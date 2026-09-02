from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job import (
    CreateJobRequest,
    JobDemoSource,
    JobPhase,
    JobRunStatus,
)
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository, OpenedJob
from cs2pov.workspace.paths import WorkspacePaths


NOW = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)
STAGING_ID = UUID("12345678-1234-5678-1234-567812345678")


def _make_repository(tmp_path: Path):
    workspace = WorkspacePaths(tmp_path / "workspace")
    demo_file = tmp_path / "match.dem"
    demo_file.write_bytes(b"current-v1-demo")
    demo_assets = FileSystemDemoAssetRepository(workspace, clock=lambda: NOW)
    imported = demo_assets.import_source(demo_file).asset
    source = JobDemoSource(
        imported.asset_id,
        f"library/demos/{imported.asset_id}/asset.json",
        imported.display_name,
    )
    repository = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=lambda: NOW,
        staging_id_factory=lambda: STAGING_ID,
    )
    return workspace, demo_assets, repository, CreateJobRequest("job-001", "双语字幕", source)


def _tree(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix() + ("/" if path.is_dir() else "")
            for path in root.rglob("*")
        )
    )


def _snapshot(root: Path) -> tuple[tuple[str, str, int, int], ...]:
    if not root.exists():
        return ()
    rows = []
    for path in sorted((root, *root.rglob("*")), key=lambda item: item.as_posix()):
        stat_result = path.lstat()
        payload = "<dir>" if path.is_dir() else path.read_bytes().hex()
        rows.append(
            (
                path.relative_to(root).as_posix(),
                payload,
                stat_result.st_size,
                stat_result.st_mtime_ns,
            )
        )
    return tuple(rows)


def test_create_job_publishes_exact_initial_layout_and_pending_manifest(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)

    opened = repository.create_job(request)

    assert isinstance(opened, OpenedJob)
    assert opened.marker.job_id == "job-001"
    assert opened.source == request.source
    assert opened.manifest.phase is JobPhase.CREATED
    assert opened.manifest.run_status is JobRunStatus.PENDING
    assert opened.manifest.round_progress.to_dict() == {
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "review_pending": 0,
    }
    assert opened.manifest.configuration_snapshot_ids == ()
    assert opened.manifest.active_review_id is None
    assert opened.manifest.final_artifacts == ()
    assert opened.manifest.created_at == "2026-08-31T16:00:00.000000Z"
    assert opened.manifest.updated_at == opened.manifest.created_at
    assert opened.effective_run_status is JobRunStatus.PENDING

    job_dir = workspace.jobs_dir / "job-001"
    assert _tree(job_dir) == (
        "events/",
        "events/.write.lock",
        "events/job_events.jsonl",
        "final/",
        "final/green_screen/",
        "final/subtitles/",
        "final/timelines/",
        "final/video/",
        "job.json",
        "models/",
        "models/invocations/",
        "models/snapshots/",
        "repository.json",
        "review/",
        "review/revisions/",
        "source/",
        "source/demo_ref.json",
        "tasks/",
        "timeline/",
        "transcript/",
        "understanding/",
        "voice/",
    )
    assert (job_dir / "events/.write.lock").read_bytes() == b"0"
    assert (job_dir / "events/job_events.jsonl").read_bytes() == b""
    assert not (job_dir / "events/.writer_claim").exists()
    assert json.loads((job_dir / "repository.json").read_text("utf-8")) == {
        "schema_version": 1,
        "repository_kind": "cs2pov-current-job",
        "job_id": "job-001",
    }


def test_create_job_inspects_persistent_source_without_resolving_it(tmp_path, monkeypatch):
    _, demo_assets, repository, request = _make_repository(tmp_path)
    calls = []
    real_inspect = demo_assets.inspect_asset

    def inspect(asset_id):
        calls.append(("inspect", asset_id))
        return real_inspect(asset_id)

    def forbidden_resolve(_ref):
        raise AssertionError("create_job must not call resolve_asset")

    monkeypatch.setattr(demo_assets, "inspect_asset", inspect)
    monkeypatch.setattr(demo_assets, "resolve_asset", forbidden_resolve)

    repository.create_job(request)

    assert calls
    assert set(calls) == {("inspect", request.source.asset_id)}


