"""Replay the current round orchestration through real child processes."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from cs2pov.application.job_coordinator import JobRoundCoordinator
from cs2pov.application.round_scheduler import RoundScheduler, RoundSchedulerSettings
from cs2pov.application.round_worker import RoundWorkResult
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import ModelInvocationRecord
from cs2pov.domain.job import CreateJobRequest, JobDemoSource, JobWriteClaim
from cs2pov.domain.job_tasks import RetryPolicy
from cs2pov.domain.understanding import RoundUnderstandingDocument, UnderstandingResult
from cs2pov.domain.validation import compose_draft_timeline
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths

FIXTURE = ROOT / "tests/golden/fixtures/new_round_orchestration_v1.json"
REPOSITORY_FIXTURE = ROOT / "tests/golden/fixtures/new_job_repository_v1.json"
DOMAIN_FIXTURE = ROOT / "tests/golden/fixtures/new_domain_contract_v1.json"
CLAIM_ACQUIRED_AT = "2026-09-13T00:00:00.000000Z"
PRE_EXPIRY_AT = "2026-09-13T00:00:10.000000Z"
POST_EXPIRY_AT = "2026-09-13T00:00:31.000000Z"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"fixture root is not an object: {path.name}")
    return value


def _clock(value: str):
    current = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    return lambda: current.replace(tzinfo=timezone.utc)


def _advancing_clock(value: str):
    current = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )

    def now():
        nonlocal current
        value = current
        current += timedelta(microseconds=1)
        return value

    return now


def _repository(root: Path, clock=None) -> FileSystemJobRepository:
    paths = WorkspacePaths(root)
    clock = clock or (lambda: datetime.now(timezone.utc))
    assets = FileSystemDemoAssetRepository(paths, clock=clock)
    return FileSystemJobRepository(paths, assets, clock=clock)


def _tree_snapshot(root: Path) -> tuple[tuple[str, bytes | None], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes() if path.is_file() else None)
        for path in sorted((root, *root.rglob("*")), key=lambda item: item.as_posix())
    )


def _seed(root: Path) -> None:
    # Reuse the repository contract's anonymous synthetic graph so this replay
    # exercises the same durable inputs as the preceding repository checker.
    from scripts.check_new_job_repository import (
        _build_domain,
        _domain_payload,
        _load_json,
    )

    payload = _load_json(REPOSITORY_FIXTURE)
    raw_domain = _domain_payload(payload, DOMAIN_FIXTURE)
    paths = WorkspacePaths(root)
    fixed_clock = _advancing_clock(CLAIM_ACQUIRED_AT)
    assets = FileSystemDemoAssetRepository(paths, clock=fixed_clock)
    source_file = root / "input" / "fixture.dem"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"anonymous synthetic demo")
    imported = assets.import_source(source_file).asset
    domain = _build_domain(raw_domain, imported.asset_id, payload["job"]["review"])
    repository = FileSystemJobRepository(paths, assets, clock=fixed_clock)
    job = payload["job"]
    source = JobDemoSource(
        imported.asset_id,
        f"library/demos/{imported.asset_id}/asset.json",
        imported.display_name,
    )
    repository.create_job(CreateJobRequest(job["job_id"], job["display_name"], source))
    session = repository.acquire_write(job["job_id"], lease_us=30_000_000)
    claim = session.claim
    repository.save_demo_timeline(job["job_id"], domain.timeline, claim)
    repository.save_voice_activities(job["job_id"], domain.activities, claim)
    for configuration in domain.configurations:
        current = repository.load_job(job["job_id"])
        repository.register_model_configuration(
            job["job_id"], configuration, current.manifest.content_fingerprint(), claim
        )
    for task_id in sorted({value.task_id for value in domain.invocations}):
        repository.save_task_invocations(
            job["job_id"], task_id,
            tuple(value for value in domain.invocations if value.task_id == task_id), claim
        )
    for round_value in domain.timeline.rounds.rounds:
        repository.save_transcript_round(
            job["job_id"], round_value.round_id,
            tuple(value for value in domain.transcripts if value.round_id == round_value.round_id),
            claim,
        )
    repository.save_unassigned_transcript(
        job["job_id"], tuple(value for value in domain.transcripts if value.round_id is None), claim
    )
    session.release()
    source = JobDemoSource(
        imported.asset_id,
        f"library/demos/{imported.asset_id}/asset.json",
        imported.display_name,
    )
    repository.create_job(CreateJobRequest("job-corrupt", "Corrupt sibling", source))
    corrupt = repository.load_job("job-corrupt")
    corrupt.paths.demo_timeline.write_bytes(b"{malformed")
    repository.create_job(CreateJobRequest("job-unsupported", "Unsupported sibling", source))
    unsupported = repository.load_job("job-unsupported")
    manifest = json.loads(unsupported.paths.manifest.read_text(encoding="utf-8"))
    manifest["schema_version"] = 2
    unsupported.paths.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


class _FixtureWorker:
    def __init__(self, *, reverse: bool = False):
        self.reverse = reverse
        self.calls = []
        self.round_three_started = asyncio.Event()
        self.round_three_release = asyncio.Event()
        self.round_one_release = asyncio.Event()

    async def translate(self, request):
        self.calls.append(request.round_id)
        if self.reverse and request.round_id == "round-001":
            await self.round_one_release.wait()
        if self.reverse and request.round_id == "round-003":
            self.round_three_started.set()
            await self.round_three_release.wait()
        results = tuple(
            UnderstandingResult(
                cue.cue_id,
                request.round_id,
                cue.asr_original,
                cue.asr_original,
                f"合成翻译:{cue.asr_original}",
                0.9,
                ("synthetic-replay",),
                (),
                f"invoke-replay-{request.round_id}",
            )
            for cue in request.cues
        )
        invocation = None
        invocations = ()
        if results:
            response_hash = content_fingerprint(
                {"round_id": request.round_id, "results": [item.to_dict() for item in results]}
            )
            invocation = ModelInvocationRecord(
                f"invoke-replay-{request.round_id}",
                request.configuration.snapshot_id,
                request.task_id,
                request.document_input_fingerprint,
                response_hash,
            )
            invocations = (invocation,)
        return RoundWorkResult(
            RoundUnderstandingDocument(
                request.round_id,
                request.document_input_fingerprint,
                request.configuration.snapshot_id,
                None if invocation is None else invocation.invocation_id,
                results,
            ),
            invocations,
        )


def _coordinator(repository: FileSystemJobRepository) -> JobRoundCoordinator:
    return JobRoundCoordinator(
        repository,
        clock=repository.clock,
        event_id_factory=lambda: f"event-replay-{uuid4().hex}",
    )


async def _checkpoint_result(
    coordinator: JobRoundCoordinator,
    task,
    request,
    claim,
) -> None:
    result = await _FixtureWorker().translate(request)
    coordinator.checkpoint_success(task, result, claim=claim)


def _producer(root: Path, job_id: str) -> None:
    repository = _repository(root, _advancing_clock(CLAIM_ACQUIRED_AT))
    coordinator = _coordinator(repository)
    session = repository.acquire_write(job_id, lease_us=30_000_000)
    prepared = coordinator.prepare_translation(
        job_id, configuration_snapshot_id="llm-config-001", claim=session.claim
    )
    requests = {request.task_id: request for request in prepared.requests}
    round_two = next(task for task in prepared.tasks if task.round_id == "round-002")
    round_two_running = coordinator.mark_running(
        round_two, attempt_id="attempt-producer-002", claim=session.claim
    )
    asyncio.run(
        _checkpoint_result(
            coordinator,
            round_two_running,
            requests["round-002"],
            session.claim,
        )
    )
    coordinator.mark_running(prepared.tasks[0], attempt_id="attempt-producer-001", claim=session.claim)
    print("producer status: running", flush=True)
    os._exit(73)


async def _consumer(root: Path, job_id: str) -> None:
    live_repository = _repository(root, _clock(PRE_EXPIRY_AT))
    job_root = live_repository.load_job(job_id).paths.job_dir
    stale_claim = JobWriteClaim.from_dict(
        json.loads(
            live_repository.load_job(job_id).paths.writer_claim.read_text(
                encoding="utf-8"
            )
        )
    )
    before_busy_check = _tree_snapshot(job_root)
    live_repository.list_jobs()
    live_repository.inspect_job(job_id)
    if _tree_snapshot(job_root) != before_busy_check:
        raise ValueError("read-only inspection mutated the Job tree")
    try:
        live_repository.acquire_write(job_id, lease_us=30_000_000)
    except JobRepositoryError as error:
        if error.code != "job_write_busy":
            raise
    else:
        raise ValueError("active producer claim was not enforced")
    if _tree_snapshot(job_root) != before_busy_check:
        raise ValueError("busy claim check mutated the Job tree")
    repository = _repository(root, _clock(POST_EXPIRY_AT))
    takeover = repository.acquire_write(job_id, lease_us=30_000_000)
    if takeover.claim.run_id == stale_claim.run_id:
        raise ValueError("expired claim did not change run identity")
    takeover.release()
    stale_archives = tuple(
        path
        for path in repository.load_job(job_id).paths.events_dir.iterdir()
        if path.name.startswith(".writer_claim.stale-")
    )
    if not stale_archives:
        raise ValueError("expired claim was not archived")
    coordinator = _coordinator(repository)
    worker = _FixtureWorker(reverse=True)
    scheduler = RoundScheduler(coordinator, worker)

    async def run_scheduler():
        return await scheduler.run(
            job_id,
            configuration_snapshot_id="llm-config-001",
            settings=RoundSchedulerSettings(
                max_concurrency=2,
                claim_lease_us=30_000_000,
                heartbeat_interval_us=1_000_000,
                retry_policy=RetryPolicy(
                    max_attempts=2, base_delay_us=1_000_000, max_delay_us=2_000_000
                ),
            ),
        )

    scheduled = asyncio.create_task(run_scheduler())
    await worker.round_three_started.wait()
    worker.round_three_release.set()
    while repository.load_round_tasks(job_id)[2].status.value != "succeeded":
        await asyncio.sleep(0)
    worker.round_one_release.set()
    report = await scheduled
    expected_rounds = ["round-001", "round-002", "round-003"]
    if [task.round_id for task in report.tasks] != expected_rounds:
        raise ValueError("consumer did not close the complete round set")
    if any(task.status.value != "succeeded" for task in report.tasks):
        raise ValueError("consumer left a round unfinished")
    if list(report.completion_order) != ["round-003", "round-001"]:
        raise ValueError(
            f"completion order was not observed in reverse order: {report.completion_order!r}"
        )
    recovered = report.tasks[0].attempts
    if not recovered or recovered[0].attempt_id != "attempt-producer-001":
        raise ValueError("producer attempt was not retained during recovery")
    round_two = next(task for task in report.tasks if task.round_id == "round-002")
    if round_two.status.value != "succeeded" or not round_two.attempts:
        raise ValueError("checkpointed sibling result was not retained")
    if set(worker.calls) != {"round-001", "round-003"}:
        raise ValueError("resume reran a reusable sibling or skipped a pending round")
    if repository.load_job(job_id).paths.writer_claim.exists():
        raise ValueError("consumer left a writer claim behind")

    print("consumer status: succeeded")
    print(f"completion order size: {len(report.completion_order)}")


def _final_consumer(root: Path, job_id: str) -> None:
    repository = _repository(root, _clock(POST_EXPIRY_AT))
    language = repository.load_language_graph(job_id)
    draft = compose_draft_timeline(
        language.timeline,
        language.transcripts,
        language.understanding_documents,
        language.configurations,
        language.invocations,
    )
    if tuple(cue.cue_id for cue in draft.cues) != tuple(
        cue.cue_id
        for cue in sorted(
            (cue for cue in language.transcripts if cue.round_id is not None),
            key=lambda cue: (cue.time_range.start_us, cue.time_range.end_us, cue.cue_id),
        )
    ):
        raise ValueError("draft cue order was not canonical")
    catalog = {entry.discovery_id: entry for entry in repository.list_jobs()}
    if not catalog[job_id].healthy:
        raise ValueError("completed primary Job was not inspected")
    if catalog["job-corrupt"].healthy or catalog["job-unsupported"].healthy:
        raise ValueError("sibling corruption was not isolated")
    print("final status: validated")


def _child(mode: str, root: Path, job_id: str) -> int:
    if mode == "producer":
        _seed(root)
        _producer(root, job_id)
    elif mode == "consumer":
        asyncio.run(_consumer(root, job_id))
    else:
        _final_consumer(root, job_id)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("producer", "consumer", "final"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args()
    fixture = _load(args.fixture)
    if fixture.get("fixture_id") != "new-round-orchestration-v1":
        raise SystemExit("invalid orchestration fixture")
    expected = fixture.get("expected")
    if expected != {
        "producer_status": "running",
        "consumer_status": "succeeded",
        "round_ids": ["round-001", "round-002", "round-003"],
        "recovered_attempts": 1,
        "completion_order_size": 2,
        "producer_exit_code": 73,
        "pre_expiry_error": "job_write_busy",
        "recovered_attempt_id": "attempt-producer-001",
        "reused_round_id": "round-002",
        "completion_order": ["round-003", "round-001"],
    }:
        raise SystemExit("invalid orchestration expectations")
    if args.mode:
        return _child(args.mode, args.root.resolve(), fixture["job_id"])
    with tempfile.TemporaryDirectory(prefix="round-orchestration-") as value:
        root = Path(value)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "src"), environment.get("PYTHONPATH", "")))
        for mode in ("producer", "consumer", "final"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--mode", mode, "--root", str(root)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            expected_code = 73 if mode == "producer" else 0
            if result.returncode != expected_code:
                sys.stderr.write(result.stderr)
                return result.returncode
            if mode == "producer" and "producer status: running" not in result.stdout:
                return 1
            if mode == "consumer" and (
                "consumer status: succeeded" not in result.stdout
                or "completion order size: 2" not in result.stdout
            ):
                return 1
            if mode == "final" and "final status: validated" not in result.stdout:
                return 1
    print("round orchestration replay passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
