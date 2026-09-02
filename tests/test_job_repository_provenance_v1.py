from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from cs2pov.domain.invocation import (
    ModelCapability,
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.job import CreateJobRequest, JobDemoSource
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.timeline import (
    DemoDescriptor,
    DemoTimeline,
    MatchPhase,
    PlayerSnapshot,
    Round,
    RoundBoundaryConfidence,
    RoundCollection,
)
from cs2pov.domain.validation import validate_voice_activity_against_timeline
from cs2pov.domain.voice import VoiceActivityCue
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
RUN_ID = UUID("33333333-3333-4333-8333-333333333333")


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self) -> None:
        self.value += timedelta(microseconds=1)


def _seed(tmp_path: Path):
    workspace = WorkspacePaths(tmp_path / "workspace")
    source_file = tmp_path / "provenance.dem"
    source_file.write_bytes(b"provenance-demo")
    assets = FileSystemDemoAssetRepository(workspace, clock=lambda: NOW)
    asset = assets.import_source(source_file).asset
    source = JobDemoSource(
        asset.asset_id,
        f"library/demos/{asset.asset_id}/asset.json",
        asset.display_name,
    )
    FileSystemJobRepository(workspace, assets, clock=lambda: NOW).create_job(
        CreateJobRequest("job-provenance", "Provenance Job", source)
    )
    clock = MutableClock()
    repository = FileSystemJobRepository(
        workspace,
        assets,
        clock=clock,
        run_id_factory=lambda: RUN_ID,
        process_id_supplier=lambda: 5150,
    )
    claim = repository.acquire_write("job-provenance", lease_us=60_000_000).claim
    return workspace, assets, repository, clock, claim, asset.asset_id


def _timeline(asset_id: str) -> DemoTimeline:
    descriptor = DemoDescriptor(
        asset_id,
        "de_mirage",
        None,
        64,
        1,
        (
            PlayerSnapshot("player-alpha", "Alpha", 2),
            PlayerSnapshot("player-bravo", "Bravo", 3),
        ),
    )
    rounds = RoundCollection(
        (
            Round(
                "round-001",
                1,
                TimeRange(10_000_000, 20_000_000),
                640,
                1280,
                MatchPhase.REGULATION_FIRST_HALF,
                "fixture-parser-v1",
                RoundBoundaryConfidence.EXACT,
                0,
            ),
        )
    )
    anchors = (
        TimeAnchor(
            "anchor-demo",
            SourceClock.DEMO_TICK,
            "demo",
            640,
            1280,
            TimeRange(10_000_000, 20_000_000),
            0,
            "fixture-parser-v1",
        ),
        TimeAnchor(
            "anchor-alpha",
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-alpha",
            0,
            24_000,
            TimeRange(10_000_000, 11_000_000),
            16_000,
            "fixture-voice-v1",
        ),
        TimeAnchor(
            "anchor-bravo",
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-bravo",
            0,
            24_000,
            TimeRange(12_000_000, 13_000_000),
            16_000,
            "fixture-voice-v1",
        ),
    )
    return DemoTimeline(descriptor, rounds, anchors)


def _activities(asset_id: str) -> tuple[VoiceActivityCue, ...]:
    timeline = _timeline(asset_id)
    values = (
        VoiceActivityCue(
            "activity-bravo",
            "player-bravo",
            TimeRange(12_100_000, 12_900_000),
            7,
            ("anchor-bravo",),
            16_000,
        ),
        VoiceActivityCue(
            "activity-alpha",
            "player-alpha",
            TimeRange(10_100_000, 10_800_000),
            8,
            ("anchor-alpha",),
            16_000,
        ),
    )
    for value in values:
        validate_voice_activity_against_timeline(value, timeline)
    return values


def _configuration(
    snapshot_id: str = "asr-config-001",
    *,
    capability: ModelCapability = ModelCapability.ASR,
    model_name: str = "fixture-asr",
) -> ModelConfigurationSnapshot:
    return ModelConfigurationSnapshot(
        snapshot_id,
        capability,
        "local" if capability is ModelCapability.ASR else "openai-compatible",
        None if capability is ModelCapability.ASR else "provider-profile",
        model_name,
        None if capability is ModelCapability.ASR else "understanding-v1",
        {"language": "en"},
        (),
        "adapter-v1",
    )


def _invocation(invocation_id: str, snapshot_id: str, task_id: str):
    return ModelInvocationRecord.from_payloads(
        invocation_id,
        snapshot_id,
        task_id,
        {"request": invocation_id},
        {"response": invocation_id},
    )


def _snapshot_tree(root: Path):
    rows = []
    for path in sorted((root, *root.rglob("*")), key=lambda value: value.as_posix()):
        state = path.lstat()
        payload = path.read_bytes() if path.is_file() else None
        rows.append(
            (
                path.relative_to(root).as_posix(),
                state.st_mode,
                state.st_size,
                state.st_mtime_ns,
                payload,
            )
        )
    return tuple(rows)