def test_create_job_rejects_unavailable_source_before_staging(tmp_path, monkeypatch):
    workspace, demo_assets, repository, request = _make_repository(tmp_path)
    real_inspection = demo_assets.inspect_asset(request.source.asset_id)
    unavailable = type(real_inspection)(
        real_inspection.asset,
        False,
        real_inspection.cache_status,
        ("demo_asset_integrity_failed",),
    )
    monkeypatch.setattr(demo_assets, "inspect_asset", lambda _asset_id: unavailable)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.create_job(request)

    assert exc_info.value.code == "job_source_unavailable"
    assert not workspace.jobs_dir.exists() or not any(
        child.name.startswith(".") and child.name.endswith(".staging")
        for child in workspace.jobs_dir.iterdir()
    )


def test_create_job_keeps_final_directory_hidden_until_all_documents_validate(tmp_path, monkeypatch):
    workspace, _, repository, request = _make_repository(tmp_path)
    import cs2pov.storage.job_repository as job_repository

    real_write = job_repository.atomic_write_json
    seen = []

    def guarded_write(*args, **kwargs):
        seen.append(kwargs["logical_path"])
        assert not (workspace.jobs_dir / request.job_id).exists()
        result = real_write(*args, **kwargs)
        assert not (workspace.jobs_dir / request.job_id).exists()
        return result

    monkeypatch.setattr(job_repository, "atomic_write_json", guarded_write)

    repository.create_job(request)

    assert seen == ["repository.json", "source/demo_ref.json", "job.json"]


def test_create_job_never_overwrites_existing_corrupt_or_empty_target(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)
    target = workspace.jobs_dir / request.job_id
    target.mkdir(parents=True)
    marker = target / "do-not-touch.bin"
    marker.write_bytes(b"existing")
    before = _snapshot(target)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.create_job(request)

    assert exc_info.value.code == "job_already_exists"
    assert _snapshot(target) == before
    assert not any(child.name.endswith(".staging") for child in workspace.jobs_dir.iterdir())


def test_create_job_preserves_preexisting_empty_target_metadata(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)
    target = workspace.jobs_dir / request.job_id
    target.mkdir(parents=True)
    before = _snapshot(target)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.create_job(request)

    assert exc_info.value.code == "job_already_exists"
    assert _snapshot(target) == before


def test_create_job_cleans_only_its_staging_when_initial_write_fails(tmp_path, monkeypatch):
    workspace, _, repository, request = _make_repository(tmp_path)
    workspace.jobs_dir.mkdir(parents=True)
    unrelated = workspace.jobs_dir / ".unrelated.staging"
    unrelated.mkdir()
    (unrelated / "keep").write_bytes(b"keep")
    import cs2pov.storage.job_repository as job_repository

    def fail(*_args, **_kwargs):
        raise JobRepositoryError("job_write_failed", "写入失败。", "请重试。", "job.json")

    monkeypatch.setattr(job_repository, "atomic_write_json", fail)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.create_job(request)

    assert exc_info.value.code == "job_write_failed"
    assert (unrelated / "keep").read_bytes() == b"keep"
    assert not (workspace.jobs_dir / request.job_id).exists()
    assert sorted(child.name for child in workspace.jobs_dir.iterdir()) == [".unrelated.staging"]


def test_created_documents_do_not_contain_workspace_absolute_path(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)

    repository.create_job(request)

    forbidden = str(workspace.root).encode("utf-8")
    for path in (workspace.jobs_dir / request.job_id).rglob("*"):
        if path.is_file():
            assert forbidden not in path.read_bytes()


