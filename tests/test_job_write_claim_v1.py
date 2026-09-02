from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import UUID

import pytest

from cs2pov.domain.job import (
    CreateJobRequest,
    JobDemoSource,
    JobPhase,
    JobRunStatus,
    JobWriteClaim,
)
from cs2pov.storage.cross_process_lock import CrossProcessFileLock
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_claim import CLAIM_INITIALIZATION_GRACE_US, JobWriteSession
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths


NOW = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)
RUN_1 = UUID("11111111-1111-4111-8111-111111111111")
RUN_2 = UUID("22222222-2222-4222-8222-222222222222")


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance_us(self, value: int) -> None:
        self.value += timedelta(microseconds=value)


def _seed(tmp_path: Path, *, clock=None, run_ids=(RUN_1, RUN_2), process_id=4242):
    tmp_path.mkdir(parents=True, exist_ok=True)
    workspace = WorkspacePaths(tmp_path / "workspace")
    demo_file = tmp_path / "match.dem"
    demo_file.write_bytes(b"writer-claim-demo")
    demo_assets = FileSystemDemoAssetRepository(workspace, clock=lambda: NOW)
    asset = demo_assets.import_source(demo_file).asset
    source = JobDemoSource(
        asset.asset_id,
        f"library/demos/{asset.asset_id}/asset.json",
        asset.display_name,
    )
    FileSystemJobRepository(workspace, demo_assets, clock=lambda: NOW).create_job(
        CreateJobRequest("job-claim", "Claim Job", source)
    )
    mutable_clock = clock or MutableClock()
    values = iter(run_ids)
    repository = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=mutable_clock,
        run_id_factory=lambda: next(values),
        process_id_supplier=lambda: process_id,
    )
    return workspace, demo_assets, repository, mutable_clock, source


def _snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    rows = []
    if not root.exists():
        return ()
    pending = [root]
    while pending:
        path = pending.pop()
        state = path.lstat()
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            payload = ("link", os.readlink(path))
        elif path.is_file():
            payload = ("file", path.read_bytes())
        else:
            payload = ("dir",)
            pending.extend(path.iterdir())
        rows.append((relative, state.st_mode, state.st_size, state.st_mtime_ns, payload))
    return tuple(sorted(rows, key=lambda item: str(item[0])))


def _claim_path(workspace: WorkspacePaths) -> Path:
    return workspace.jobs_dir / "job-claim/events/.writer_claim/claim.json"


def _next_manifest(opened, *, at: datetime, phase=None, status=None):
    timestamp = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return replace(
        opened.manifest,
        updated_at=timestamp,
        phase=phase or opened.manifest.phase,
        run_status=status or opened.manifest.run_status,
    )


def test_acquire_publishes_complete_private_free_claim_and_second_live_owner_is_busy(tmp_path):
    workspace, _, repository, _, _ = _seed(tmp_path)

    session = repository.acquire_write("job-claim", lease_us=30_000_000)

    assert isinstance(session, JobWriteSession)
    assert session.claim.job_id == "job-claim"
    assert session.claim.run_id == "run-11111111111141118111111111111111"
    assert session.claim.process_id == 4242
    assert session.claim.acquired_at == "2026-08-31T16:00:00.000000Z"
    assert session.claim.heartbeat_at == session.claim.acquired_at
    assert session.claim.lease_expires_at == "2026-08-31T16:00:30.000000Z"
    payload = json.loads(_claim_path(workspace).read_text("utf-8"))
    assert payload == session.claim.to_dict()
    serialized = json.dumps(payload).lower()
    for forbidden in (
        "hostname",
        "username",
        "command",
        "executable",
        "cwd",
        str(workspace.root).lower(),
    ):
        assert forbidden not in serialized

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.acquire_write("job-claim", lease_us=30_000_000)

    assert exc_info.value.code == "job_write_busy"
    assert json.loads(_claim_path(workspace).read_text("utf-8")) == payload


def test_live_claim_conflicts_even_when_contender_has_same_pid(tmp_path):
    workspace, demo_assets, first, clock, _ = _seed(tmp_path, process_id=777)
    first.acquire_write("job-claim", lease_us=10_000_000)
    second = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=clock,
        run_id_factory=lambda: RUN_2,
        process_id_supplier=lambda: 777,
    )

    with pytest.raises(JobRepositoryError) as exc_info:
        second.acquire_write("job-claim", lease_us=10_000_000)

    assert exc_info.value.code == "job_write_busy"


