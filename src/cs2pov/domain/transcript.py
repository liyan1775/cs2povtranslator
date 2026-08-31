from dataclasses import dataclass
from .errors import DomainSchemaError
from .schema import *
from .timebase import *


@dataclass(frozen=True, slots=True)
class TranscriptCue:
    cue_id: str
    player_id: str
    round_id: str | None
    time_range: TimeRange
    source_clock: SourceClock
    source_stream_id: str
    source_start: int
    source_end: int
    asr_original: str
    language: str
    confidence: float | None
    anchor_ids: tuple[str, ...]
    voice_activity_ids: tuple[str, ...]
    asr_invocation_record_id: str

    def __post_init__(self):
        for v, p in (
            (self.cue_id, "cue_id"),
            (self.player_id, "player_id"),
            (self.source_stream_id, "source_stream_id"),
            (self.asr_invocation_record_id, "asr_invocation_record_id"),
        ):
            require_identifier(v, p)
        if self.round_id is not None:
            require_identifier(self.round_id, "round_id")
        if not isinstance(self.time_range, TimeRange) or not isinstance(
            self.source_clock, SourceClock
        ):
            raise DomainSchemaError(
                "domain_field_invalid", "提示无效。", "请修正后重试。"
            )
        if self.source_end <= self.source_start:
            raise DomainSchemaError(
                "domain_field_invalid", "提示无效。", "请修正后重试。"
            )
        require_int(
            self.source_start, "source_start", minimum=0, maximum=MAX_SOURCE_POSITION
        )
        require_int(
            self.source_end, "source_end", minimum=0, maximum=MAX_SOURCE_POSITION
        )
        require_str(self.asr_original, "asr_original")
        require_identifier(self.language, "language")
        if self.confidence is not None:
            require_probability(self.confidence, "confidence")
        if not isinstance(self.anchor_ids, (list, tuple)) or not isinstance(
            self.voice_activity_ids, (list, tuple)
        ):
            raise DomainSchemaError(
                "domain_field_invalid", "提示无效。", "请修正后重试。"
            )
        object.__setattr__(
            self,
            "anchor_ids",
            tuple(require_identifier(x, "anchor_id") for x in self.anchor_ids),
        )
        object.__setattr__(
            self,
            "voice_activity_ids",
            tuple(
                require_identifier(x, "voice_activity_id")
                for x in self.voice_activity_ids
            ),
        )
        if (
            not self.anchor_ids
            or any(not isinstance(x, str) for x in self.anchor_ids)
            or any(not isinstance(x, str) for x in self.voice_activity_ids)
        ):
            raise DomainSchemaError(
                "domain_field_invalid", "提示无效。", "请修正后重试。"
            )
        reject_private_data(
            {"asr_original": self.asr_original, "language": self.language}, "cue"
        )

    @classmethod
    def from_source_span(
        cls,
        cue_id,
        player_id,
        round_id,
        source_clock,
        source_stream_id,
        source_start,
        source_end,
        anchors,
        asr_original,
        language,
        confidence,
        voice_activity_ids,
        asr_invocation_record_id,
    ):
        m = map_source_range(
            anchors, source_clock, source_stream_id, source_start, source_end
        )
        if not m.is_contiguous:
            raise DomainSchemaError(
                "cue_time_discontinuous", "提示时间不连续。", "请拆分后重试。"
            )
        return cls(
            cue_id,
            player_id,
            round_id,
            m.envelope,
            source_clock,
            source_stream_id,
            source_start,
            source_end,
            asr_original,
            language,
            confidence,
            m.anchor_ids,
            voice_activity_ids,
            asr_invocation_record_id,
        )

    def to_dict(self):
        return {
            "schema_version": 1,
            "cue_id": self.cue_id,
            "player_id": self.player_id,
            "round_id": self.round_id,
            "start_us": self.time_range.start_us,
            "end_us": self.time_range.end_us,
            "source_clock": self.source_clock.value,
            "source_stream_id": self.source_stream_id,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "asr_original": self.asr_original,
            "language": self.language,
            "confidence": self.confidence,
            "anchor_ids": list(self.anchor_ids),
            "voice_activity_ids": list(self.voice_activity_ids),
            "asr_invocation_record_id": self.asr_invocation_record_id,
        }

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "cue")
        reject_private_data(d, "cue")
        require_current_schema(d, "cue")
        require_exact_keys(
            d,
            {
                "schema_version",
                "cue_id",
                "player_id",
                "round_id",
                "start_us",
                "end_us",
                "source_clock",
                "source_stream_id",
                "source_start",
                "source_end",
                "asr_original",
                "language",
                "confidence",
                "anchor_ids",
                "voice_activity_ids",
                "asr_invocation_record_id",
            },
            set(),
            "cue",
        )
        if not isinstance(d["anchor_ids"], (list, tuple)) or not isinstance(
            d["voice_activity_ids"], (list, tuple)
        ):
            raise DomainSchemaError(
                "domain_field_invalid", "提示无效。", "请修正后重试。"
            )
        try:
            clock = SourceClock(d["source_clock"])
        except (ValueError, TypeError) as exc:
            raise DomainSchemaError(
                "domain_field_invalid", "提示无效。", "请修正后重试。"
            ) from exc
        return cls(
            d["cue_id"],
            d["player_id"],
            d["round_id"],
            TimeRange(d["start_us"], d["end_us"]),
            clock,
            d["source_stream_id"],
            d["source_start"],
            d["source_end"],
            d["asr_original"],
            d["language"],
            d["confidence"],
            tuple(d["anchor_ids"]),
            tuple(d["voice_activity_ids"]),
            d["asr_invocation_record_id"],
        )