def test_create_job_rename_failure_removes_staging_and_keeps_target_absent(tmp_path, monkeypatch):
    workspace, _, repository, request = _make_repository(tmp_path)
    import cs2pov.storage.job_repository as job_repository

    def fail_rename(_source, _target):
        raise PermissionError(errno.EACCES, "denied")

    import errno

    monkeypatch.setattr(job_repository.os, "rename", fail_rename)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.create_job(request)

    assert exc_info.value.code == "job_write_failed"
    assert not (workspace.jobs_dir / request.job_id).exists()
    assert not any(path.name.endswith(".staging") for path in workspace.jobs_dir.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX parent directory fsync contract")
def test_create_job_parent_fsync_failure_keeps_published_valid_job(tmp_path, monkeypatch):
    workspace, _, repository, request = _make_repository(tmp_path)
    import cs2pov.storage.job_repository as job_repository

    def fail_fsync(_path):
        raise JobRepositoryError(
            "job_write_durability_uncertain",
            "持久化不确定。",
            "请检查。",
        )

    monkeypatch.setattr(job_repository, "_fsync_jobs_directory", fail_fsync)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.create_job(request)

    assert exc_info.value.code == "job_write_durability_uncertain"
    assert (workspace.jobs_dir / request.job_id).is_dir()
    assert repository.load_job(request.job_id).manifest.job_id == request.job_id
    assert not any(path.name.endswith(".staging") for path in workspace.jobs_dir.iterdir())


def test_two_child_process_creators_have_one_winner_and_one_stable_collision(tmp_path):
    workspace, _, _, request = _make_repository(tmp_path)
    barrier = tmp_path / "go"
    worker = r"""
import json
from pathlib import Path
import sys
import time
from cs2pov.domain.job import CreateJobRequest, JobDemoSource
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths

root, asset_id, display_name, barrier = sys.argv[1:]
while not Path(barrier).exists():
    time.sleep(0.005)
paths = WorkspacePaths(Path(root))
source = JobDemoSource(asset_id, f"library/demos/{asset_id}/asset.json", display_name)
repository = FileSystemJobRepository(paths, FileSystemDemoAssetRepository(paths))
try:
    repository.create_job(CreateJobRequest("job-001", "concurrent", source))
except JobRepositoryError as exc:
    print(json.dumps({"status": exc.code}))
else:
    print(json.dumps({"status": "created"}))
"""
    command = [
        sys.executable,
        "-c",
        worker,
        str(workspace.root),
        request.source.asset_id,
        request.source.display_name,
        str(barrier),
    ]
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )
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

    assert sorted(results) == ["created", "job_already_exists"]
    assert FileSystemJobRepository(
        workspace, FileSystemDemoAssetRepository(workspace)
    ).load_job("job-001").manifest.display_name == "concurrent"
    assert not any(path.name.endswith(".staging") for path in workspace.jobs_dir.iterdir())


def test_load_job_returns_frozen_current_version_value_without_writing(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)
    repository.create_job(request)
    job_dir = workspace.jobs_dir / request.job_id
    before = _snapshot(job_dir)

    reopened = FileSystemJobRepository(
        workspace,
        FileSystemDemoAssetRepository(workspace),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    ).load_job(request.job_id)

    assert reopened.manifest == repository.load_job(request.job_id).manifest
    assert reopened.source == request.source
    assert reopened.paths.job_dir == job_dir
    assert _snapshot(job_dir) == before
    with pytest.raises(FrozenInstanceError):
        reopened.manifest = None


def test_two_repository_instances_open_same_job_without_any_filesystem_change(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)
    repository.create_job(request)
    before = _snapshot(workspace.jobs_dir)
    first = FileSystemJobRepository(workspace, FileSystemDemoAssetRepository(workspace))
    second = FileSystemJobRepository(workspace, FileSystemDemoAssetRepository(workspace))

    assert first.load_job(request.job_id).manifest == second.load_job(request.job_id).manifest

    assert _snapshot(workspace.jobs_dir) == before


@pytest.mark.parametrize("document", ["repository.json", "job.json", "source/demo_ref.json"])
def test_load_job_maps_exact_noncurrent_schema_to_unsupported_with_domain_cause(tmp_path, document):
    workspace, _, repository, request = _make_repository(tmp_path)
    repository.create_job(request)
    path = workspace.jobs_dir / request.job_id / document
    payload = json.loads(path.read_text("utf-8"))
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job(request.job_id)

    assert exc_info.value.code == "job_schema_unsupported"
    assert isinstance(exc_info.value.__cause__, DomainSchemaError)


@pytest.mark.parametrize("schema_value", [True, "1", None])
def test_load_job_maps_malformed_manifest_schema_to_manifest_invalid(tmp_path, schema_value):
    workspace, _, repository, request = _make_repository(tmp_path)
    repository.create_job(request)
    manifest = workspace.jobs_dir / request.job_id / "job.json"
    payload = json.loads(manifest.read_text("utf-8"))
    payload["schema_version"] = schema_value
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job(request.job_id)

    assert exc_info.value.code == "job_manifest_invalid"