def test_heartbeat_extends_from_current_clock_and_release_is_idempotent(tmp_path):
    workspace, _, repository, clock, _ = _seed(tmp_path)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    clock.advance_us(3_000_000)

    heartbeat = session.heartbeat()

    assert heartbeat.run_id == session.claim.run_id
    assert heartbeat.heartbeat_at == "2026-08-31T16:00:03.000000Z"
    assert heartbeat.lease_expires_at == "2026-08-31T16:00:13.000000Z"
    assert JobWriteClaim.from_dict(
        json.loads(_claim_path(workspace).read_text("utf-8"))
    ) == heartbeat

    session.release()
    session.release()
    assert not _claim_path(workspace).parent.exists()


def test_acquisition_lease_starts_after_waiting_for_the_os_lock(tmp_path):
    workspace, demo_assets, _, clock, _ = _seed(tmp_path)

    class AdvancingLockFactory:
        @classmethod
        def open_existing(cls, path, *, timeout_ms):
            inner = CrossProcessFileLock.open_existing(path, timeout_ms=timeout_ms)

            class Context:
                def __enter__(self):
                    locked = inner.__enter__()
                    clock.advance_us(7_000_000)
                    return locked

                def __exit__(self, exc_type, exc, traceback):
                    return inner.__exit__(exc_type, exc, traceback)

            return Context()

        @classmethod
        def bootstrap_for_write(cls, path, *, timeout_ms):
            return CrossProcessFileLock.bootstrap_for_write(path, timeout_ms=timeout_ms)

    repository = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=clock,
        run_id_factory=lambda: RUN_1,
        process_id_supplier=lambda: 1,
        lock_factory=AdvancingLockFactory,
    )

    session = repository.acquire_write("job-claim", lease_us=10_000_000)

    assert session.claim.acquired_at == "2026-08-31T16:00:07.000000Z"
    assert session.claim.lease_expires_at == "2026-08-31T16:00:17.000000Z"


def test_non_owner_cannot_heartbeat_release_or_replace_manifest(tmp_path):
    workspace, _, repository, clock, _ = _seed(tmp_path)
    owner = repository.acquire_write("job-claim", lease_us=10_000_000)
    active_bytes = _claim_path(workspace).read_bytes()
    fake = replace(owner.claim, run_id="run-not-owner")
    intruder = JobWriteSession(repository, "job-claim", fake)
    opened = repository.load_job("job-claim")
    clock.advance_us(1)
    new_manifest = _next_manifest(opened, at=clock.value, phase=JobPhase.TIMELINE_READY)

    for operation in (
        intruder.heartbeat,
        intruder.release,
        lambda: repository.replace_manifest(
            "job-claim",
            opened.manifest.content_fingerprint(),
            new_manifest,
            fake,
        ),
    ):
        with pytest.raises(JobRepositoryError) as exc_info:
            operation()
        assert exc_info.value.code == "job_write_interrupted"
        assert _claim_path(workspace).read_bytes() == active_bytes
        assert repository.load_job("job-claim").manifest == opened.manifest


def test_expired_claim_is_archived_and_old_writer_is_fenced(tmp_path):
    workspace, demo_assets, repository, clock, _ = _seed(tmp_path)
    old = repository.acquire_write("job-claim", lease_us=5_000_000)
    opened = repository.load_job("job-claim")
    clock.advance_us(5_000_001)
    contender = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=clock,
        run_id_factory=lambda: RUN_2,
        process_id_supplier=lambda: 9000,
    )

    current = contender.acquire_write("job-claim", lease_us=10_000_000)

    assert current.claim.run_id != old.claim.run_id
    archives = tuple(
        path
        for path in (workspace.jobs_dir / "job-claim/events").iterdir()
        if path.name.startswith(".writer_claim.stale-")
    )
    assert len(archives) == 1
    assert (archives[0] / "claim.json").exists()
    with pytest.raises(JobRepositoryError) as heartbeat_error:
        old.heartbeat()
    assert heartbeat_error.value.code == "job_write_interrupted"
    clock.advance_us(1)
    attempted = _next_manifest(opened, at=clock.value, phase=JobPhase.TIMELINE_READY)
    with pytest.raises(JobRepositoryError) as replace_error:
        repository.replace_manifest(
            "job-claim",
            opened.manifest.content_fingerprint(),
            attempted,
            old.claim,
        )
    assert replace_error.value.code == "job_write_interrupted"