def test_voice_activities_round_trip_in_canonical_order_and_reads_do_not_write(tmp_path):
    workspace, _, repository, _, claim, asset_id = _seed(tmp_path)
    values = _activities(asset_id)

    repository.save_voice_activities("job-provenance", values, claim)
    before = _snapshot_tree(workspace.jobs_dir / "job-provenance")
    reopened = repository.load_voice_activities("job-provenance")
    after = _snapshot_tree(workspace.jobs_dir / "job-provenance")

    assert reopened == tuple(
        sorted(
            values,
            key=lambda item: (
                item.time_range.start_us,
                item.time_range.end_us,
                item.activity_id,
            ),
        )
    )
    assert after == before


def test_voice_write_is_claim_fenced_and_validation_preserves_old_bytes(tmp_path):
    workspace, _, repository, _, claim, asset_id = _seed(tmp_path)
    repository.save_voice_activities(
        "job-provenance", _activities(asset_id), claim
    )
    path = workspace.jobs_dir / "job-provenance/voice/activities.jsonl"
    old_bytes = path.read_bytes()

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.save_voice_activities(
            "job-provenance",
            ("not-an-activity",),
            claim,
        )
    assert exc_info.value.code == "job_shard_invalid"
    assert path.read_bytes() == old_bytes

    fake = claim.__class__(
        claim.job_id,
        "run-not-owner",
        claim.process_id,
        claim.acquired_at,
        claim.heartbeat_at,
        claim.lease_expires_at,
    )
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.save_voice_activities(
            "job-provenance", _activities(asset_id), fake
        )
    assert exc_info.value.code == "job_write_interrupted"
    assert path.read_bytes() == old_bytes


def test_configuration_registration_updates_manifest_and_round_trips(tmp_path):
    workspace, _, repository, clock, claim, _ = _seed(tmp_path)
    opened = repository.load_job("job-provenance")
    snapshot = _configuration()
    clock.advance()

    registered = repository.register_model_configuration(
        "job-provenance",
        snapshot,
        opened.manifest.content_fingerprint(),
        claim,
    )

    expected_path = (
        workspace.jobs_dir
        / "job-provenance/models/snapshots/snapshot_asr-config-001.json"
    )
    assert expected_path.is_file()
    assert registered.manifest.configuration_snapshot_ids == (snapshot.snapshot_id,)
    before = _snapshot_tree(workspace.jobs_dir / "job-provenance")
    assert repository.load_model_configuration(
        "job-provenance", snapshot.snapshot_id
    ) == snapshot
    assert repository.load_model_configurations("job-provenance") == (snapshot,)
    assert _snapshot_tree(workspace.jobs_dir / "job-provenance") == before


def test_stale_configuration_cas_creates_no_snapshot(tmp_path):
    workspace, _, repository, clock, claim, _ = _seed(tmp_path)
    clock.advance()

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.register_model_configuration(
            "job-provenance", _configuration(), "0" * 64, claim
        )

    assert exc_info.value.code == "job_manifest_conflict"
    assert not any(
        (workspace.jobs_dir / "job-provenance/models/snapshots").iterdir()
    )


def test_configuration_is_immutable_idempotent_and_orphan_retry_closes_manifest(
    tmp_path, monkeypatch
):
    workspace, _, repository, clock, claim, _ = _seed(tmp_path)
    opened = repository.load_job("job-provenance")
    snapshot = _configuration()
    real_replace = repository._replace_manifest_locked

    def crash_after_snapshot(*_args, **_kwargs):
        raise RuntimeError("injected coordinator crash")

    monkeypatch.setattr(repository, "_replace_manifest_locked", crash_after_snapshot)
    clock.advance()
    with pytest.raises(RuntimeError, match="coordinator crash"):
        repository.register_model_configuration(
            "job-provenance",
            snapshot,
            opened.manifest.content_fingerprint(),
            claim,
        )
    snapshot_path = (
        workspace.jobs_dir
        / "job-provenance/models/snapshots/snapshot_asr-config-001.json"
    )
    orphan_bytes = snapshot_path.read_bytes()
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_model_configurations("job-provenance")
    assert exc_info.value.code == "job_shard_invalid"

    monkeypatch.setattr(repository, "_replace_manifest_locked", real_replace)
    clock.advance()
    registered = repository.register_model_configuration(
        "job-provenance",
        snapshot,
        opened.manifest.content_fingerprint(),
        claim,
    )
    assert registered.manifest.configuration_snapshot_ids == (snapshot.snapshot_id,)
    assert snapshot_path.read_bytes() == orphan_bytes

    same = repository.register_model_configuration(
        "job-provenance",
        snapshot,
        registered.manifest.content_fingerprint(),
        claim,
    )
    assert same.manifest == registered.manifest
    conflicting = _configuration(model_name="different-model")
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.register_model_configuration(
            "job-provenance",
            conflicting,
            registered.manifest.content_fingerprint(),
            claim,
        )
    assert exc_info.value.code == "job_shard_invalid"
    assert snapshot_path.read_bytes() == orphan_bytes


