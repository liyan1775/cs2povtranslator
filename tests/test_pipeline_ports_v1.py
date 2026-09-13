from pathlib import Path
from datetime import datetime, timezone

import pytest

from cs2pov.application.pipeline_ports import (
    CurrentJobTimelineApplicationService,
    LegacyDemoParserPort,
    PipelinePortError,
)
from cs2pov.domain.job import CreateJobRequest, JobDemoSource, JobPhase
from cs2pov.domain.models import DemoInfo, Player, Round as LegacyRound
from cs2pov.domain.timebase import SourceClock
from cs2pov.domain.timeline import MatchPhase, RoundBoundaryConfidence
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths


ASSET_ID = "a" * 64


class FakeAdapter:
    def __init__(self, info: DemoInfo, rounds: list[LegacyRound]) -> None:
        self.info = info
        self.rounds = rounds
        self.calls: list[tuple] = []

    def inspect(self, demo_path: Path, original_input: Path) -> DemoInfo:
        self.calls.append(("inspect", demo_path, original_input))
        return self.info

    def parse_rounds(self, demo_path: Path, *, tick_rate: float, fallback_end_time: float, min_duration_seconds: float):
        self.calls.append(("rounds", demo_path, tick_rate, fallback_end_time, min_duration_seconds))
        return self.rounds


def _demo(tmp_path: Path) -> Path:
    path = tmp_path / "match.dem"
    path.write_bytes(b"anonymous demo")
    return path


def _info(*, map_name: str | None = "de_mirage", tick_rate: float = 64.0) -> DemoInfo:
    return DemoInfo(
        input_path="source.dem",
        map_name=map_name,
        server_name="fixture",
        tick_rate=tick_rate,
        players=[Player("player-a", "Alpha", 2), Player("player-b", "Bravo", 3)],
    )


def test_port_converts_tick_rounds_to_current_timeline_without_artifact_store(tmp_path: Path):
    adapter = FakeAdapter(
        _info(),
        [
            LegacyRound(9, 20.0, 40.0, 1280, 2560, source="demoparser2:round_start_cleaned"),
            LegacyRound(10, 40.0, 60.0, 2560, 3840, source="demoparser2:round_start_cleaned"),
        ],
    )

    timeline = LegacyDemoParserPort(adapter).parse_timeline(_demo(tmp_path), ASSET_ID)

    assert timeline.descriptor.map_name == "de_mirage"
    assert timeline.descriptor.tick_rate_numerator == 64
    assert timeline.descriptor.tick_rate_denominator == 1
    assert [r.round_id for r in timeline.rounds.rounds] == ["round-001", "round-002"]
    assert [(r.time_range.start_us, r.time_range.end_us) for r in timeline.rounds.rounds] == [
        (20_000_000, 40_000_000),
        (40_000_000, 60_000_000),
    ]
    assert all(r.confidence is RoundBoundaryConfidence.EXACT for r in timeline.rounds.rounds)
    assert all(r.match_phase is MatchPhase.UNKNOWN for r in timeline.rounds.rounds)
    assert [(a.source_clock, a.source_stream_id, a.source_start, a.source_end) for a in timeline.anchors] == [
        (SourceClock.DEMO_TICK, "demo", 1280, 2560),
        (SourceClock.DEMO_TICK, "demo", 2560, 3840),
    ]
    assert adapter.calls[0][0] == "inspect"
    assert adapter.calls[1][0] == "rounds"


def test_port_uses_fallback_round_without_fabricating_tick_anchor(tmp_path: Path):
    adapter = FakeAdapter(
        _info(),
        [LegacyRound(1, 0.0, 1.25, source="fallback_no_round_events")],
    )

    timeline = LegacyDemoParserPort(adapter).parse_timeline(_demo(tmp_path), ASSET_ID, fallback_end_time=1.25)

    round_value = timeline.rounds.rounds[0]
    assert round_value.confidence is RoundBoundaryConfidence.FALLBACK
    assert round_value.start_tick is None and round_value.end_tick is None
    assert round_value.time_range.start_us == 0
    assert round_value.time_range.end_us == 1_250_000
    assert timeline.anchors == ()


def test_port_normalizes_float_seconds_with_floor_start_and_ceil_end(tmp_path: Path):
    adapter = FakeAdapter(
        _info(tick_rate=59.94),
        [LegacyRound(1, 1.0000004, 1.0000005, source="estimated")],
    )

    timeline = LegacyDemoParserPort(adapter).parse_timeline(_demo(tmp_path), ASSET_ID)

    assert timeline.rounds.rounds[0].time_range.start_us == 1_000_000
    assert timeline.rounds.rounds[0].time_range.end_us == 1_000_001
    assert timeline.rounds.rounds[0].confidence is RoundBoundaryConfidence.ESTIMATED
    assert timeline.rounds.rounds[0].boundary_uncertainty_us == 16_684