@pytest.mark.parametrize(
    "relative_path,expected_code",
    [("job.json", "job_manifest_invalid"), ("source/demo_ref.json", "job_shard_missing")],
)
def test_load_job_maps_missing_required_documents_precisely(tmp_path, relative_path, expected_code):
    workspace, _, repository, request = _make_repository(tmp_path)
    repository.create_job(request)
    (workspace.jobs_dir / request.job_id / relative_path).unlink()

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job(request.job_id)

    assert exc_info.value.code == expected_code


def test_load_job_rejects_marker_manifest_source_identity_mismatch(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)
    repository.create_job(request)
    source_path = workspace.jobs_dir / request.job_id / "source/demo_ref.json"
    payload = json.loads(source_path.read_text("utf-8"))
    payload["display_name"] = "other.dem"
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job(request.job_id)

    assert exc_info.value.code == "job_shard_invalid"


@pytest.mark.parametrize(
    "document,field,value,expected_code",
    [
        ("repository.json", "job_id", "job-002", "job_manifest_invalid"),
        ("job.json", "job_id", "job-002", "job_manifest_invalid"),
        ("job.json", "demo_display_name", "other.dem", "job_shard_invalid"),
    ],
)
def test_load_job_validates_directory_marker_manifest_and_source_identity(
    tmp_path, document, field, value, expected_code
):
    workspace, _, repository, request = _make_repository(tmp_path)
    repository.create_job(request)
    path = workspace.jobs_dir / request.job_id / document
    payload = json.loads(path.read_text("utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job(request.job_id)

    assert exc_info.value.code == expected_code


def test_load_job_never_falls_back_to_legacy_manifest(tmp_path):
    workspace, _, repository, request = _make_repository(tmp_path)
    legacy = workspace.jobs_dir / request.job_id
    legacy.mkdir(parents=True)
    (legacy / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job(request.job_id)

    assert exc_info.value.code == "job_manifest_invalid"


def test_create_and_load_reject_linked_jobs_root_before_external_write(tmp_path):
    workspace, demo_assets, _, request = _make_repository(tmp_path)
    outside = tmp_path / "outside-jobs"
    outside.mkdir()
    try:
        workspace.jobs_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    repository = FileSystemJobRepository(workspace, demo_assets, clock=lambda: NOW)

    with pytest.raises(JobRepositoryError) as create_error:
        repository.create_job(request)
    with pytest.raises(JobRepositoryError) as load_error:
        repository.load_job(request.job_id)

    assert create_error.value.code == "job_path_escape"
    assert load_error.value.code == "job_path_escape"
    assert not any(outside.iterdir())


def test_create_and_load_reject_linked_job_candidate_before_external_write(tmp_path):
    workspace, demo_assets, _, request = _make_repository(tmp_path)
    workspace.jobs_dir.mkdir(parents=True)
    outside = tmp_path / "outside-job"
    outside.mkdir()
    (outside / "keep").write_bytes(b"keep")
    try:
        (workspace.jobs_dir / request.job_id).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    repository = FileSystemJobRepository(workspace, demo_assets, clock=lambda: NOW)

    with pytest.raises(JobRepositoryError) as create_error:
        repository.create_job(request)
    with pytest.raises(JobRepositoryError) as load_error:
        repository.load_job(request.job_id)

    assert create_error.value.code == "job_path_escape"
    assert load_error.value.code == "job_path_escape"
    assert (outside / "keep").read_bytes() == b"keep"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_create_rejects_windows_junction_jobs_root(tmp_path):
    workspace, demo_assets, _, request = _make_repository(tmp_path)
    outside = tmp_path / "outside-junction"
    outside.mkdir()
    result = os.system(f'cmd /c mklink /J "{workspace.jobs_dir}" "{outside}" >NUL')
    if result != 0:
        pytest.skip("mklink /J unavailable")
    repository = FileSystemJobRepository(workspace, demo_assets, clock=lambda: NOW)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.create_job(request)

    assert exc_info.value.code == "job_path_escape"
    assert not any(outside.iterdir())