@pytest.mark.parametrize(
    "snapshot",
    [
        _configuration("Uppercase-ID"),
        _configuration("dot.id"),
    ],
)
def test_configuration_filename_rejects_non_path_ids(tmp_path, snapshot):
    workspace, _, repository, _, claim, _ = _seed(tmp_path)
    opened = repository.load_job("job-provenance")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.register_model_configuration(
            "job-provenance",
            snapshot,
            opened.manifest.content_fingerprint(),
            claim,
        )

    assert exc_info.value.code == "job_path_escape"
    assert not any(
        (workspace.jobs_dir / "job-provenance/models/snapshots").iterdir()
    )


def test_task_invocations_are_immutable_and_resolve_configuration(tmp_path):
    workspace, _, repository, clock, claim, _ = _seed(tmp_path)
    opened = repository.load_job("job-provenance")
    snapshot = _configuration()
    clock.advance()
    registered = repository.register_model_configuration(
        "job-provenance",
        snapshot,
        opened.manifest.content_fingerprint(),
        claim,
    )
    records = (
        _invocation("invoke-002", snapshot.snapshot_id, "asr-batch-001"),
        _invocation("invoke-001", snapshot.snapshot_id, "asr-batch-001"),
    )

    repository.save_task_invocations(
        "job-provenance", "asr-batch-001", records, claim
    )
    path = (
        workspace.jobs_dir
        / "job-provenance/models/invocations/task_asr-batch-001.jsonl"
    )
    original_bytes = path.read_bytes()
    expected = tuple(sorted(records, key=lambda item: item.invocation_id))
    before = _snapshot_tree(workspace.jobs_dir / "job-provenance")
    assert repository.load_task_invocations(
        "job-provenance", "asr-batch-001"
    ) == expected
    assert repository.load_all_invocations("job-provenance") == expected
    assert _snapshot_tree(workspace.jobs_dir / "job-provenance") == before

    repository.save_task_invocations(
        "job-provenance", "asr-batch-001", tuple(reversed(records)), claim
    )
    assert path.read_bytes() == original_bytes
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.save_task_invocations(
            "job-provenance",
            "asr-batch-001",
            (*records, _invocation("invoke-003", snapshot.snapshot_id, "asr-batch-001")),
            claim,
        )
    assert exc_info.value.code == "job_shard_invalid"
    assert path.read_bytes() == original_bytes
    assert registered.manifest.configuration_snapshot_ids == (snapshot.snapshot_id,)


def test_task_invocations_reject_filename_mismatch_and_dangling_configuration(tmp_path):
    workspace, _, repository, _, claim, _ = _seed(tmp_path)
    mismatch = _invocation("invoke-001", "missing-config", "different-task")
    dangling = _invocation("invoke-002", "missing-config", "task-001")

    for task_id, records in (
        ("task-001", (mismatch,)),
        ("task-001", (dangling,)),
        ("Uppercase-Task", (mismatch,)),
    ):
        with pytest.raises(JobRepositoryError) as exc_info:
            repository.save_task_invocations(
                "job-provenance", task_id, records, claim
            )
        assert exc_info.value.code in {"job_path_escape", "job_shard_invalid"}

    assert not any(
        (workspace.jobs_dir / "job-provenance/models/invocations").iterdir()
    )


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ('{"schema_version":2}\n', "job_schema_unsupported"),
        ('{"schema_version":true}\n', "job_shard_invalid"),
        (
            '{"schema_version":1,"invocation_id":"x",'
            '"invocation_id":"y"}\n',
            "job_shard_invalid",
        ),
    ],
)
def test_malformed_invocation_documents_map_stably(tmp_path, payload, expected_code):
    workspace, _, repository, _, _, _ = _seed(tmp_path)
    path = (
        workspace.jobs_dir
        / "job-provenance/models/invocations/task_task-001.jsonl"
    )
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_task_invocations("job-provenance", "task-001")

    assert exc_info.value.code == expected_code


def test_configuration_and_invocation_files_contain_no_private_machine_data(tmp_path):
    workspace, _, repository, clock, claim, _ = _seed(tmp_path)
    opened = repository.load_job("job-provenance")
    snapshot = _configuration()
    clock.advance()
    repository.register_model_configuration(
        "job-provenance",
        snapshot,
        opened.manifest.content_fingerprint(),
        claim,
    )
    repository.save_task_invocations(
        "job-provenance",
        "task-001",
        (_invocation("invoke-001", snapshot.snapshot_id, "task-001"),),
        claim,
    )

    values = []
    for path in (
        workspace.jobs_dir / "job-provenance/models"
    ).rglob("*.json*"):
        for line in path.read_text("utf-8").splitlines():
            values.append(json.loads(line))
    serialized = json.dumps(values).lower()
    assert str(workspace.root).lower() not in serialized
    username = os.environ.get("USERNAME")
    if username:
        assert username.lower() not in serialized
    assert "authorization" not in serialized
