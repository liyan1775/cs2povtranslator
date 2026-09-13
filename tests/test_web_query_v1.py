from __future__ import annotations

from pathlib import Path

from cs2pov.domain.assets import DemoAssetSummary
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.job import (
    JobCatalogEntry,
    JobDemoSource,
    JobEvent,
    JobInspection,
    JobIssue,
    JobManifest,
    JobPhase,
    JobRepositoryMarker,
    JobRunStatus,
    RoundProgressSummary,
)
from cs2pov.domain.timebase import SourceClock, TimeRange
from cs2pov.domain.timeline import (
    DemoDescriptor,
    DemoTimeline,
    MatchPhase,
    PlayerSnapshot,
    Round,
    RoundBoundaryConfidence,
    RoundCollection,
)
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import (
    RoundUnderstandingDocument,
    UnderstandingResult,
)
from cs2pov.domain.review import DraftCommsCue, DraftCommsTimeline
from cs2pov.storage.job_events import EventJournalRead
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService
from cs2pov.web.query import CurrentJobWebQueryService


ASSET_ID = "a" * 64
NOW = "2026-09-13T10:00:00.000000Z"


def _timeline() -> DemoTimeline:
    return DemoTimeline(
        DemoDescriptor(
            ASSET_ID,
            "de_mirage",
            None,
            64,
            1,
            (PlayerSnapshot("player-alpha", "Alpha", 2),),
        ),
        RoundCollection(
            (
                Round(
                    "round-001",
                    1,
                    TimeRange(100_000, 200_000),
                    None,
                    None,
                    MatchPhase.REGULATION_FIRST_HALF,
                    "fixture",
                    RoundBoundaryConfidence.EXACT,
                    0,
                ),
                Round(
                    "round-002",
                    2,
                    TimeRange(300_000, 400_000),
                    None,
                    None,
                    MatchPhase.REGULATION_FIRST_HALF,
                    "fixture",
                    RoundBoundaryConfidence.EXACT,
                    0,
                ),
            )
        ),
        (),
    )


def _cue(cue_id: str, round_id: str, start_us: int) -> TranscriptCue:
    return TranscriptCue(
        cue_id,
        "player-alpha",
        round_id,
        TimeRange(start_us, start_us + 20_000),
        SourceClock.DEMO_TICK,
        "demo",
        start_us,
        start_us + 20,
        f"text-{cue_id}",
        "en",
        0.9,
        ("anchor-1",),
        ("activity-1",),
        "asr-invocation",
    )


def _job_fixture():
    timeline = _timeline()
    cue_early = _cue("cue-early", "round-001", 110_000)
    cue_late = _cue("cue-late", "round-001", 150_000)
    result_early = UnderstandingResult(
        cue_early.cue_id,
        cue_early.round_id,
        cue_early.asr_original,
        "early meaning",
        "早期翻译",
        0.86,
        ("round context",),
        (),
        "translation-invocation",
    )
    result_late = UnderstandingResult(
        cue_late.cue_id,
        cue_late.round_id,
        cue_late.asr_original,
        "late meaning",
        "后期翻译",
        0.87,
        ("round context",),
        (),
        "translation-invocation",
    )
    document = RoundUnderstandingDocument(
        "round-001",
        "b" * 64,
        "snapshot-translation",
        "translation-invocation",
        (result_late, result_early),
    )
    draft = DraftCommsTimeline(
        ASSET_ID,
        "demo-microseconds",
        content_fingerprint({"fixture": "draft"}),
        (
            DraftCommsCue.from_transcript_and_understanding(cue_early, result_early),
            DraftCommsCue.from_transcript_and_understanding(cue_late, result_late),
        ),
    )
    source = JobDemoSource(
        ASSET_ID,
        f"library/demos/{ASSET_ID}/asset.json",
        "match.dem",
    )
    manifest = JobManifest(
        "job-web",
        "Web fixture",
        NOW,
        NOW,
        ASSET_ID,
        "match.dem",
        "de_mirage",
        "player-alpha",
        JobPhase.DRAFT_TIMELINE_READY,
        JobRunStatus.SUCCEEDED,
        RoundProgressSummary(2, 2, 0, 0),
        ("snapshot-translation",),
        None,
        (),
    )
    entry = JobCatalogEntry(
        "job-web",
        "job-web",
        "Web fixture",
        NOW,
        NOW,
        ASSET_ID,
        "match.dem",
        "de_mirage",
        "player-alpha",
        JobPhase.DRAFT_TIMELINE_READY,
        JobRunStatus.SUCCEEDED,
        JobRunStatus.SUCCEEDED,
        RoundProgressSummary(2, 2, 0, 0),
        (),
        True,
        (),
    )
    inspection = JobInspection(
        entry,
        JobRepositoryMarker("job-web"),
        manifest,
        source,
        (
            JobEvent(
                "event-1",
                "job-web",
                "run-1",
                NOW,
                "translation.completed",
                {"round_id": "round-001"},
            ),
        ),
        False,
    )
    return timeline, cue_early, cue_late, document, draft, entry, inspection


