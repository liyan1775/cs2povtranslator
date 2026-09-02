import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job import (
    CreateJobRequest,
    FinalArtifactEntry,
    FinalArtifactKind,
    FinalArtifactTimebase,
    JobEvent,
    JobManifest,
    JobPhase,
    JobRepositoryMarker,
    JobRunStatus,
    JobWriteClaim,
    RoundProgressSummary,
    JobDemoSource,
)


HASH = "a" * 64


def source():
    return JobDemoSource(HASH, f"library/demos/{HASH}/asset.json", "match.dem")


def valid_manifest():
    return JobManifest(
        "job-001",
        "name",
        "2026-08-31T16:00:00.000000Z",
        "2026-08-31T16:00:00.000000Z",
        HASH,
        "match.dem",
        None,
        None,
        JobPhase.CREATED,
        JobRunStatus.PENDING,
        RoundProgressSummary(0, 0, 0, 0),
        (),
        None,
        (),
    )


def test_job_manifest_round_trips_and_fingerprint_is_order_independent():
    manifest = JobManifest(
        job_id="job-001",
        display_name="Mirage POV 双语字幕",
        created_at="2026-08-31T16:00:00.000000Z",
        updated_at="2026-08-31T16:00:00.000000Z",
        demo_asset_id=HASH,
        demo_display_name="match.dem",
        map_name=None,
        target_player_id=None,
        phase=JobPhase.CREATED,
        run_status=JobRunStatus.PENDING,
        round_progress=RoundProgressSummary(0, 0, 0, 0),
        configuration_snapshot_ids=(),
        active_review_id=None,
        final_artifacts=(),
    )
    assert JobManifest.from_dict(manifest.to_dict()) == manifest
    assert manifest.content_fingerprint() == JobManifest.from_dict(
        dict(reversed(list(manifest.to_dict().items())))
    ).content_fingerprint()


def test_manifest_rejects_non_current_schema_and_bool_integer():
    data = JobManifest(
        "job-001", "name", "2026-08-31T16:00:00.000000Z",
        "2026-08-31T16:00:00.000000Z", HASH, "match.dem", None, None,
        JobPhase.CREATED, JobRunStatus.PENDING, RoundProgressSummary(0, 0, 0, 0),
        (), None, (),
    ).to_dict()
    data["schema_version"] = True
    with pytest.raises(DomainSchemaError):
        JobManifest.from_dict(data)


def test_create_request_and_event_freeze_payload_and_reject_private_data():
    request = CreateJobRequest("job-001", "name", source())
    assert request.job_id == "job-001"
    event = JobEvent("event-1", "job-001", "run-1", "2026-08-31T16:00:00.000000Z", "job_created", {"nested": {"value": 1}})
    payload = event.to_dict()["payload"]
    payload["nested"]["value"] = 2
    assert event.to_dict()["payload"]["nested"]["value"] == 1
    with pytest.raises(DomainSchemaError):
        JobEvent("event-1", "job-001", "run-1", "2026-08-31T16:00:00.000000Z", "x", {"api_key": "secret"})


def test_claim_and_marker_have_exact_versioned_shapes():
    claim = JobWriteClaim("job-001", "run-1", 5, "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:30.000000Z")
    assert JobWriteClaim.from_dict(claim.to_dict()) == claim
    marker = JobRepositoryMarker("job-001")
    assert JobRepositoryMarker.from_dict(marker.to_dict()) == marker


def test_artifact_path_must_match_kind_subtree():
    with pytest.raises(DomainSchemaError):
        FinalArtifactEntry("artifact-1", FinalArtifactKind.SUBTITLE, "final/video/out.mp4", HASH, None, FinalArtifactTimebase.DEMO_GLOBAL)


