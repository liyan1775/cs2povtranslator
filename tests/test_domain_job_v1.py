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