class _FakeDemoAssets:
    def list_assets(self):
        return (
            DemoAssetSummary(
                ASSET_ID,
                "match.dem",
                "dem",
                12,
                12,
                NOW,
                True,
                None,
            ),
        )


class _FakeJobs:
    def __init__(self):
        (
            self.timeline,
            self.cue_early,
            self.cue_late,
            self.document,
            self.draft,
            self.entry,
            self.inspection,
        ) = _job_fixture()
        self.damaged = JobCatalogEntry(
            "job-damaged",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (),
            False,
            (
                JobIssue(
                    "job_manifest_invalid",
                    "error",
                    "Job 清单无效。",
                    "请检查 job.json。",
                    "job.json",
                ),
            ),
        )

    def list_jobs(self):
        return (self.damaged, self.entry)

    def inspect_job(self, job_id):
        if job_id != "job-web":
            raise KeyError(job_id)
        return self.inspection

    def read_events(self, job_id):
        return EventJournalRead(self.inspection.events, False, ())

    def load_demo_timeline(self, job_id):
        return self.timeline

    def load_transcript_round(self, job_id, round_id):
        return (self.cue_late, self.cue_early)

    def load_round_understanding(self, job_id, round_id):
        return self.document

    def load_draft_timeline(self, job_id):
        return self.draft


def _service(tmp_path: Path) -> CurrentJobWebQueryService:
    paths = WorkspacePaths(tmp_path / "workspace")
    WorkspaceService(paths, minimum_free_bytes=0).initialize()
    return CurrentJobWebQueryService(
        paths,
        workspace_service=WorkspaceService(paths, minimum_free_bytes=0),
        demo_assets=_FakeDemoAssets(),
        jobs=_FakeJobs(),
    )


def test_query_service_projects_workspace_assets_jobs_and_rounds(tmp_path):
    service = _service(tmp_path)

    workspace = service.workspace()
    assert workspace["diagnostic"]["ok"] is True
    assert "workspace_id" in workspace
    assert str(tmp_path) not in str(workspace)

    assert service.demos()["items"][0]["display_name"] == "match.dem"
    jobs = service.jobs()
    assert jobs["items"][0]["discovery_id"] == "job-damaged"
    assert jobs["items"][0]["healthy"] is False
    assert jobs["items"][1]["job_id"] == "job-web"
    assert jobs["items"][1]["effective_run_status"] == "succeeded"

    detail = service.job("job-web")
    assert detail["manifest"]["phase"] == "draft_timeline_ready"
    assert detail["events"][0]["event_type"] == "translation.completed"

    round_detail = service.round("job-web", "round-001")
    assert [item["cue_id"] for item in round_detail["transcripts"]] == [
        "cue-early",
        "cue-late",
    ]
    assert [item["cue_id"] for item in round_detail["understanding"]["results"]] == [
        "cue-early",
        "cue-late",
    ]
    assert round_detail["draft"][0]["translated_zh"] == "早期翻译"


def test_query_service_rejects_unknown_round_with_stable_error(tmp_path):
    service = _service(tmp_path)

    try:
        service.round("job-web", "round-404")
    except Exception as exc:
        assert exc.code == "round_not_found"
        assert exc.message_zh
        assert exc.suggestion_zh
    else:
        raise AssertionError("expected stable web query error")


def test_query_service_default_construction_reads_current_filesystem_repositories(tmp_path):
    paths = WorkspacePaths(tmp_path / "workspace")
    WorkspaceService(paths, minimum_free_bytes=0).initialize()
    source_file = tmp_path / "match.dem"
    source_file.write_bytes(b"web-current-job")
    from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
    from cs2pov.storage.job_repository import FileSystemJobRepository
    from cs2pov.domain.job import CreateJobRequest

    assets = FileSystemDemoAssetRepository(paths)
    asset = assets.import_source(source_file).asset
    source = JobDemoSource(
        asset.asset_id,
        f"library/demos/{asset.asset_id}/asset.json",
        asset.display_name,
    )
    FileSystemJobRepository(paths, assets).create_job(
        CreateJobRequest("job-current", "Current Job", source)
    )

    service = CurrentJobWebQueryService(paths, workspace_service=WorkspaceService(paths, minimum_free_bytes=0))
    assert service.jobs()["items"][0]["job_id"] == "job-current"
    assert service.job("job-current")["manifest"]["phase"] == "created"
