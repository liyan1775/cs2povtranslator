"""Job persistence layer for CS2 POV Translator Web UI.

Replaces the v0.1 in-memory ``_jobs`` dict with a file-backed store so job
history survives server restarts and browser closes.

Format
~~~~~~
``~/.cs2tl/jobs.json`` — JSON Lines, one job object per line. Small enough
(single-user tool, maybe 100 jobs) that we rewrite the file on every mutation
rather than implementing a partial-update protocol.

Safety
~~~~~~
* Atomic writes: write to ``.tmp`` then ``os.replace()``.
* Corruption recovery: skip unparseable lines on load, log a warning.
* State machine: validates transitions (e.g. completed → running is illegal).

Migration
~~~~~~~~
On first init, scans ``~/.cs2tl/cache/`` for job directories created by v0.1.
Jobs with a ``progress.json`` are imported so the user doesn't lose history.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """Valid job states with a linear lifecycle.

    Transitions::

        CREATED ──▶ RUNNING ──▶ COMPLETED
                        │
                        └──▶ FAILED

    Once terminal (COMPLETED / FAILED), the state is immutable.
    """

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid outgoing transitions from each state
_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.CREATED: {JobStatus.RUNNING},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),  # terminal
    JobStatus.FAILED: set(),  # terminal
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class JobRecord:
    """Lightweight value object for one pipeline job."""

    job_id: str
    demo_name: str
    demo_path: str
    cache_dir: str
    status: JobStatus = JobStatus.CREATED
    created_at: str = ""  # ISO-8601
    player_count: int = 0
    team_2_names: list[str] = field(default_factory=list)
    team_3_names: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "demo_name": self.demo_name,
            "demo_path": self.demo_path,
            "cache_dir": self.cache_dir,
            "status": self.status.value,
            "created_at": self.created_at,
            "player_count": self.player_count,
            "team_2_names": self.team_2_names,
            "team_3_names": self.team_3_names,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRecord:
        raw_status = data.get("status", "created")
        try:
            status = JobStatus(raw_status)
        except ValueError:
            status = JobStatus.CREATED
        return cls(
            job_id=data.get("job_id", ""),
            demo_name=data.get("demo_name", ""),
            demo_path=data.get("demo_path", ""),
            cache_dir=data.get("cache_dir", ""),
            status=status,
            created_at=data.get("created_at", ""),
            player_count=data.get("player_count", 0),
            team_2_names=data.get("team_2_names", []),
            team_3_names=data.get("team_3_names", []),
            error=data.get("error"),
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class JobStore:
    """File-backed registry of translation jobs.

    Thread-safe for the single-user case (all writes happen on the same
    uvicorn event-loop thread).  Not safe for multi-process concurrency —
    use a real database if that ever becomes a requirement.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._path = store_path or _default_store_path()
        self._jobs: dict[str, JobRecord] = {}

    # -- lifecycle -----------------------------------------------------------

    def _migrate_from_legacy_store(self) -> None:
        """Move jobs.json from legacy location (~/.cs2tl/) to cs2tl-data/."""
        legacy_path = Path.home() / ".cs2tl" / "jobs.json"
        if legacy_path.exists() and not self._path.exists():
            import shutil
            self._path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_path), str(self._path))
            logger.info("JobStore: migrated %s → %s", legacy_path, self._path)

    def load(self) -> None:
        """Load (or reload) the job registry from disk."""
        self._migrate_from_legacy_store()
        """Load (or reload) the job registry from disk.

        Called once at startup.  Corrupted lines are skipped with a warning
        rather than crashing — losing one job's metadata is better than
        losing the entire history.
        """
        if not self._path.exists():
            logger.info("JobStore: no existing jobs.json — starting fresh")
            self._jobs = {}
            self._migrate_v0_1_cache()
            return

        loaded: dict[str, JobRecord] = {}
        corrupted = 0
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        corrupted += 1
                        logger.warning(
                            "JobStore: skipping corrupted line %d in %s",
                            line_no, self._path,
                        )
                        continue
                    record = JobRecord.from_dict(data)
                    if record.job_id:
                        loaded[record.job_id] = record
        except (OSError, json.JSONDecodeError) as exc:
            # Entire file is unreadable — rename it and start fresh
            logger.error("JobStore: cannot read %s (%s) — starting fresh", self._path, exc)
            self._jobs = {}
            self._rename_corrupt_file()
            self._migrate_v0_1_cache()
            return

        if corrupted:
            logger.warning(
                "JobStore: %d corrupted line(s) skipped in %s — rewriting clean copy",
                corrupted, self._path,
            )
            self._jobs = loaded
            self._flush()

        self._jobs = loaded
        logger.info("JobStore: loaded %d job(s) from %s", len(self._jobs), self._path)

        # Opportunistic migration for any v0.1 cache dirs not yet imported
        self._migrate_v0_1_cache()

    # -- CRUD ----------------------------------------------------------------

    def create(
        self,
        demo_name: str,
        demo_path: str,
        cache_dir: str,
        demo_info: dict[str, Any] | None = None,
        *,
        job_id: str | None = None,
    ) -> JobRecord:
        """Register a new job in CREATED state.  Does NOT start the pipeline.

        If *job_id* is ``None``, a random 8-char hex id is generated.

        Returns the new ``JobRecord`` so the caller can transition to RUNNING.
        """
        if job_id is None:
            job_id = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat()

        record = JobRecord(
            job_id=job_id,
            demo_name=demo_name,
            demo_path=demo_path,
            cache_dir=cache_dir,
            status=JobStatus.CREATED,
            created_at=now,
            player_count=demo_info.get("player_count", 0) if demo_info else 0,
            team_2_names=demo_info.get("team_2", []) if demo_info else [],
            team_3_names=demo_info.get("team_3", []) if demo_info else [],
        )
        self._jobs[job_id] = record
        self._flush()
        logger.info("JobStore: created job %s (%s)", job_id, demo_name)
        return record

    def update_status(
        self,
        job_id: str,
        new_status: JobStatus,
        error: str | None = None,
    ) -> JobRecord:
        """Transition a job to a new status.  Raises ``ValueError`` for
        illegal transitions (e.g.  COMPLETED → RUNNING)."""
        record = self._jobs.get(job_id)
        if record is None:
            raise KeyError(f"Job {job_id} not found")

        allowed = _TRANSITIONS.get(record.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition: {record.status.value} → {new_status.value} "
                f"for job {job_id}"
            )

        record.status = new_status
        if error:
            record.error = error
        self._flush()
        logger.info("JobStore: job %s → %s", job_id, new_status.value)
        return record

    def start(self, job_id: str) -> JobRecord:
        """Shorthand: CREATED → RUNNING."""
        return self.update_status(job_id, JobStatus.RUNNING)

    def complete(self, job_id: str) -> JobRecord:
        """Shorthand: RUNNING → COMPLETED."""
        return self.update_status(job_id, JobStatus.COMPLETED)

    def fail(self, job_id: str, error: str) -> JobRecord:
        """Shorthand: RUNNING → FAILED with an error message."""
        return self.update_status(job_id, JobStatus.FAILED, error=error)

    def get(self, job_id: str) -> JobRecord | None:
        """Look up a job by id.  Returns ``None`` if not found."""
        return self._jobs.get(job_id)

    def list_all(self) -> list[JobRecord]:
        """Return all jobs, newest first."""
        return sorted(
            self._jobs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )

    # -- internals -----------------------------------------------------------

    def _flush(self) -> None:
        """Atomically write the in-memory registry to disk.

        Writes to a temp file first, then ``os.replace()`` which is atomic
        on all platforms we care about (POSIX + Windows).
        """
        tmp_path = self._path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                for record in self._jobs.values():
                    fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.error("JobStore: flush failed — %s", exc)
            raise

    def _rename_corrupt_file(self) -> None:
        """Rename the unreadable jobs.json so we can start fresh."""
        backup = self._path.with_suffix(".json.corrupt-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
        try:
            os.rename(self._path, backup)
            logger.warning("JobStore: renamed corrupt file to %s", backup)
        except OSError:
            pass

    def _migrate_v0_1_cache(self) -> None:
        """Scan the cache directory for v0.1 job dirs and import them.

        v0.1 jobs live in ``~/.cs2tl/cache/<job_id>/`` and contain a
        ``progress.json`` file.  We infer the job status from that file
        and import any job that isn't already in the registry.
        """
        cache_root = Path(self._path).parent / "cache"
        if not cache_root.exists():
            return

        imported = 0
        for entry in sorted(cache_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name in self._jobs:
                continue  # already tracked

            progress_file = entry / "progress.json"
            if not progress_file.exists():
                continue

            # Infer status from progress.json
            status = JobStatus.RUNNING  # default — pipeline may have crashed
            error: str | None = None
            demo_name = ""
            try:
                data = json.loads(progress_file.read_text(encoding="utf-8"))
                if data.get("error"):
                    status = JobStatus.FAILED
                    error = data["error"]
                elif data.get("done", 0) >= data.get("total", 7):
                    status = JobStatus.COMPLETED
                demo_name_from_dir = _guess_demo_name(entry)
                if demo_name_from_dir:
                    demo_name = demo_name_from_dir
            except (json.JSONDecodeError, OSError):
                status = JobStatus.FAILED
                error = "progress.json is corrupted"

            if not demo_name:
                demo_name = entry.name

            now = datetime.now(timezone.utc).isoformat()
            record = JobRecord(
                job_id=entry.name,
                demo_name=demo_name,
                demo_path="",
                cache_dir=str(entry),
                status=status,
                created_at=now,
                error=error,
            )
            self._jobs[record.job_id] = record
            imported += 1
            logger.info(
                "JobStore: migrated v0.1 job %s (%s) → %s",
                entry.name, demo_name, status.value,
            )

        if imported:
            self._flush()
            logger.info("JobStore: migrated %d v0.1 job(s)", imported)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_store_path() -> Path:
    """Return ``{data_dir}/jobs.json`` so deleting cs2tl-data/ wipes everything."""
    from cs2tl.config import default_data_dir
    path = default_data_dir() / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _guess_demo_name(cache_dir: Path) -> str:
    """Try to find a .dem or .dem.zst file in the cache dir for the name."""
    for ext in (".dem.zst", ".dem"):
        candidates = list(cache_dir.glob(f"*{ext}"))
        if candidates:
            return candidates[0].name
    return ""
