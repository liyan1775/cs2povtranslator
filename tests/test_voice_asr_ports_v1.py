from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fractions import Fraction
import json
from pathlib import Path
import wave

import pytest

from cs2pov.application.pipeline_ports import CurrentJobTimelineApplicationService, LegacyDemoParserPort
from cs2pov.application.voice_asr_ports import (
    ASRSegment,
    ASRWindow,
    CurrentJobVoiceAsrApplicationService,
    LegacyFasterWhisperPort,
    LegacyVoiceExtractorPort,
    VoiceActivityCue,
    VoiceExtractionResult,
    VoicePacket,
    VoiceStream,
    _convert_asr_activity,
    build_voice_projection,
)
from cs2pov.domain.invocation import ModelCapability, ModelConfigurationSnapshot
from cs2pov.domain.job import CreateJobRequest, JobDemoSource, JobPhase
from cs2pov.domain.models import DemoInfo, Player, Round as LegacyRound
from cs2pov.domain.timebase import SourceClock, TimeRange
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths


ASSET_ID = "a" * 64


class _DemoAdapter:
    def inspect(self, demo_path: Path, original_input: Path) -> DemoInfo:
        return DemoInfo(
            input_path=str(original_input),
            map_name="de_mirage",
            server_name="fixture",
            tick_rate=64.0,
            players=(Player("player-a", "Alpha", 2), Player("player-b", "Bravo", 3)),
        )

    def parse_rounds(self, demo_path: Path, *, tick_rate: float, fallback_end_time: float, min_duration_seconds: float):
        return [
            LegacyRound(1, 0.0, 20.0, 0, 1280, source="demoparser2:round_start_cleaned"),
            LegacyRound(2, 30.0, 50.0, 1920, 3200, source="demoparser2:round_start_cleaned"),
        ]


class _Extractor:
    def __init__(self, streams: tuple[VoiceStream, ...]):
        self.streams = streams

    def extract(self, demo_path: Path, scratch_dir: Path, *, tick_rate):
        return VoiceExtractionResult(self.streams)


class _ASR:
    def __init__(self, *, fail_activity_id: str | None = None):
        self.fail_activity_id = fail_activity_id

    def transcribe(self, window: ASRWindow) -> tuple[ASRSegment, ...]:
        if window.activity_id == self.fail_activity_id:
            raise RuntimeError("provider failure")
        return (
            ASRSegment(window.source_start, window.source_end, "hello", "en", 0.9),
        )


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source.dem"
    source.write_bytes(b"anonymous demo")
    return source