def test_catalog_and_inspection_normalize_tuples_and_validate_projection():
    from cs2pov.domain.job import JobCatalogEntry, JobInspection, JobIssue
    issue = JobIssue("job_manifest_invalid", "error", "清单无效", "修复", "job.json")
    entry = JobCatalogEntry("job-1", "job-1", "name", "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:00.000000Z", HASH, "match.dem", "de_nuke", "target", JobPhase.CREATED, JobRunStatus.PENDING, JobRunStatus.PENDING, RoundProgressSummary(0, 0, 0, 0), [FinalArtifactKind.SUBTITLE], False, [issue])
    assert isinstance(entry.final_artifact_kinds, tuple)
    assert isinstance(entry.issues, tuple)
    inspection = JobInspection(entry, None, None, None, [], False)
    assert inspection.events == ()


def test_catalog_validates_optional_metadata_and_health_issue_consistency():
    from cs2pov.domain.job import JobCatalogEntry, JobIssue
    warning = JobIssue("job_event_tail_incomplete", "warning", "末行不完整", "检查", "events/job_events.jsonl")
    error = JobIssue("job_manifest_invalid", "error", "清单无效", "修复", "job.json")
    common = dict(discovery_id="job-1", job_id="job-1", display_name="name", created_at="2026-08-31T16:00:00.000000Z", updated_at="2026-08-31T16:00:00.000000Z", demo_asset_id=HASH, demo_display_name="match.dem", map_name="de_nuke", target_player_id="target", phase=JobPhase.CREATED, durable_run_status=JobRunStatus.PENDING, effective_run_status=JobRunStatus.PENDING, round_progress=RoundProgressSummary(0, 0, 0, 0), final_artifact_kinds=(), healthy=True)
    healthy = JobCatalogEntry(issues=(warning,), **common)
    assert healthy.issues == (warning,)
    with pytest.raises(DomainSchemaError):
        JobCatalogEntry(issues=(error,), **common)
    with pytest.raises(DomainSchemaError):
        JobCatalogEntry(issues=(warning,), **{**common, "healthy": False})
    with pytest.raises(DomainSchemaError):
        JobCatalogEntry(issues=(), **{**common, "display_name": "https://secret"})
    with pytest.raises(DomainSchemaError):
        JobCatalogEntry(issues=(), **{**common, "demo_asset_id": "bad"})


@pytest.mark.parametrize("identifier", ["A", "a" * 65, "foo.", "foo ", "CON", ".", "..", True])
def test_path_identifiers_reject_case_dot_device_and_overlong_values(identifier):
    with pytest.raises(DomainSchemaError):
        JobManifest(
            identifier, "name", "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:00.000000Z",
            HASH, "match.dem", None, None, JobPhase.CREATED, JobRunStatus.PENDING,
            RoundProgressSummary(0, 0, 0, 0), (), None, (),
        )


@pytest.mark.parametrize("timestamp", [
    "2026-08-31T16:00:00Z", "2026-08-31T16:00:00.1Z", "2026-08-31T16:00:00.000000+00:00",
    "2026-02-30T16:00:00.000000Z", "2026-08-31T16:00:00.000000+08:00",
])
def test_manifest_rejects_noncanonical_or_impossible_timestamps(timestamp):
    with pytest.raises(DomainSchemaError):
        JobManifest(
            "job-1", "name", timestamp, timestamp, HASH, "match.dem", None, None,
            JobPhase.CREATED, JobRunStatus.PENDING, RoundProgressSummary(0, 0, 0, 0), (), None, (),
        )


def test_manifest_rejects_progress_arithmetic_and_nested_extra_keys():
    with pytest.raises(DomainSchemaError):
        RoundProgressSummary(1, 1, 1, 0)
    payload = JobManifest(
        "job-1", "name", "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:00.000000Z",
        HASH, "match.dem", None, None, JobPhase.CREATED, JobRunStatus.PENDING,
        RoundProgressSummary(0, 0, 0, 0), (), None, (),
    ).to_dict()
    payload["round_progress"]["extra"] = 1
    with pytest.raises(DomainSchemaError):
        JobManifest.from_dict(payload)


@pytest.mark.parametrize("payload", [{"api_key": "secret"}, {"value": "https://example.test"}, {1: "non-string-key"}, {"value": float("nan")}, {"value": float("inf")}])
def test_event_payload_is_json_only_and_private_free(payload):
    with pytest.raises(DomainSchemaError):
        JobEvent("event-1", "job-1", "run-1", "2026-08-31T16:00:00.000000Z", "job_created", payload)


