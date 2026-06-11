from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class StageName(str, Enum):
    PREPARE_INPUT = "prepare_input"
    INSPECT_DEMO = "inspect_demo"
    EXTRACT_VOICE = "extract_voice"
    BUILD_VOICE_ACTIVITY = "build_voice_activity"
    PARSE_ROUNDS = "parse_rounds"
    TRANSCRIBE = "transcribe"
    BUILD_ROUND_CONTEXTS = "build_round_contexts"
    TRANSLATE = "translate"
    EXPORT_SUBTITLES = "export_subtitles"


STAGE_ORDER: list[StageName] = [
    StageName.PREPARE_INPUT,
    StageName.INSPECT_DEMO,
    StageName.EXTRACT_VOICE,
    StageName.BUILD_VOICE_ACTIVITY,
    StageName.PARSE_ROUNDS,
    StageName.TRANSCRIBE,
    StageName.BUILD_ROUND_CONTEXTS,
    StageName.TRANSLATE,
    StageName.EXPORT_SUBTITLES,
]


@dataclass(slots=True)
class Player:
    steamid: str
    name: str
    team_number: int | None = None
    voice_packets: int = 0
    decoded_packets: int = 0
    compact_wav_seconds: float = 0.0
    wav_path: str | None = None
    packet_info_path: str | None = None


@dataclass(slots=True)
class DemoInfo:
    input_path: str
    demo_path: str | None = None
    map_name: str | None = None
    server_name: str | None = None
    tick_rate: float = 64.0
    header: dict[str, Any] = field(default_factory=dict)
    players: list[Player] = field(default_factory=list)


@dataclass(slots=True)
class VoicePacketInfo:
    steamid: str
    player_name: str
    team_number: int | None
    demo_start: float
    demo_end: float
    wav_offset: float
    duration: float
    tick: int
    bytes: int


@dataclass(slots=True)
class VoiceActivityCue:
    id: str
    steamid: str
    player_name: str
    team_number: int | None
    start_time: float
    end_time: float
    packet_count: int


@dataclass(slots=True)
class Round:
    round_number: int
    start_time: float
    end_time: float
    start_tick: int | None = None
    end_tick: int | None = None
    is_warmup: bool = False
    winner_team: int | None = None
    source: str = "fallback"


@dataclass(slots=True)
class TranscriptSegment:
    id: str
    steamid: str
    player_name: str
    team_number: int | None
    start_time: float
    end_time: float
    original_text: str
    language: str | None = None
    round_number: int | None = None
    confidence: float | None = None


@dataclass(slots=True)
class RoundContext:
    round_number: int
    start_time: float
    end_time: float
    segments: list[TranscriptSegment]


@dataclass(slots=True)
class TranslationSegment:
    id: str
    steamid: str
    player_name: str
    team_number: int | None
    start_time: float
    end_time: float
    original_text: str
    translated_text: str
    round_number: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineConfig:
    output_root: str = "output"
    job_id: str | None = None
    map_name: str | None = None
    selected_pov_steamid: str | None = None
    selected_team_number: int | None = None
    export_scope: str = "pov_team"  # pov_team | pov_player | all
    target_language: str = "zh-CN"
    asr_language: str = "auto"
    transcription_profile: str = "balanced"
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_cache_dir: str | None = None
    translate_mode: str = "round"
    glossary_enabled: bool = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: int = 60
    dry_run_translation: bool = False
    skip_translation: bool = False
    max_rounds: int | None = None
    min_round_duration_seconds: float = 10.0
    whisper_vad_filter: bool = True
    transcription_mode: str = "round"  # round | activity | player
    activity_padding_seconds: float = 0.06
    keep_temp_audio: bool = False
    include_unrecognized_voice: bool = False
    unrecognized_min_duration_seconds: float = 0.35
    filter_hallucinations: bool = True
    max_subtitle_segment_seconds: float = 10.0
    voice_cluster_gap_seconds: float = 1.0
    subtitle_bilingual_format: str = "label"  # label | arrow
    subtitle_export_preset: str = "editing"  # editing | review | compact | debug
    subtitle_overlap_policy: str = "shift"  # allow | shift | compact
    subtitle_min_duration_seconds: float = 0.7


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return value


def player_from_dict(data: dict[str, Any]) -> Player:
    return Player(
        steamid=str(data.get("steamid", "")),
        name=str(data.get("name", "")),
        team_number=data.get("team_number"),
        voice_packets=int(data.get("voice_packets", data.get("packets", 0)) or 0),
        decoded_packets=int(data.get("decoded_packets", 0) or 0),
        compact_wav_seconds=float(data.get("compact_wav_seconds", data.get("duration", 0.0)) or 0.0),
        wav_path=data.get("wav_path") or data.get("wav"),
        packet_info_path=data.get("packet_info_path"),
    )


def transcript_from_dict(data: dict[str, Any]) -> TranscriptSegment:
    return TranscriptSegment(
        id=str(data["id"]),
        steamid=str(data["steamid"]),
        player_name=str(data.get("player_name", data.get("name", ""))),
        team_number=data.get("team_number"),
        start_time=float(data["start_time"]),
        end_time=float(data["end_time"]),
        original_text=str(data.get("original_text", data.get("text", ""))),
        language=data.get("language"),
        round_number=data.get("round_number"),
        confidence=data.get("confidence"),
    )


def round_from_dict(data: dict[str, Any]) -> Round:
    return Round(
        round_number=int(data["round_number"]),
        start_time=float(data["start_time"]),
        end_time=float(data["end_time"]),
        start_tick=data.get("start_tick"),
        end_tick=data.get("end_tick"),
        is_warmup=bool(data.get("is_warmup", False)),
        winner_team=data.get("winner_team"),
        source=str(data.get("source", "unknown")),
    )


def translation_from_dict(data: dict[str, Any]) -> TranslationSegment:
    return TranslationSegment(
        id=str(data["id"]),
        steamid=str(data["steamid"]),
        player_name=str(data.get("player_name", "")),
        team_number=data.get("team_number"),
        start_time=float(data["start_time"]),
        end_time=float(data["end_time"]),
        original_text=str(data.get("original_text", "")),
        translated_text=str(data.get("translated_text", "")),
        round_number=data.get("round_number"),
        warnings=list(data.get("warnings", [])),
    )