def test_recent_incomplete_claim_is_invalid_but_old_incomplete_claim_can_be_displaced(tmp_path):
    workspace, _, repository, clock, _ = _seed(tmp_path)
    claim_dir = _claim_path(workspace).parent
    claim_dir.mkdir()
    current_seconds = clock.value.timestamp()
    os.utime(claim_dir, (current_seconds, current_seconds))

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.acquire_write("job-claim", lease_us=10_000_000)

    assert exc_info.value.code == "job_claim_invalid"
    assert claim_dir.is_dir()

    old_seconds = current_seconds - (CLAIM_INITIALIZATION_GRACE_US + 1) / 1_000_000
    os.utime(claim_dir, (old_seconds, old_seconds))
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    assert session.claim.run_id.startswith("run-")
    assert any(
        path.name.startswith(".writer_claim.stale-")
        for path in claim_dir.parent.iterdir()
    )


@pytest.mark.parametrize("lease_us", [True, 0, -1, 1.5, None])
def test_acquire_rejects_invalid_lease_duration(tmp_path, lease_us):
    _, _, repository, _, _ = _seed(tmp_path)

    with pytest.raises((JobRepositoryError, TypeError, ValueError)):
        repository.acquire_write("job-claim", lease_us=lease_us)


def test_claim_rejects_naive_and_backwards_clocks(tmp_path):
    naive = MutableClock(datetime(2026, 8, 31, 16, 0))
    _, _, repository, _, _ = _seed(tmp_path, clock=naive)
    with pytest.raises(JobRepositoryError):
        repository.acquire_write("job-claim", lease_us=10_000_000)

    aware = MutableClock()
    _, _, repository, _, _ = _seed(tmp_path / "backwards", clock=aware)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    aware.value -= timedelta(microseconds=1)
    with pytest.raises(JobRepositoryError) as exc_info:
        session.heartbeat()
    assert exc_info.value.code == "job_claim_invalid"


def test_missing_or_expired_claim_projects_running_to_interrupted_without_writes(tmp_path):
    workspace, _, repository, clock, _ = _seed(tmp_path)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    clock.advance_us(1)
    running = _next_manifest(
        opened,
        at=clock.value,
        phase=JobPhase.UNDERSTANDING_TRANSLATING,
        status=JobRunStatus.RUNNING,
    )
    repository.replace_manifest(
        "job-claim",
        opened.manifest.content_fingerprint(),
        running,
        session.claim,
    )
    assert repository.load_job("job-claim").effective_run_status is JobRunStatus.RUNNING

    session.release()
    before = _snapshot(workspace.jobs_dir / "job-claim")
    reopened = repository.load_job("job-claim")
    inspection = repository.inspect_job("job-claim")
    after = _snapshot(workspace.jobs_dir / "job-claim")

    assert reopened.manifest.run_status is JobRunStatus.RUNNING
    assert reopened.effective_run_status is JobRunStatus.INTERRUPTED
    assert inspection.entry.durable_run_status is JobRunStatus.RUNNING
    assert inspection.entry.effective_run_status is JobRunStatus.INTERRUPTED
    assert after == before


def test_load_rechecks_manifest_with_claim_to_avoid_false_interruption(tmp_path):
    workspace, demo_assets, owner, clock, _ = _seed(tmp_path)
    session = owner.acquire_write("job-claim", lease_us=10_000_000)
    initial = owner.load_job("job-claim")
    clock.advance_us(1)
    running = _next_manifest(initial, at=clock.value, status=JobRunStatus.RUNNING)
    owner.replace_manifest(
        "job-claim",
        initial.manifest.content_fingerprint(),
        running,
        session.claim,
    )
    clock.advance_us(1)
    succeeded = _next_manifest(
        replace(initial, manifest=running),
        at=clock.value,
        status=JobRunStatus.SUCCEEDED,
    )
    completed = False

    class CompletingLockFactory:
        @classmethod
        def open_existing(cls, path, *, timeout_ms):
            inner = CrossProcessFileLock.open_existing(path, timeout_ms=timeout_ms)

            class Context:
                def __enter__(self):
                    nonlocal completed
                    if not completed:
                        owner.replace_manifest(
                            "job-claim",
                            running.content_fingerprint(),
                            succeeded,
                            session.claim,
                        )
                        session.release()
                        completed = True
                    return inner.__enter__()

                def __exit__(self, exc_type, exc, traceback):
                    return inner.__exit__(exc_type, exc, traceback)

            return Context()

        @classmethod
        def bootstrap_for_write(cls, path, *, timeout_ms):
            return CrossProcessFileLock.bootstrap_for_write(path, timeout_ms=timeout_ms)

    reader = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=clock,
        lock_factory=CompletingLockFactory,
    )

    inspection = reader.inspect_job("job-claim")
    reopened = reader.load_job("job-claim")

    assert inspection.entry.durable_run_status is JobRunStatus.SUCCEEDED
    assert inspection.entry.effective_run_status is JobRunStatus.SUCCEEDED
    assert reopened.manifest.run_status is JobRunStatus.SUCCEEDED
    assert reopened.effective_run_status is JobRunStatus.SUCCEEDED