def test_job_enum_contracts_have_all_current_values():
    assert tuple(item.value for item in JobPhase) == (
        "created", "timeline_ready", "voice_ready", "transcribed", "context_ready",
        "understanding_translating", "understood_translated", "draft_timeline_ready",
        "completed_draft", "review_pending", "reviewed", "final_timeline_ready",
        "subtitles_exported", "green_screen_rendered", "completed_without_video",
        "ready_for_render", "rendering", "video_ready", "completed_with_video",
    )
    assert tuple(item.value for item in JobRunStatus) == (
        "pending", "running", "succeeded", "failed", "cancelled", "interrupted",
    )
    assert tuple(item.value for item in FinalArtifactKind) == ("timeline", "subtitle", "green_screen", "video")
    assert tuple(item.value for item in FinalArtifactTimebase) == ("demo_global", "round_local")
    with pytest.raises(ValueError):
        JobPhase("CREATED")
    with pytest.raises(ValueError):
        JobRunStatus("PENDING")
    for enum_type, bad_value in (
        (FinalArtifactKind, "SUBTITLE"),
        (FinalArtifactTimebase, "DEMO_GLOBAL"),
    ):
        with pytest.raises(ValueError):
            enum_type(bad_value)

    manifest_payload = valid_manifest().to_dict()
    manifest_payload["phase"] = "CREATED"
    with pytest.raises(DomainSchemaError):
        JobManifest.from_dict(manifest_payload)

    artifact = FinalArtifactEntry(
        "artifact-1",
        FinalArtifactKind.SUBTITLE,
        "final/subtitles/out.srt",
        HASH,
        None,
        FinalArtifactTimebase.DEMO_GLOBAL,
    ).to_dict()
    artifact["kind"] = "SUBTITLE"
    with pytest.raises(DomainSchemaError):
        FinalArtifactEntry.from_dict(artifact)


@pytest.mark.parametrize("field", ["total", "succeeded", "failed", "review_pending"])
def test_round_progress_rejects_bool_for_every_integer_field(field):
    values = {"total": 1, "succeeded": 0, "failed": 0, "review_pending": 0}
    values[field] = True
    with pytest.raises(DomainSchemaError):
        RoundProgressSummary(**values)


def test_manifest_updated_at_must_not_precede_created_at_and_to_dict_is_detached():
    with pytest.raises(DomainSchemaError):
        JobManifest(
            "job-1", "name", "2026-08-31T16:00:01.000000Z", "2026-08-31T16:00:00.000000Z",
            HASH, "match.dem", None, None, JobPhase.CREATED, JobRunStatus.PENDING,
            RoundProgressSummary(0, 0, 0, 0), (), None, (),
        )
    manifest = JobManifest(
        "job-1", "name", "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:00.000000Z",
        HASH, "match.dem", None, None, JobPhase.CREATED, JobRunStatus.PENDING,
        RoundProgressSummary(0, 0, 0, 0), ("snap-1",), None, (),
    )
    payload = manifest.to_dict()
    payload["configuration_snapshot_ids"].append("snap-2")
    payload["round_progress"]["total"] = 100
    assert manifest.configuration_snapshot_ids == ("snap-1",)
    assert manifest.round_progress.total == 0


@pytest.mark.parametrize("value", ["https://private", "/home/private", "C:/secret", "\\\\server\\secret"])
def test_issue_message_suggestion_and_catalog_metadata_reject_private_or_invalid_values(value):
    from cs2pov.domain.job import JobIssue
    with pytest.raises(DomainSchemaError):
        JobIssue("job_manifest_invalid", "error", value, value, "job.json")


@pytest.mark.parametrize(
    "field, value",
    [
        ("display_name", "../private"),
        ("demo_display_name", "../private.dem"),
        ("demo_asset_id", "not-a-hash"),
        ("map_name", ":bad"),
        ("target_player_id", "../../player"),
    ],
)
def test_manifest_from_dict_rejects_invalid_names_hashes_and_identifiers(field, value):
    payload = valid_manifest().to_dict()
    payload[field] = value
    with pytest.raises(DomainSchemaError):
        JobManifest.from_dict(payload)


