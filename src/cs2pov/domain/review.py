from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .errors import DomainSchemaError
from .fingerprint import content_fingerprint
from .schema import (
    require_current_schema,
    require_exact_keys,
    require_identifier,
    require_mapping,
    require_optional_str,
    require_sha256,
    require_str,
    reject_private_data,
)
from .timebase import TimeRange


def _error(code: str, path: str = "review") -> None:
    raise DomainSchemaError(code, "审查领域数据无效。", "请修正后重试。", path)


def _sequence(value: object, path: str) -> tuple[Any, ...]:
    if not isinstance(value, (tuple, list)):
        _error("domain_field_invalid", path)
    return tuple(value)


def _timestamp(value: object) -> str:
    try:
        raw = require_str(value, "reviewed_at")
        parsed = datetime.fromisoformat(
            raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        )
    except (DomainSchemaError, TypeError, ValueError) as exc:
        raise DomainSchemaError(
            "review_decision_invalid", "审查决策无效。", "请修正后重试。", "reviewed_at"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _error("review_decision_invalid", "reviewed_at")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ReviewAction(Enum):
    ACCEPT = "accept"
    EDIT = "edit"
    EXCLUDE = "exclude"


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision_id: str
    cue_id: str
    source_result_fingerprint: str
    action: ReviewAction
    reviewed_at: str
    reviewer_label: str
    reason: str | None
    revised_time_range: TimeRange | None
    revised_interpreted_source: str | None
    revised_translated_zh: str | None

    def __post_init__(self) -> None:
        reject_private_data(self._privacy_payload(), "review_decision")
        require_identifier(self.decision_id, "decision_id")
        require_identifier(self.cue_id, "cue_id")
        require_sha256(self.source_result_fingerprint, "source_result_fingerprint")
        if not isinstance(self.action, ReviewAction):
            _error("review_decision_invalid", "action")
        object.__setattr__(self, "reviewed_at", _timestamp(self.reviewed_at))
        require_str(self.reviewer_label, "reviewer_label")
        require_optional_str(self.reason, "reason")
        if self.revised_time_range is not None and not isinstance(
            self.revised_time_range, TimeRange
        ):
            _error("review_decision_invalid", "revised_time_range")
        require_optional_str(
            self.revised_interpreted_source, "revised_interpreted_source"
        )
        require_optional_str(self.revised_translated_zh, "revised_translated_zh")
        has_revision = any(
            value is not None
            for value in (
                self.revised_time_range,
                self.revised_interpreted_source,
                self.revised_translated_zh,
            )
        )
        if self.action is ReviewAction.ACCEPT and has_revision:
            _error("review_decision_invalid", "action")
        if self.action is ReviewAction.EDIT and not has_revision:
            _error("review_decision_invalid", "action")
        if self.action is ReviewAction.EXCLUDE and (not self.reason or has_revision):
            _error("review_decision_invalid", "action")

    def _privacy_payload(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "cue_id": self.cue_id,
            "source_result_fingerprint": self.source_result_fingerprint,
            "reviewed_at": self.reviewed_at,
            "reviewer_label": self.reviewer_label,
            "reason": self.reason,
            "revised_interpreted_source": self.revised_interpreted_source,
            "revised_translated_zh": self.revised_translated_zh,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "decision_id": self.decision_id,
            "cue_id": self.cue_id,
            "source_result_fingerprint": self.source_result_fingerprint,
            "action": self.action.value,
            "reviewed_at": self.reviewed_at,
            "reviewer_label": self.reviewer_label,
            "reason": self.reason,
            "revised_start_us": (
                None
                if self.revised_time_range is None
                else self.revised_time_range.start_us
            ),
            "revised_end_us": (
                None
                if self.revised_time_range is None
                else self.revised_time_range.end_us
            ),
            "revised_interpreted_source": self.revised_interpreted_source,
            "revised_translated_zh": self.revised_translated_zh,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ReviewDecision":
        d = require_mapping(data, "review_decision")
        reject_private_data(d, "review_decision")
        require_current_schema(d, "review_decision")
        require_exact_keys(
            d,
            {
                "schema_version",
                "decision_id",
                "cue_id",
                "source_result_fingerprint",
                "action",
                "reviewed_at",
                "reviewer_label",
                "reason",
                "revised_start_us",
                "revised_end_us",
                "revised_interpreted_source",
                "revised_translated_zh",
            },
            set(),
            "review_decision",
        )
        try:
            action = ReviewAction(require_str(d["action"], "action"))
        except (DomainSchemaError, ValueError) as exc:
            raise DomainSchemaError(
                "review_decision_invalid", "审查决策无效。", "请修正后重试。", "action"
            ) from exc
        start, end = d["revised_start_us"], d["revised_end_us"]
        if (start is None) != (end is None):
            _error("review_decision_invalid", "revised_time_range")
        revised = None if start is None else TimeRange(start, end)
        return cls(
            require_identifier(d["decision_id"], "decision_id"),
            require_identifier(d["cue_id"], "cue_id"),
            require_sha256(d["source_result_fingerprint"], "source_result_fingerprint"),
            action,
            d["reviewed_at"],
            require_str(d["reviewer_label"], "reviewer_label"),
            require_optional_str(d["reason"], "reason"),
            revised,
            require_optional_str(
                d["revised_interpreted_source"], "revised_interpreted_source"
            ),
            require_optional_str(d["revised_translated_zh"], "revised_translated_zh"),
        )


@dataclass(frozen=True, slots=True)
class DraftCommsCue:
    cue_id: str
    round_id: str
    player_id: str
    start_us: int
    end_us: int
    asr_original: str
    interpreted_source: str
    translated_zh: str
    confidence: float
    evidence: tuple[str, ...]
    understanding_result_fingerprint: str

    def __post_init__(self) -> None:
        from .schema import require_int, require_probability, require_string_list

        reject_private_data(
            {
                "cue_id": self.cue_id,
                "round_id": self.round_id,
                "player_id": self.player_id,
                "asr_original": self.asr_original,
                "interpreted_source": self.interpreted_source,
                "translated_zh": self.translated_zh,
                "evidence": self.evidence,
            },
            "draft_cue",
        )
        require_identifier(self.cue_id, "cue_id")
        require_identifier(self.round_id, "round_id")
        require_identifier(self.player_id, "player_id")
        require_int(self.start_us, "start_us", minimum=0)
        require_int(self.end_us, "end_us", minimum=0)
        if self.end_us <= self.start_us:
            _error("timeline_invalid", "time_range")
        require_str(self.asr_original, "asr_original")
        require_str(self.interpreted_source, "interpreted_source")
        require_str(self.translated_zh, "translated_zh")
        require_probability(self.confidence, "confidence")
        object.__setattr__(
            self,
            "evidence",
            require_string_list(self.evidence, "evidence", allow_empty=False),
        )
        require_sha256(
            self.understanding_result_fingerprint, "understanding_result_fingerprint"
        )

    @classmethod
    def from_transcript_and_understanding(
        cls, transcript: object, understanding: object
    ) -> "DraftCommsCue":
        from .transcript import TranscriptCue
        from .understanding import UnderstandingResult

        if not isinstance(transcript, TranscriptCue) or not isinstance(
            understanding, UnderstandingResult
        ):
            _error("domain_field_invalid")
        if (
            transcript.cue_id != understanding.cue_id
            or transcript.round_id is None
            or transcript.round_id != understanding.round_id
            or transcript.asr_original != understanding.asr_original
        ):
            _error("cue_reference_invalid")
        return cls(
            transcript.cue_id,
            transcript.round_id,
            transcript.player_id,
            transcript.time_range.start_us,
            transcript.time_range.end_us,
            transcript.asr_original,
            understanding.interpreted_source,
            understanding.translated_zh,
            understanding.confidence,
            understanding.evidence,
            understanding.content_fingerprint(),
        )

    def to_dict(self, *, include_schema: bool = True) -> dict[str, object]:
        result = {
            "cue_id": self.cue_id,
            "round_id": self.round_id,
            "player_id": self.player_id,
            "start_us": self.start_us,
            "end_us": self.end_us,
            "asr_original": self.asr_original,
            "interpreted_source": self.interpreted_source,
            "translated_zh": self.translated_zh,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "understanding_result_fingerprint": self.understanding_result_fingerprint,
        }
        return {"schema_version": 1, **result} if include_schema else result

    @classmethod
    def from_dict(cls, data: object) -> "DraftCommsCue":
        d = require_mapping(data, "draft_cue")
        reject_private_data(d, "draft_cue")
        require_current_schema(d, "draft_cue")
        require_exact_keys(
            d,
            {
                "schema_version",
                "cue_id",
                "round_id",
                "player_id",
                "start_us",
                "end_us",
                "asr_original",
                "interpreted_source",
                "translated_zh",
                "confidence",
                "evidence",
                "understanding_result_fingerprint",
            },
            set(),
            "draft_cue",
        )
        return cls(
            d["cue_id"],
            d["round_id"],
            d["player_id"],
            d["start_us"],
            d["end_us"],
            d["asr_original"],
            d["interpreted_source"],
            d["translated_zh"],
            d["confidence"],
            _sequence(d["evidence"], "evidence"),
            d["understanding_result_fingerprint"],
        )


@dataclass(frozen=True, slots=True)
class ReviewedCommsCue:
    cue_id: str
    round_id: str
    player_id: str
    start_us: int
    end_us: int
    asr_original: str
    interpreted_source: str
    model_translated_zh: str
    model_confidence: float
    evidence: tuple[str, ...]
    final_interpreted_source: str
    final_translated_zh: str
    review_decision_id: str

    def __post_init__(self) -> None:
        from .schema import require_int, require_probability, require_string_list

        reject_private_data(
            {
                "cue_id": self.cue_id,
                "round_id": self.round_id,
                "player_id": self.player_id,
                "asr_original": self.asr_original,
                "interpreted_source": self.interpreted_source,
                "model_translated_zh": self.model_translated_zh,
                "evidence": self.evidence,
                "final_interpreted_source": self.final_interpreted_source,
                "final_translated_zh": self.final_translated_zh,
            },
            "reviewed_cue",
        )
        for value, path in (
            (self.cue_id, "cue_id"),
            (self.round_id, "round_id"),
            (self.player_id, "player_id"),
            (self.review_decision_id, "review_decision_id"),
        ):
            require_identifier(value, path)
        require_int(self.start_us, "start_us", minimum=0)
        require_int(self.end_us, "end_us", minimum=0)
        if self.end_us <= self.start_us:
            _error("timeline_invalid", "time_range")
        for value, path in (
            (self.asr_original, "asr_original"),
            (self.interpreted_source, "interpreted_source"),
            (self.model_translated_zh, "model_translated_zh"),
            (self.final_interpreted_source, "final_interpreted_source"),
            (self.final_translated_zh, "final_translated_zh"),
        ):
            require_str(value, path)
        require_probability(self.model_confidence, "model_confidence")
        object.__setattr__(
            self,
            "evidence",
            require_string_list(self.evidence, "evidence", allow_empty=False),
        )

    def to_dict(self, *, include_schema: bool = True) -> dict[str, object]:
        result = {
            "cue_id": self.cue_id,
            "round_id": self.round_id,
            "player_id": self.player_id,
            "start_us": self.start_us,
            "end_us": self.end_us,
            "asr_original": self.asr_original,
            "interpreted_source": self.interpreted_source,
            "model_translated_zh": self.model_translated_zh,
            "model_confidence": self.model_confidence,
            "evidence": list(self.evidence),
            "final_interpreted_source": self.final_interpreted_source,
            "final_translated_zh": self.final_translated_zh,
            "review_decision_id": self.review_decision_id,
        }
        return {"schema_version": 1, **result} if include_schema else result

    @classmethod
    def from_dict(cls, data: object) -> "ReviewedCommsCue":
        d = require_mapping(data, "reviewed_cue")
        reject_private_data(d, "reviewed_cue")
        require_current_schema(d, "reviewed_cue")
        require_exact_keys(
            d,
            {
                "schema_version",
                "cue_id",
                "round_id",
                "player_id",
                "start_us",
                "end_us",
                "asr_original",
                "interpreted_source",
                "model_translated_zh",
                "model_confidence",
                "evidence",
                "final_interpreted_source",
                "final_translated_zh",
                "review_decision_id",
            },
            set(),
            "reviewed_cue",
        )
        return cls(
            d["cue_id"],
            d["round_id"],
            d["player_id"],
            d["start_us"],
            d["end_us"],
            d["asr_original"],
            d["interpreted_source"],
            d["model_translated_zh"],
            d["model_confidence"],
            _sequence(d["evidence"], "evidence"),
            d["final_interpreted_source"],
            d["final_translated_zh"],
            d["review_decision_id"],
        )


def _validate_cues(cues: object, path: str, cue_type: type[Any]) -> tuple[Any, ...]:
    values = _sequence(cues, path)
    if any(not isinstance(cue, cue_type) for cue in values):
        _error("timeline_invalid", path)
    if len({cue.cue_id for cue in values}) != len(values):
        _error("timeline_invalid", path)
    if tuple((cue.start_us, cue.end_us, cue.cue_id) for cue in values) != tuple(
        sorted((cue.start_us, cue.end_us, cue.cue_id) for cue in values)
    ):
        _error("timeline_invalid", path)
    return values


@dataclass(frozen=True, slots=True)
class DraftCommsTimeline:
    demo_asset_id: str
    timebase: str
    input_fingerprint: str
    cues: tuple[DraftCommsCue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.cues, (tuple, list)):
            _error("domain_field_invalid", "cues")
        reject_private_data(
            {
                "demo_asset_id": self.demo_asset_id,
                "timebase": self.timebase,
                "input_fingerprint": self.input_fingerprint,
            },
            "draft_timeline",
        )
        require_sha256(self.demo_asset_id, "demo_asset_id")
        require_sha256(self.input_fingerprint, "input_fingerprint")
        if self.timebase != "demo-microseconds":
            _error("timeline_invalid", "timebase")
        values = _validate_cues(self.cues, "cues", DraftCommsCue)
        object.__setattr__(self, "cues", values)

    def to_dict(self, *, include_schema: bool = True) -> dict[str, object]:
        result = {
            "demo_asset_id": self.demo_asset_id,
            "timebase": self.timebase,
            "input_fingerprint": self.input_fingerprint,
            "cues": [cue.to_dict() for cue in self.cues],
        }
        return {"schema_version": 1, **result} if include_schema else result

    @classmethod
    def from_dict(cls, data: object) -> "DraftCommsTimeline":
        d = require_mapping(data, "draft_timeline")
        reject_private_data(d, "draft_timeline")
        require_current_schema(d, "draft_timeline")
        require_exact_keys(
            d,
            {
                "schema_version",
                "demo_asset_id",
                "timebase",
                "input_fingerprint",
                "cues",
            },
            set(),
            "draft_timeline",
        )
        return cls(
            d["demo_asset_id"],
            d["timebase"],
            d["input_fingerprint"],
            tuple(
                DraftCommsCue.from_dict(item) for item in _sequence(d["cues"], "cues")
            ),
        )

    def content_fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReviewedCommsTimeline:
    demo_asset_id: str
    timebase: str
    source_draft_fingerprint: str
    cues: tuple[ReviewedCommsCue, ...]
    excluded_decision_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.cues, (tuple, list)) or not isinstance(
            self.excluded_decision_ids, (tuple, list)
        ):
            _error("domain_field_invalid", "timeline")
        reject_private_data(
            {
                "demo_asset_id": self.demo_asset_id,
                "timebase": self.timebase,
                "source_draft_fingerprint": self.source_draft_fingerprint,
            },
            "reviewed_timeline",
        )
        require_sha256(self.demo_asset_id, "demo_asset_id")
        require_sha256(self.source_draft_fingerprint, "source_draft_fingerprint")
        if self.timebase != "demo-microseconds":
            _error("timeline_invalid", "timebase")
        values = _validate_cues(self.cues, "cues", ReviewedCommsCue)
        object.__setattr__(self, "cues", values)
        decision_ids = tuple(cue.review_decision_id for cue in values)
        ids = _sequence(self.excluded_decision_ids, "excluded_decision_ids")
        try:
            normalized = tuple(
                require_identifier(value, "excluded_decision_id") for value in ids
            )
        except DomainSchemaError:
            raise
        if len(set(normalized)) != len(normalized) or normalized != tuple(
            sorted(normalized)
        ):
            _error("timeline_invalid", "excluded_decision_ids")
        if len(set(decision_ids)) != len(decision_ids) or set(decision_ids) & set(
            normalized
        ):
            _error("review_decision_invalid", "decision_ids")
        object.__setattr__(self, "excluded_decision_ids", normalized)

    def to_dict(self, *, include_schema: bool = True) -> dict[str, object]:
        result = {
            "demo_asset_id": self.demo_asset_id,
            "timebase": self.timebase,
            "source_draft_fingerprint": self.source_draft_fingerprint,
            "cues": [cue.to_dict() for cue in self.cues],
            "excluded_decision_ids": list(self.excluded_decision_ids),
        }
        return {"schema_version": 1, **result} if include_schema else result

    @classmethod
    def from_dict(cls, data: object) -> "ReviewedCommsTimeline":
        d = require_mapping(data, "reviewed_timeline")
        reject_private_data(d, "reviewed_timeline")
        require_current_schema(d, "reviewed_timeline")
        require_exact_keys(
            d,
            {
                "schema_version",
                "demo_asset_id",
                "timebase",
                "source_draft_fingerprint",
                "cues",
                "excluded_decision_ids",
            },
            set(),
            "reviewed_timeline",
        )
        return cls(
            d["demo_asset_id"],
            d["timebase"],
            d["source_draft_fingerprint"],
            tuple(
                ReviewedCommsCue.from_dict(item)
                for item in _sequence(d["cues"], "cues")
            ),
            tuple(
                require_identifier(item, "excluded_decision_id")
                for item in _sequence(
                    d["excluded_decision_ids"], "excluded_decision_ids"
                )
            ),
        )


def compose_reviewed_timeline(
    draft: DraftCommsTimeline, decisions: object
) -> ReviewedCommsTimeline:
    if not isinstance(draft, DraftCommsTimeline):
        _error("domain_field_invalid", "draft")
    values = _sequence(decisions, "decisions")
    if any(not isinstance(decision, ReviewDecision) for decision in values):
        _error("review_decision_invalid", "decisions")
    if (
        len(values) != len(draft.cues)
        or len({decision.decision_id for decision in values}) != len(values)
        or len({decision.cue_id for decision in values}) != len(values)
    ):
        _error("review_decision_invalid", "decisions")
    by_cue = {decision.cue_id: decision for decision in values}
    if set(by_cue) != {cue.cue_id for cue in draft.cues}:
        _error("review_decision_invalid", "decisions")
    output: list[ReviewedCommsCue] = []
    excluded: list[str] = []
    for cue in draft.cues:
        decision = by_cue[cue.cue_id]
        if decision.source_result_fingerprint != cue.understanding_result_fingerprint:
            _error("domain_fingerprint_mismatch", "source_result_fingerprint")
        if decision.action is ReviewAction.EXCLUDE:
            excluded.append(decision.decision_id)
            continue
        final_start, final_end = cue.start_us, cue.end_us
        final_interpreted, final_translated = cue.interpreted_source, cue.translated_zh
        if decision.revised_time_range is not None:
            final_start, final_end = (
                decision.revised_time_range.start_us,
                decision.revised_time_range.end_us,
            )
        if decision.revised_interpreted_source is not None:
            final_interpreted = decision.revised_interpreted_source
        if decision.revised_translated_zh is not None:
            final_translated = decision.revised_translated_zh
        if decision.action is ReviewAction.EDIT and (
            final_start,
            final_end,
            final_interpreted,
            final_translated,
        ) == (cue.start_us, cue.end_us, cue.interpreted_source, cue.translated_zh):
            _error("review_decision_invalid", "action")
        output.append(
            ReviewedCommsCue(
                cue.cue_id,
                cue.round_id,
                cue.player_id,
                final_start,
                final_end,
                cue.asr_original,
                cue.interpreted_source,
                cue.translated_zh,
                cue.confidence,
                cue.evidence,
                final_interpreted,
                final_translated,
                decision.decision_id,
            )
        )
    output.sort(key=lambda cue: (cue.start_us, cue.end_us, cue.cue_id))
    return ReviewedCommsTimeline(
        draft.demo_asset_id,
        draft.timebase,
        draft.content_fingerprint(),
        tuple(output),
        tuple(sorted(excluded)),
    )