@pytest.mark.parametrize(
    ("info", "rounds", "code"),
    [
        (_info(map_name=None), [], "pipeline_metadata_invalid"),
        (_info(tick_rate=0.0), [], "pipeline_metadata_invalid"),
        (_info(), [LegacyRound(1, 0.0, 1.0, 1, None)], "pipeline_rounds_invalid"),
        (_info(), [LegacyRound(1, 3.0, 2.0)], "pipeline_rounds_invalid"),
    ],
)
def test_port_rejects_invalid_metadata_or_rounds_before_returning_partial_timeline(
    tmp_path: Path, info: DemoInfo, rounds: list[LegacyRound], code: str
):
    with pytest.raises(PipelinePortError) as caught:
        LegacyDemoParserPort(FakeAdapter(info, rounds)).parse_timeline(_demo(tmp_path), ASSET_ID)

    assert caught.value.code == code


def test_port_rejects_missing_input_and_bad_asset_id(tmp_path: Path):
    port = LegacyDemoParserPort(FakeAdapter(_info(), []))

    with pytest.raises(PipelinePortError) as missing:
        port.parse_timeline(tmp_path / "missing.dem", ASSET_ID)
    with pytest.raises(PipelinePortError) as bad_asset:
        port.parse_timeline(_demo(tmp_path), "not-a-sha")

    assert missing.value.code == "pipeline_input_invalid"
    assert bad_asset.value.code == "domain_field_invalid"


def test_current_job_service_parses_before_creation_and_persists_timeline(tmp_path: Path):
    workspace = WorkspacePaths(tmp_path / "workspace")
    source_file = tmp_path / "source.dem"
    source_file.write_bytes(b"anonymous demo")
    assets = FileSystemDemoAssetRepository(workspace, clock=lambda: datetime(2026, 9, 13, tzinfo=timezone.utc))
    asset = assets.import_source(source_file).asset
    repository = FileSystemJobRepository(
        workspace,
        assets,
        clock=lambda: datetime(2026, 9, 13, tzinfo=timezone.utc),
        process_id_supplier=lambda: 1234,
    )
    request = CreateJobRequest(
        "job-pipeline-port",
        "Port Job",
        JobDemoSource(asset.asset_id, f"library/demos/{asset.asset_id}/asset.json", asset.display_name),
    )
    adapter = FakeAdapter(
        _info(),
        [LegacyRound(1, 0.0, 20.0, 0, 1280, source="demoparser2:round_start_cleaned")],
    )

    opened = CurrentJobTimelineApplicationService(
        repository,
        LegacyDemoParserPort(adapter),
    ).create_job_with_timeline(request, source_file)

    assert opened.manifest.phase is JobPhase.TIMELINE_READY
    persisted = repository.load_demo_timeline(request.job_id)
    assert persisted.descriptor.demo_asset_id == asset.asset_id
    assert persisted.rounds.rounds[0].round_id == "round-001"
    assert (workspace.jobs_dir / request.job_id / "timeline" / "demo.json").is_file()
    assert not (workspace.jobs_dir / request.job_id / "artifacts").exists()


def test_current_job_service_does_not_create_job_when_projection_fails(tmp_path: Path):
    workspace = WorkspacePaths(tmp_path / "workspace")
    source_file = tmp_path / "source.dem"
    source_file.write_bytes(b"anonymous demo")
    assets = FileSystemDemoAssetRepository(workspace, clock=lambda: datetime(2026, 9, 13, tzinfo=timezone.utc))
    asset = assets.import_source(source_file).asset
    repository = FileSystemJobRepository(workspace, assets)
    request = CreateJobRequest(
        "job-no-partial-port",
        "No Partial Job",
        JobDemoSource(asset.asset_id, f"library/demos/{asset.asset_id}/asset.json", asset.display_name),
    )
    adapter = FakeAdapter(_info(map_name=None), [])

    with pytest.raises(PipelinePortError) as caught:
        CurrentJobTimelineApplicationService(repository, LegacyDemoParserPort(adapter)).create_job_with_timeline(
            request,
            source_file,
        )

    assert caught.value.code == "pipeline_metadata_invalid"
    assert not workspace.jobs_dir.exists() or not list(workspace.jobs_dir.iterdir())