@pytest.mark.parametrize("status", [JobRunStatus.PENDING, JobRunStatus.FAILED, JobRunStatus.SUCCEEDED])
def test_non_running_status_is_never_projected_to_interrupted(tmp_path, status):
    workspace, demo_assets, repository, clock, _ = _seed(tmp_path)
    if status is JobRunStatus.PENDING:
        assert repository.load_job("job-claim").effective_run_status is status
        return
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    clock.advance_us(1)
    changed = _next_manifest(opened, at=clock.value, status=status)
    repository.replace_manifest(
        "job-claim", opened.manifest.content_fingerprint(), changed, session.claim
    )
    session.release()

    reopened = FileSystemJobRepository(workspace, demo_assets, clock=clock).load_job(
        "job-claim"
    )
    assert reopened.effective_run_status is status


def test_malformed_active_claim_is_diagnosed_without_changing_pending_status(tmp_path):
    workspace, _, repository, _, _ = _seed(tmp_path)
    claim_dir = _claim_path(workspace).parent
    claim_dir.mkdir()
    _claim_path(workspace).write_text("{}\n", encoding="utf-8")

    inspection = repository.inspect_job("job-claim")

    assert inspection.entry.durable_run_status is JobRunStatus.PENDING
    assert inspection.entry.effective_run_status is JobRunStatus.PENDING
    assert any(issue.code == "job_claim_invalid" for issue in inspection.entry.issues)
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job("job-claim")
    assert exc_info.value.code == "job_claim_invalid"


def test_live_claim_keeps_running_without_pid_liveness_probe(tmp_path):
    _, _, repository, clock, _ = _seed(tmp_path, process_id=999_999_999)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    clock.advance_us(1)
    running = _next_manifest(opened, at=clock.value, status=JobRunStatus.RUNNING)
    repository.replace_manifest(
        "job-claim", opened.manifest.content_fingerprint(), running, session.claim
    )

    assert repository.load_job("job-claim").effective_run_status is JobRunStatus.RUNNING