@pytest.mark.parametrize(
    "mutate, parser",
    [
        (lambda payload: payload.update(extra=True), JobManifest.from_dict),
        (lambda payload: payload.update(extra=True), JobRepositoryMarker.from_dict),
        (lambda payload: payload.update(extra=True), JobDemoSource.from_dict),
        (lambda payload: payload.update(extra=True), JobEvent.from_dict),
        (lambda payload: payload.update(extra=True), JobWriteClaim.from_dict),
        (lambda payload: payload.update(extra=True), FinalArtifactEntry.from_dict),
    ],
)
def test_every_job_document_rejects_unknown_root_keys(mutate, parser):
    artifact = FinalArtifactEntry(
        "artifact-1",
        FinalArtifactKind.SUBTITLE,
        "final/subtitles/out.srt",
        HASH,
        None,
        FinalArtifactTimebase.DEMO_GLOBAL,
    )
    values = {
        JobManifest.from_dict: valid_manifest().to_dict(),
        JobRepositoryMarker.from_dict: JobRepositoryMarker("job-001").to_dict(),
        JobDemoSource.from_dict: source().to_dict(),
        JobEvent.from_dict: JobEvent(
            "event-1",
            "job-001",
            "run-1",
            "2026-08-31T16:00:00.000000Z",
            "job_created",
            {},
        ).to_dict(),
        JobWriteClaim.from_dict: JobWriteClaim(
            "job-001",
            "run-1",
            1,
            "2026-08-31T16:00:00.000000Z",
            "2026-08-31T16:00:00.000000Z",
            "2026-08-31T16:00:30.000000Z",
        ).to_dict(),
        FinalArtifactEntry.from_dict: artifact.to_dict(),
    }
    payload = values[parser]
    mutate(payload)
    with pytest.raises(DomainSchemaError):
        parser(payload)


def test_demo_source_wraps_invalid_asset_reference_as_domain_error():
    with pytest.raises(DomainSchemaError):
        JobDemoSource("not-a-hash", "library/demos/not-a-hash/asset.json", "match.dem")


def test_manifest_rejects_casefold_duplicate_paths_and_snapshot_ids():
    with pytest.raises(DomainSchemaError):
        JobManifest(
            "job-1", "name", "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:00.000000Z",
            HASH, "match.dem", None, None, JobPhase.CREATED, JobRunStatus.PENDING,
            RoundProgressSummary(0, 0, 0, 0), ("snap-1", "snap-1"), None, (),
        )
    first = FinalArtifactEntry("artifact-1", FinalArtifactKind.SUBTITLE, "final/subtitles/file.srt", HASH, None, FinalArtifactTimebase.DEMO_GLOBAL)
    second = FinalArtifactEntry("artifact-2", FinalArtifactKind.SUBTITLE, "final/subtitles/FILE.SRT", HASH, None, FinalArtifactTimebase.DEMO_GLOBAL)
    with pytest.raises(DomainSchemaError):
        JobManifest("job-1", "name", "2026-08-31T16:00:00.000000Z", "2026-08-31T16:00:00.000000Z", HASH, "match.dem", None, None, JobPhase.CREATED, JobRunStatus.PENDING, RoundProgressSummary(0, 0, 0, 0), (), None, (first, second))

    duplicate_id = FinalArtifactEntry(
        "artifact-1",
        FinalArtifactKind.SUBTITLE,
        "final/subtitles/other.srt",
        HASH,
        None,
        FinalArtifactTimebase.DEMO_GLOBAL,
    )
    with pytest.raises(DomainSchemaError):
        JobManifest(
            "job-1",
            "name",
            "2026-08-31T16:00:00.000000Z",
            "2026-08-31T16:00:00.000000Z",
            HASH,
            "match.dem",
            None,
            None,
            JobPhase.CREATED,
            JobRunStatus.PENDING,
            RoundProgressSummary(0, 0, 0, 0),
            (),
            None,
            (first, duplicate_id),
        )