def _job(tmp_path: Path):
    workspace = WorkspacePaths(tmp_path / "workspace")
    source = _source(tmp_path)
    assets = FileSystemDemoAssetRepository(
        workspace,
        clock=lambda: datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    asset = assets.import_source(source).asset
    class Clock:
        def __init__(self):
            self.current = datetime(2026, 9, 13, tzinfo=timezone.utc)

        def __call__(self):
            self.current += timedelta(microseconds=1)
            return self.current

    clock = Clock()
    repository = FileSystemJobRepository(
        workspace,
        assets,
        clock=clock,
        process_id_supplier=lambda: 1234,
    )
    request = CreateJobRequest(
        "job-voice-asr",
        "Voice ASR Job",
        JobDemoSource(asset.asset_id, f"library/demos/{asset.asset_id}/asset.json", asset.display_name),
    )
    CurrentJobTimelineApplicationService(
        repository,
        LegacyDemoParserPort(_DemoAdapter()),
    ).create_job_with_timeline(request, source)
    return workspace, repository, request, source


def _write_test_audio(path: Path, sample_count: int = 72_000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24_000)
        handle.writeframes(b"\0\0" * sample_count)
    return path


def _streams(tmp_path: Path) -> tuple[VoiceStream, ...]:
    return (
        VoiceStream(
            "player-a",
            "Alpha",
            2,
            24_000,
            _write_test_audio(tmp_path / "alpha.wav"),
            (
                VoicePacket(0, 24_000, TimeRange(1_000_000, 2_000_000)),
                VoicePacket(24_000, 48_000, TimeRange(2_000_000, 3_000_000)),
                VoicePacket(48_000, 72_000, TimeRange(31_000_000, 32_000_000)),
            ),
        ),
    )


def _configuration() -> ModelConfigurationSnapshot:
    return ModelConfigurationSnapshot(
        "asr-config",
        ModelCapability.ASR,
        "faster-whisper",
        None,
        "base",
        None,
        {"device": "cpu", "compute_type": "int8"},
        (),
        "legacy-faster-whisper-v1",
    )


def test_voice_projection_adds_audio_anchors_and_exact_contiguous_activities(tmp_path: Path):
    timeline = LegacyDemoParserPort(_DemoAdapter()).parse_timeline(_source(tmp_path), ASSET_ID)
    projected, activities = build_voice_projection(timeline, VoiceExtractionResult(_streams(tmp_path)))

    audio_anchors = [a for a in projected.anchors if a.source_clock is SourceClock.COMPACT_AUDIO_SAMPLE]
    assert len(audio_anchors) == 3
    assert len(activities) == 2
    assert activities[0].packet_count == 2
    assert activities[0].anchor_ids == (audio_anchors[0].anchor_id, audio_anchors[1].anchor_id)
    assert activities[1].time_range == TimeRange(31_000_000, 32_000_000)


def test_voice_projection_keeps_overlapping_players_as_independent_activities(tmp_path: Path):
    timeline = LegacyDemoParserPort(_DemoAdapter()).parse_timeline(_source(tmp_path), ASSET_ID)
    streams = _streams(tmp_path) + (
        VoiceStream(
            "player-b",
            "Bravo",
            3,
            24_000,
            _write_test_audio(tmp_path / "bravo.wav"),
            (VoicePacket(0, 24_000, TimeRange(1_000_000, 2_000_000)),),
        ),
    )
    projected, activities = build_voice_projection(timeline, VoiceExtractionResult(streams))

    assert len(activities) == 3
    assert {activity.player_id for activity in activities} == {"player-a", "player-b"}
    assert sum(1 for anchor in projected.anchors if anchor.source_clock is SourceClock.COMPACT_AUDIO_SAMPLE) == 4


def test_asr_port_rejects_a_source_span_that_crosses_a_silence_gap(tmp_path: Path):
    timeline = LegacyDemoParserPort(_DemoAdapter()).parse_timeline(_source(tmp_path), ASSET_ID)
    projected, _ = build_voice_projection(
        timeline,
        VoiceExtractionResult(
            (
                VoiceStream(
                    "player-a",
                    "Alpha",
                    2,
                    24_000,
                    tmp_path / "alpha.wav",
                    (
                        VoicePacket(0, 24_000, TimeRange(1_000_000, 2_000_000)),
                        VoicePacket(24_000, 48_000, TimeRange(3_000_000, 4_000_000)),
                    ),
                ),
            )
        ),
    )
    anchors = tuple(a for a in projected.anchors if a.source_clock is SourceClock.COMPACT_AUDIO_SAMPLE)
    activity = VoiceActivityCue(
        "activity-player-a-00001",
        "player-a",
        TimeRange(1_000_000, 4_000_000),
        2,
        tuple(a.anchor_id for a in anchors),
        16_000,
    )
    with pytest.raises(Exception) as caught:
        _convert_asr_activity(
            activity,
            "round-001",
            (ASRSegment(0, 48_000, "crosses silence", "en", 0.5),),
            projected,
            (activity,),
            _configuration(),
        )
    assert getattr(caught.value, "code", None) == "pipeline_asr_result_invalid"


def test_current_job_voice_asr_persists_reopenable_language_graph(tmp_path: Path):
    workspace, repository, request, source = _job(tmp_path)
    report = CurrentJobVoiceAsrApplicationService(
        repository,
        _Extractor(_streams(tmp_path)),
        _ASR(),
    ).run(request.job_id, source, _configuration(), workspace.temp_dir / "voice-run")

    assert report.job.manifest.phase is JobPhase.TRANSCRIBED
    assert report.failed_round_ids == ()
    assert report.completed_round_ids == ("round-001", "round-002")
    assert len(repository.load_voice_activities(request.job_id)) == 2
    assert len(repository.load_transcript_round(request.job_id, "round-001")) == 1
    assert len(repository.load_transcript_round(request.job_id, "round-002")) == 1
    graph = repository.load_language_graph(request.job_id)
    assert len(graph.transcripts) == 2
    assert len(graph.invocations) == 2
    media = repository.load_audio_media(request.job_id)
    assert len(media) == 1
    assert media[0].player_id == "player-a"
    assert (
        workspace.jobs_dir
        / request.job_id
        / media[0].relative_path
    ).is_file()


def test_one_failed_round_does_not_checkpoint_sibling_round(tmp_path: Path):
    workspace, repository, request, source = _job(tmp_path)
    failed_id = "activity-player-a-00002"
    report = CurrentJobVoiceAsrApplicationService(
        repository,
        _Extractor(_streams(tmp_path)),
        _ASR(fail_activity_id=failed_id),
    ).run(request.job_id, source, _configuration(), workspace.temp_dir / "voice-run")

    assert report.job.manifest.phase is JobPhase.VOICE_READY
    assert report.completed_round_ids == ("round-001",)
    assert report.failed_round_ids == ("round-002",)
    assert report.errors == ((failed_id, "pipeline_asr_result_invalid"),)
    assert len(repository.load_transcript_round(request.job_id, "round-001")) == 1


def test_speechless_round_is_persisted_as_an_empty_transcript(tmp_path: Path):
    workspace, repository, request, source = _job(tmp_path)
    audio = _write_test_audio(tmp_path / "alpha.wav")
    streams = (
        VoiceStream(
            "player-a",
            "Alpha",
            2,
            24_000,
            audio,
            (VoicePacket(0, 24_000, TimeRange(1_000_000, 2_000_000)),),
        ),
    )
    report = CurrentJobVoiceAsrApplicationService(
        repository,
        _Extractor(streams),
        _ASR(),
    ).run(request.job_id, source, _configuration(), workspace.temp_dir / "voice-run")

    assert report.job.manifest.phase is JobPhase.TRANSCRIBED
    assert repository.load_transcript_round(request.job_id, "round-001")
    assert repository.load_transcript_round(request.job_id, "round-002") == ()


def test_unassigned_activity_is_persisted_separately(tmp_path: Path):
    workspace, repository, request, source = _job(tmp_path)
    audio = _write_test_audio(tmp_path / "alpha.wav")
    streams = (
        VoiceStream(
            "player-a",
            "Alpha",
            2,
            24_000,
            audio,
            (VoicePacket(0, 24_000, TimeRange(21_000_000, 22_000_000)),),
        ),
    )
    report = CurrentJobVoiceAsrApplicationService(
        repository,
        _Extractor(streams),
        _ASR(),
    ).run(request.job_id, source, _configuration(), workspace.temp_dir / "voice-run")

    assert report.job.manifest.phase is JobPhase.TRANSCRIBED
    unassigned = repository.load_unassigned_transcript(request.job_id)
    assert len(unassigned) == 1 and unassigned[0].round_id is None


def test_legacy_voice_extractor_converts_manifest_to_sample_packets(tmp_path: Path):
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    audio = voice_dir / "alpha.wav"
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(1_000)
        handle.writeframes(b"\0\0" * 500)
    packets = voice_dir / "alpha.packets.json"
    packets.write_text(
        json.dumps(
            [
                {
                    "wav_offset": 0.0,
                    "duration": 0.25,
                    "demo_start": 1.0,
                    "demo_end": 1.25,
                }
            ]
        ),
        encoding="utf-8",
    )

    class Adapter:
        def extract_voice(self, demo_path, target_dir, *, tick_rate):
            return {
                "sample_rate": 1_000,
                "players": [
                    {
                        "steamid": "player-a",
                        "name": "Alpha",
                        "team_number": 2,
                        "wav_path": str(audio),
                        "packet_info_path": str(packets),
                    }
                ],
            }

    result = LegacyVoiceExtractorPort(Adapter()).extract(
        _source(tmp_path),
        tmp_path,
        tick_rate=Fraction(64, 1),
    )
    assert result.streams[0].packets[0] == VoicePacket(0, 250, TimeRange(1_000_000, 1_250_000))


def test_legacy_faster_whisper_port_maps_window_offsets_and_cleans_slice(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(1_000)
        handle.writeframes(b"\0\0" * 500)

    seen = {}

    class Adapter:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def transcribe(self, path):
            seen["path"] = path
            return [{"start": 0.1, "end": 0.2, "text": "hello", "language": "en", "confidence": 0.8}]

    window = ASRWindow("activity-a", "player-a", audio, tmp_path / "scratch", 1_000, 100, 300)
    result = LegacyFasterWhisperPort(adapter_factory=Adapter).transcribe(window)

    assert result == (ASRSegment(200, 300, "hello", "en", 0.8),)
    assert seen["path"] == tmp_path / "scratch" / "activity-a.wav"
    assert not seen["path"].exists()