def test_replace_manifest_is_claim_fenced_compare_and_swap_without_phase_policy(tmp_path):
    _, _, repository, clock, _ = _seed(tmp_path)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    old_bytes = opened.paths.manifest.read_bytes()
    clock.advance_us(1)
    changed = _next_manifest(
        opened,
        at=clock.value,
        phase=JobPhase.REVIEWED,
        status=JobRunStatus.RUNNING,
    )

    with pytest.raises(JobRepositoryError) as conflict:
        repository.replace_manifest("job-claim", "0" * 64, changed, session.claim)
    assert conflict.value.code == "job_manifest_conflict"
    assert opened.paths.manifest.read_bytes() == old_bytes

    replaced = repository.replace_manifest(
        "job-claim",
        opened.manifest.content_fingerprint(),
        changed,
        session.claim,
    )
    assert replaced.manifest == changed
    assert replaced.effective_run_status is JobRunStatus.RUNNING


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: replace(manifest, job_id="other-job"),
        lambda manifest: replace(manifest, demo_asset_id="0" * 64),
        lambda manifest: replace(manifest, demo_display_name="other.dem"),
        lambda manifest: replace(manifest, created_at="2026-08-31T15:59:59.000000Z"),
        lambda manifest: replace(manifest, updated_at=manifest.updated_at),
    ],
)
def test_replace_manifest_rejects_identity_or_non_forward_timestamp(tmp_path, mutation):
    _, _, repository, _, _ = _seed(tmp_path)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    candidate = mutation(opened.manifest)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.replace_manifest(
            "job-claim",
            opened.manifest.content_fingerprint(),
            candidate,
            session.claim,
        )

    assert exc_info.value.code in {"job_manifest_conflict", "job_manifest_invalid"}
    assert repository.load_job("job-claim").manifest == opened.manifest


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: replace(
            manifest, configuration_snapshot_ids=("missing-snapshot",)
        ),
        lambda manifest: replace(manifest, active_review_id="missing-review"),
    ],
)
def test_replace_manifest_rejects_missing_durable_references(tmp_path, mutation):
    _, _, repository, clock, _ = _seed(tmp_path)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    clock.advance_us(1)
    candidate = replace(
        mutation(opened.manifest),
        updated_at=clock.value.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.replace_manifest(
            "job-claim",
            opened.manifest.content_fingerprint(),
            candidate,
            session.claim,
        )

    assert exc_info.value.code == "job_shard_missing"
    assert repository.load_job("job-claim").manifest == opened.manifest


def test_replace_manifest_pre_replace_failure_preserves_old_manifest(
    tmp_path, monkeypatch
):
    _, _, repository, clock, _ = _seed(tmp_path)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    old_bytes = opened.paths.manifest.read_bytes()
    clock.advance_us(1)
    changed = _next_manifest(opened, at=clock.value, phase=JobPhase.TIMELINE_READY)
    import cs2pov.storage.atomic_documents as atomic_documents

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(atomic_documents.os, "replace", fail_replace)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.replace_manifest(
            "job-claim",
            opened.manifest.content_fingerprint(),
            changed,
            session.claim,
        )

    assert exc_info.value.code == "job_write_failed"
    assert opened.paths.manifest.read_bytes() == old_bytes


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is a POSIX durability step")
def test_replace_manifest_post_replace_fsync_failure_leaves_new_manifest_visible(tmp_path, monkeypatch):
    _, _, repository, clock, _ = _seed(tmp_path)
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    opened = repository.load_job("job-claim")
    clock.advance_us(1)
    changed = _next_manifest(opened, at=clock.value, phase=JobPhase.TIMELINE_READY)
    import cs2pov.storage.atomic_documents as atomic_documents

    def fail_parent_fsync(_path, _logical_path):
        raise OSError("injected parent fsync failure")

    monkeypatch.setattr(atomic_documents, "_fsync_directory", fail_parent_fsync)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.replace_manifest(
            "job-claim",
            opened.manifest.content_fingerprint(),
            changed,
            session.claim,
        )

    assert exc_info.value.code == "job_write_durability_uncertain"
    assert repository.load_job("job-claim").manifest == changed


def test_all_claim_mutations_use_same_existing_write_lock(tmp_path):
    workspace, demo_assets, _, clock, _ = _seed(tmp_path)
    calls = []

    class RecordingLockFactory:
        @classmethod
        def open_existing(cls, path, *, timeout_ms):
            calls.append(("open", Path(path)))
            return CrossProcessFileLock.open_existing(path, timeout_ms=timeout_ms)

        @classmethod
        def bootstrap_for_write(cls, path, *, timeout_ms):
            calls.append(("bootstrap", Path(path)))
            return CrossProcessFileLock.bootstrap_for_write(path, timeout_ms=timeout_ms)

    repository = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=clock,
        run_id_factory=lambda: RUN_1,
        process_id_supplier=lambda: 1,
        lock_factory=RecordingLockFactory,
    )
    session = repository.acquire_write("job-claim", lease_us=10_000_000)
    clock.advance_us(1)
    session.heartbeat()
    opened = repository.load_job("job-claim")
    clock.advance_us(1)
    changed = _next_manifest(opened, at=clock.value, phase=JobPhase.TIMELINE_READY)
    repository.replace_manifest(
        "job-claim", opened.manifest.content_fingerprint(), changed, session.claim
    )
    session.release()

    expected = workspace.jobs_dir / "job-claim/events/.write.lock"
    assert calls
    assert {path for _, path in calls} == {expected}
    assert all(kind == "open" for kind, _ in calls)


