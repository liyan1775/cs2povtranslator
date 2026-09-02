from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

from cs2pov.domain.job import (
    CreateJobRequest,
    FinalArtifactKind,
    JobDemoSource,
    JobPhase,
    JobRunStatus,
)
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths


def _seed(tmp_path: Path):
    workspace = WorkspacePaths(tmp_path / "workspace")
    source_file = tmp_path / "match.dem"
    source_file.write_bytes(b"catalog-demo")
    demo_assets = FileSystemDemoAssetRepository(
        workspace,
        clock=lambda: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    asset = demo_assets.import_source(source_file).asset
    source = JobDemoSource(
        asset.asset_id,
        f"library/demos/{asset.asset_id}/asset.json",
        asset.display_name,
    )
    return workspace, demo_assets, source


def _create(
    workspace: WorkspacePaths,
    demo_assets: FileSystemDemoAssetRepository,
    source: JobDemoSource,
    job_id: str,
    hour: int,
):
    repository = FileSystemJobRepository(
        workspace,
        demo_assets,
        clock=lambda: datetime(2026, 8, 31, hour, tzinfo=timezone.utc),
    )
    return repository.create_job(CreateJobRequest(job_id, f"Job {job_id}", source))


def _filesystem_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    if not root.exists():
        return ()
    rows: list[tuple[object, ...]] = []
    pending = [root]
    while pending:
        current = pending.pop()
        result = current.lstat()
        relative = current.relative_to(root).as_posix()
        if current.is_symlink():
            payload: object = ("link", os.readlink(current))
        elif current.is_file():
            payload = ("file", current.read_bytes())
        else:
            payload = ("dir",)
            pending.extend(sorted(current.iterdir(), key=lambda path: path.name, reverse=True))
        rows.append((relative, result.st_mode, result.st_size, result.st_mtime_ns, payload))
    return tuple(sorted(rows, key=lambda row: str(row[0])))


def _rewrite(path: Path, change) -> None:
    payload = json.loads(path.read_text("utf-8"))
    change(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_list_jobs_isolates_damaged_current_jobs_and_ignores_legacy_and_staging(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-old", 10)
    _create(workspace, demo_assets, source, "job-new", 11)
    _create(workspace, demo_assets, source, "job-invalid", 12)
    _create(workspace, demo_assets, source, "job-missing", 13)
    _create(workspace, demo_assets, source, "job-unsupported", 14)
    _create(workspace, demo_assets, source, "job-mismatch", 15)
    _create(workspace, demo_assets, source, "job-source-missing", 16)

    (workspace.jobs_dir / "job-invalid/job.json").write_bytes(b"{not-json")
    (workspace.jobs_dir / "job-missing/job.json").unlink()
    _rewrite(
        workspace.jobs_dir / "job-unsupported/job.json",
        lambda payload: payload.__setitem__("schema_version", 2),
    )
    _rewrite(
        workspace.jobs_dir / "job-mismatch/job.json",
        lambda payload: payload.__setitem__("job_id", "other-job"),
    )
    (workspace.jobs_dir / "job-source-missing/source/demo_ref.json").unlink()

    legacy = workspace.jobs_dir / "legacy-job"
    legacy.mkdir()
    (legacy / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")
    hidden = workspace.jobs_dir / ".job-hidden.deadbeef.staging"
    hidden.mkdir()
    (hidden / "repository.json").write_text("should not be read", encoding="utf-8")
    (workspace.jobs_dir / "unrelated.txt").write_text("ignore", encoding="utf-8")

    linked_expected = False
    outside = tmp_path / "linked-current-job"
    outside.mkdir()
    (outside / "repository.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository_kind": "cs2pov-current-job",
                "job_id": "job-linked",
            }
        ),
        encoding="utf-8",
    )
    try:
        (workspace.jobs_dir / "job-linked").symlink_to(outside, target_is_directory=True)
        linked_expected = True
    except OSError:
        pass

    before = _filesystem_snapshot(workspace.jobs_dir)
    entries = FileSystemJobRepository(workspace, demo_assets).list_jobs()
    after = _filesystem_snapshot(workspace.jobs_dir)

    by_id = {entry.discovery_id: entry for entry in entries}
    expected_ids = {
        "job-old",
        "job-new",
        "job-invalid",
        "job-missing",
        "job-unsupported",
        "job-mismatch",
        "job-source-missing",
    }
    if linked_expected:
        expected_ids.add("job-linked")
    assert set(by_id) == expected_ids
    assert "legacy-job" not in by_id
    assert ".job-hidden.deadbeef.staging" not in by_id
    assert "unrelated.txt" not in by_id

    healthy = [entry.discovery_id for entry in entries if entry.healthy]
    assert healthy == ["job-new", "job-old"]
    no_timestamp = [entry.discovery_id for entry in entries if entry.updated_at is None]
    assert no_timestamp == sorted(no_timestamp)
    assert by_id["job-new"].display_name == "Job job-new"
    assert by_id["job-new"].demo_asset_id == source.asset_id
    assert by_id["job-new"].demo_display_name == source.display_name
    assert by_id["job-new"].phase is JobPhase.CREATED
    assert by_id["job-new"].durable_run_status is JobRunStatus.PENDING
    assert by_id["job-new"].effective_run_status is JobRunStatus.PENDING
    assert by_id["job-new"].round_progress.total == 0
    assert by_id["job-new"].final_artifact_kinds == ()

    codes = {
        discovery_id: {issue.code for issue in entry.issues}
        for discovery_id, entry in by_id.items()
    }
    assert "job_manifest_invalid" in codes["job-invalid"]
    assert "job_manifest_invalid" in codes["job-missing"]
    assert "job_schema_unsupported" in codes["job-unsupported"]
    assert "job_manifest_invalid" in codes["job-mismatch"]
    assert "job_shard_missing" in codes["job-source-missing"]
    if linked_expected:
        assert codes["job-linked"] == {"job_path_escape"}

    workspace_text = str(workspace.root)
    for entry in entries:
        for issue in entry.issues:
            assert issue.message_zh
            assert issue.suggestion_zh
            assert workspace_text not in issue.message_zh
            assert workspace_text not in issue.suggestion_zh
    assert after == before


def test_list_jobs_isolates_marker_lstat_failure_from_healthy_sibling(tmp_path, monkeypatch):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-healthy", 10)
    _create(workspace, demo_assets, source, "job-io-failure", 11)
    import cs2pov.storage.job_repository as job_repository

    failing_marker = workspace.jobs_dir / "job-io-failure/repository.json"
    real_lstat = job_repository.os.lstat

    def injected_lstat(path, *args, **kwargs):
        if Path(path) == failing_marker:
            raise PermissionError("injected marker failure")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(job_repository.os, "lstat", injected_lstat)

    entries = FileSystemJobRepository(workspace, demo_assets).list_jobs()

    by_id = {entry.discovery_id: entry for entry in entries}
    assert by_id["job-healthy"].healthy
    assert not by_id["job-io-failure"].healthy
    assert {issue.code for issue in by_id["job-io-failure"].issues} == {
        "job_manifest_invalid"
    }


def test_list_jobs_keeps_candidate_visible_when_direntry_stat_fails(tmp_path, monkeypatch):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-healthy", 10)
    _create(workspace, demo_assets, source, "job-unreadable", 11)
    import cs2pov.storage.job_repository as job_repository

    real_scandir = job_repository.os.scandir
    root_entries = tuple(real_scandir(workspace.jobs_dir))

    class UnreadableEntry:
        def __init__(self, entry):
            self.name = entry.name
            self.path = entry.path

        def stat(self, *, follow_symlinks=True):
            raise PermissionError("injected candidate stat failure")

    def injected_scandir(path):
        if Path(path) == workspace.jobs_dir:
            return iter(
                UnreadableEntry(entry) if entry.name == "job-unreadable" else entry
                for entry in root_entries
            )
        return real_scandir(path)

    monkeypatch.setattr(job_repository.os, "scandir", injected_scandir)

    entries = FileSystemJobRepository(workspace, demo_assets).list_jobs()

    by_id = {entry.discovery_id: entry for entry in entries}
    assert by_id["job-healthy"].healthy
    assert not by_id["job-unreadable"].healthy
    assert {issue.code for issue in by_id["job-unreadable"].issues} == {
        "job_path_escape"
    }


def test_inspect_job_maps_directory_lstat_failure_to_nonthrowing_diagnostic(tmp_path, monkeypatch):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-io-failure", 10)
    import cs2pov.storage.job_repository as job_repository

    failing_directory = workspace.jobs_dir / "job-io-failure"
    real_lstat = job_repository.os.lstat

    def injected_lstat(path, *args, **kwargs):
        if Path(path) == failing_directory:
            raise PermissionError("injected directory failure")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(job_repository.os, "lstat", injected_lstat)

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job(
        "job-io-failure"
    )

    assert not inspection.entry.healthy
    assert {issue.code for issue in inspection.entry.issues} == {"job_path_escape"}
    assert inspection.marker is None
    assert inspection.manifest is None


def test_list_jobs_isolates_optional_shard_lstat_failure(tmp_path, monkeypatch):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-healthy", 10)
    _create(workspace, demo_assets, source, "job-shard-io", 11)
    import cs2pov.storage.job_repository as job_repository

    failing_shard = workspace.jobs_dir / "job-shard-io/timeline/demo.json"
    real_lstat = job_repository.os.lstat

    def injected_lstat(path, *args, **kwargs):
        if Path(path) == failing_shard:
            raise PermissionError("injected optional shard failure")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(job_repository.os, "lstat", injected_lstat)

    entries = FileSystemJobRepository(workspace, demo_assets).list_jobs()

    by_id = {entry.discovery_id: entry for entry in entries}
    assert by_id["job-healthy"].healthy
    assert not by_id["job-shard-io"].healthy
    issue = by_id["job-shard-io"].issues[0]
    assert issue.code == "job_path_escape"
    assert issue.logical_path == "timeline/demo.json"


def test_list_jobs_exposes_distinct_final_artifact_kinds_from_valid_manifest(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-artifacts", 10)
    manifest = workspace.jobs_dir / "job-artifacts/job.json"
    subtitle = b"subtitle"
    green = b"green"
    (workspace.jobs_dir / "job-artifacts/final/subtitles/a.ass").write_bytes(subtitle)
    (workspace.jobs_dir / "job-artifacts/final/subtitles/b.srt").write_bytes(subtitle)
    (workspace.jobs_dir / "job-artifacts/final/green_screen/a.mov").write_bytes(green)

    def add_artifacts(payload):
        payload["final_artifacts"] = [
            {
                "artifact_id": "subtitle-a",
                "kind": "subtitle",
                "relative_path": "final/subtitles/a.ass",
                "content_sha256": hashlib.sha256(subtitle).hexdigest(),
                "round_id": None,
                "timebase": "demo_global",
            },
            {
                "artifact_id": "subtitle-b",
                "kind": "subtitle",
                "relative_path": "final/subtitles/b.srt",
                "content_sha256": hashlib.sha256(subtitle).hexdigest(),
                "round_id": None,
                "timebase": "demo_global",
            },
            {
                "artifact_id": "green-a",
                "kind": "green_screen",
                "relative_path": "final/green_screen/a.mov",
                "content_sha256": hashlib.sha256(green).hexdigest(),
                "round_id": None,
                "timebase": "demo_global",
            },
        ]

    _rewrite(manifest, add_artifacts)

    entry = FileSystemJobRepository(workspace, demo_assets).list_jobs()[0]

    assert entry.final_artifact_kinds == (
        FinalArtifactKind.SUBTITLE,
        FinalArtifactKind.GREEN_SCREEN,
    )
    assert entry.healthy


def test_list_jobs_preserves_microsecond_order_without_float_timestamp_rounding(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-a", 10)
    _create(workspace, demo_assets, source, "job-z", 11)

    def set_time(value):
        def change(payload):
            payload["created_at"] = value
            payload["updated_at"] = value

        return change

    _rewrite(
        workspace.jobs_dir / "job-a/job.json",
        set_time("9999-01-01T00:00:00.000000Z"),
    )
    _rewrite(
        workspace.jobs_dir / "job-z/job.json",
        set_time("9999-01-01T00:00:00.000001Z"),
    )

    entries = FileSystemJobRepository(workspace, demo_assets).list_jobs()

    assert [entry.discovery_id for entry in entries] == ["job-z", "job-a"]


def test_inspect_job_reports_unavailable_demo_but_keeps_valid_artifact_metadata(tmp_path, monkeypatch):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-inspect", 10)
    job_dir = workspace.jobs_dir / "job-inspect"
    artifact = job_dir / "final/subtitles/final.ass"
    artifact.write_bytes(b"valid-subtitle")
    _rewrite(
        job_dir / "job.json",
        lambda payload: payload.__setitem__(
            "final_artifacts",
            [
                {
                    "artifact_id": "final-subtitle",
                    "kind": "subtitle",
                    "relative_path": "final/subtitles/final.ass",
                    "content_sha256": hashlib.sha256(b"valid-subtitle").hexdigest(),
                    "round_id": None,
                    "timebase": "demo_global",
                }
            ],
        ),
    )
    (job_dir / "future-extra.txt").write_text("ignored", encoding="utf-8")
    (workspace.demo_library_dir / source.asset_id / "source.dem").unlink()

    def forbidden_resolve(_ref):
        raise AssertionError("inspect_job must never call resolve_asset")

    monkeypatch.setattr(demo_assets, "resolve_asset", forbidden_resolve)
    before = _filesystem_snapshot(workspace.root)

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job("job-inspect")

    assert inspection.marker.job_id == "job-inspect"
    assert inspection.manifest.job_id == "job-inspect"
    assert inspection.source == source
    assert inspection.events == ()
    assert not inspection.event_tail_incomplete
    assert inspection.entry.final_artifact_kinds == (FinalArtifactKind.SUBTITLE,)
    assert {issue.code for issue in inspection.entry.issues} == {"job_source_unavailable"}
    assert not inspection.entry.healthy
    assert _filesystem_snapshot(workspace.root) == before

    with pytest.raises(JobRepositoryError) as exc_info:
        FileSystemJobRepository(workspace, demo_assets).load_job("job-inspect")
    assert exc_info.value.code == "job_source_unavailable"


def test_inspect_job_ignores_unknown_extra_file_and_directory_without_mutation(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-forward-safe", 10)
    job_dir = workspace.jobs_dir / "job-forward-safe"
    (job_dir / "future-feature").mkdir()
    (job_dir / "future-feature/payload.bin").write_bytes(b"unknown")
    (job_dir / "timeline/future-format.data").write_bytes(b"unknown")
    before = _filesystem_snapshot(job_dir)

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job(
        "job-forward-safe"
    )

    assert inspection.entry.healthy
    assert inspection.entry.issues == ()
    assert _filesystem_snapshot(job_dir) == before


def test_inspect_job_captures_missing_source_and_bad_artifact_without_hiding_manifest(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-damaged", 10)
    job_dir = workspace.jobs_dir / "job-damaged"
    (job_dir / "source/demo_ref.json").unlink()
    artifact = job_dir / "final/subtitles/final.ass"
    artifact.write_bytes(b"changed")
    _rewrite(
        job_dir / "job.json",
        lambda payload: payload.__setitem__(
            "final_artifacts",
            [
                {
                    "artifact_id": "final-subtitle",
                    "kind": "subtitle",
                    "relative_path": "final/subtitles/final.ass",
                    "content_sha256": hashlib.sha256(b"expected").hexdigest(),
                    "round_id": None,
                    "timebase": "demo_global",
                }
            ],
        ),
    )

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job("job-damaged")

    assert inspection.manifest is not None
    assert inspection.source is None
    assert {issue.code for issue in inspection.entry.issues} == {
        "job_shard_missing",
        "job_shard_invalid",
    }
    artifact_issue = next(
        issue for issue in inspection.entry.issues if issue.code == "job_shard_invalid"
    )
    assert artifact_issue.logical_path == "final/subtitles/final.ass"


def test_inspect_job_rejects_linked_final_artifact_without_following_it(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-linked-artifact", 10)
    job_dir = workspace.jobs_dir / "job-linked-artifact"
    outside = tmp_path / "outside.ass"
    outside.write_bytes(b"outside")
    artifact = job_dir / "final/subtitles/final.ass"
    try:
        artifact.symlink_to(outside)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    _rewrite(
        job_dir / "job.json",
        lambda payload: payload.__setitem__(
            "final_artifacts",
            [
                {
                    "artifact_id": "linked-subtitle",
                    "kind": "subtitle",
                    "relative_path": "final/subtitles/final.ass",
                    "content_sha256": hashlib.sha256(b"outside").hexdigest(),
                    "round_id": None,
                    "timebase": "demo_global",
                }
            ],
        ),
    )

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job(
        "job-linked-artifact"
    )

    assert "job_path_escape" in {issue.code for issue in inspection.entry.issues}
    assert outside.read_bytes() == b"outside"


def test_inspect_job_rejects_linked_optional_stage_shard_without_parsing_it(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-linked-shard", 10)
    job_dir = workspace.jobs_dir / "job-linked-shard"
    outside = tmp_path / "outside-timeline.json"
    outside.write_text("not even valid json", encoding="utf-8")
    shard = job_dir / "timeline/demo.json"
    try:
        shard.symlink_to(outside)
    except OSError:
        pytest.skip("symlink privileges unavailable")

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job(
        "job-linked-shard"
    )

    issue = next(issue for issue in inspection.entry.issues if issue.logical_path == "timeline/demo.json")
    assert issue.code == "job_path_escape"
    assert outside.read_text("utf-8") == "not even valid json"


def test_inspect_job_rejects_optional_stage_shard_that_is_not_regular(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-directory-shard", 10)
    shard = workspace.jobs_dir / "job-directory-shard/timeline/demo.json"
    shard.mkdir()

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job(
        "job-directory-shard"
    )

    issue = next(issue for issue in inspection.entry.issues if issue.logical_path == "timeline/demo.json")
    assert issue.code == "job_shard_invalid"


def test_inspect_job_is_nonthrowing_for_manifest_identity_disagreement(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-identity", 10)
    _rewrite(
        workspace.jobs_dir / "job-identity/job.json",
        lambda payload: payload.__setitem__("job_id", "different-job"),
    )

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job("job-identity")

    assert inspection.manifest.job_id == "different-job"
    assert not inspection.entry.healthy
    assert "job_manifest_invalid" in {issue.code for issue in inspection.entry.issues}


def test_inspect_job_does_not_repair_missing_initial_lock_or_journal(tmp_path):
    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-no-events", 10)
    job_dir = workspace.jobs_dir / "job-no-events"
    (job_dir / "events/.write.lock").unlink()
    (job_dir / "events/job_events.jsonl").unlink()
    before = _filesystem_snapshot(job_dir)

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job("job-no-events")

    assert "job_shard_missing" in {issue.code for issue in inspection.entry.issues}
    assert _filesystem_snapshot(job_dir) == before


def test_inspect_job_never_opens_files_below_linked_events_directory(
    tmp_path, monkeypatch
):
    import subprocess
    import cs2pov.storage.job_repository as repository_module

    workspace, demo_assets, source = _seed(tmp_path)
    _create(workspace, demo_assets, source, "job-linked-events", 10)
    job_dir = workspace.jobs_dir / "job-linked-events"
    events = job_dir / "events"
    events.rename(job_dir / "events-original")
    outside = tmp_path / "outside-events"
    outside.mkdir()
    (outside / ".write.lock").write_bytes(b"0")
    (outside / "job_events.jsonl").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_id": "outside-event",
                "job_id": "job-linked-events",
                "run_id": "run-outside",
                "occurred_at": "2026-08-31T10:00:00.000000Z",
                "event_type": "outside",
                "payload": {"sentinel": "must-not-be-read"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(events), str(outside)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(
                f"mklink /J unavailable: {result.stderr or result.stdout}"
            )
    else:
        events.symlink_to(outside, target_is_directory=True)

    real_open = repository_module.os.open
    opened_outside = False

    def reject_linked_events_open(path, *args, **kwargs):
        nonlocal opened_outside
        candidate = Path(path)
        try:
            candidate.relative_to(events)
        except ValueError:
            pass
        else:
            opened_outside = True
            raise AssertionError("linked events subtree must never be opened")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(repository_module.os, "open", reject_linked_events_open)

    inspection = FileSystemJobRepository(workspace, demo_assets).inspect_job(
        "job-linked-events"
    )

    assert "job_path_escape" in {
        issue.code for issue in inspection.entry.issues
    }
    assert not opened_outside
    assert inspection.events == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_list_jobs_reports_junction_candidate_without_following_it(tmp_path):
    workspace, demo_assets, _ = _seed(tmp_path)
    workspace.jobs_dir.mkdir(parents=True)
    outside = tmp_path / "outside-catalog-junction"
    outside.mkdir()
    (outside / "repository.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository_kind": "cs2pov-current-job",
                "job_id": "job-junction",
            }
        ),
        encoding="utf-8",
    )
    junction = workspace.jobs_dir / "job-junction"
    import subprocess

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"mklink /J unavailable: {result.stderr or result.stdout}")

    entries = FileSystemJobRepository(workspace, demo_assets).list_jobs()

    assert len(entries) == 1
    assert entries[0].discovery_id == "job-junction"
    assert {issue.code for issue in entries[0].issues} == {"job_path_escape"}