def test_takeover_waits_until_validated_manifest_publication_leaves_lock(
    tmp_path, request
):
    workspace, demo_assets, repository, _, _ = _seed(tmp_path)
    repository.acquire_write("job-claim", lease_us=5)
    holder_ready = tmp_path / "holder-ready"
    holder_release = tmp_path / "holder-release"
    contender_entered = tmp_path / "contender-entered"
    children = []

    def cleanup_children():
        holder_release.write_text("release", encoding="ascii")
        for child in children:
            if child.poll() is None:
                child.terminate()
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate(timeout=5)

    request.addfinalizer(cleanup_children)

    holder_worker = r"""
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

from cs2pov.domain.job import JobPhase, JobWriteClaim
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
import cs2pov.storage.job_repository as job_repository_module
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths

root, ready, release = sys.argv[1:]
paths = WorkspacePaths(Path(root))
clock = lambda: datetime(2026, 8, 31, 16, 0, 0, 1, tzinfo=timezone.utc)
repository = FileSystemJobRepository(paths, FileSystemDemoAssetRepository(paths), clock=clock)
opened = repository.load_job("job-claim")
claim = JobWriteClaim.from_dict(json.loads(opened.paths.writer_claim.read_text("utf-8")))
candidate = replace(
    opened.manifest,
    updated_at="2026-08-31T16:00:00.000001Z",
    phase=JobPhase.TIMELINE_READY,
)
real_atomic_write_json = job_repository_module.atomic_write_json

def delayed_publication(path, value, **kwargs):
    if Path(path).name == "job.json":
        Path(ready).write_text("validated", encoding="ascii")
        while not Path(release).exists():
            time.sleep(0.005)
    return real_atomic_write_json(path, value, **kwargs)

job_repository_module.atomic_write_json = delayed_publication
repository.replace_manifest(
    "job-claim",
    opened.manifest.content_fingerprint(),
    candidate,
    claim,
)
print("published", flush=True)
"""
    contender_worker = r"""
from datetime import datetime, timezone
from pathlib import Path
import sys

from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths

root, entered = sys.argv[1:]
paths = WorkspacePaths(Path(root))
clock = lambda: datetime(2026, 8, 31, 16, 0, 0, 10, tzinfo=timezone.utc)
repository = FileSystemJobRepository(paths, FileSystemDemoAssetRepository(paths), clock=clock)
Path(entered).write_text("attempting", encoding="ascii")
session = repository.acquire_write("job-claim", lease_us=10_000_000)
print(session.claim.run_id, flush=True)
"""
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            holder_worker,
            str(workspace.root),
            str(holder_ready),
            str(holder_release),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    children.append(holder)
    deadline = time.monotonic() + 15
    while not holder_ready.exists() and time.monotonic() < deadline:
        assert holder.poll() is None, holder.stderr.read()
        time.sleep(0.01)
    assert holder_ready.exists()

    contender = subprocess.Popen(
        [
            sys.executable,
            "-c",
            contender_worker,
            str(workspace.root),
            str(contender_entered),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    children.append(contender)
    deadline = time.monotonic() + 15
    while not contender_entered.exists() and time.monotonic() < deadline:
        assert contender.poll() is None, contender.stderr.read()
        time.sleep(0.01)
    assert contender_entered.exists()
    time.sleep(0.1)
    assert contender.poll() is None

    holder_release.write_text("release", encoding="ascii")
    holder_stdout, holder_stderr = holder.communicate(timeout=30)
    contender_stdout, contender_stderr = contender.communicate(timeout=30)
    assert holder.returncode == 0, holder_stderr
    assert contender.returncode == 0, contender_stderr
    assert holder_stdout.strip() == "published"
    assert contender_stdout.strip().startswith("run-")
    reader = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=lambda: NOW + timedelta(microseconds=10),
    )
    assert reader.load_job("job-claim").manifest.phase is JobPhase.TIMELINE_READY


def test_two_child_process_claim_contenders_have_exactly_one_owner(tmp_path):
    workspace, _, _, _, _ = _seed(tmp_path)
    barrier = tmp_path / "claim-go"
    worker = r"""
import json
import os
from pathlib import Path
import sys
import time
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths

root, barrier = sys.argv[1:]
while not Path(barrier).exists():
    time.sleep(0.005)
paths = WorkspacePaths(Path(root))
repository = FileSystemJobRepository(paths, FileSystemDemoAssetRepository(paths))
try:
    session = repository.acquire_write("job-claim", lease_us=30_000_000)
except JobRepositoryError as exc:
    print(json.dumps({"status": exc.code}), flush=True)
else:
    print(json.dumps({"status": "owner", "run_id": session.claim.run_id}), flush=True)
os._exit(0)
"""
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )
    command = [sys.executable, "-c", worker, str(workspace.root), str(barrier)]
    children = [
        subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        for _ in range(2)
    ]
    barrier.write_text("go", encoding="ascii")
    results = []
    for child in children:
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, stderr
        results.append(json.loads(stdout)["status"])

    assert sorted(results) == ["job_write_busy", "owner"]
