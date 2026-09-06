from dataclasses import dataclass

from .schema import (
    require_current_schema,
    require_exact_keys,
    require_identifier,
    require_mapping,
    require_probability,
    require_sha256,
    require_str,
    reject_private_data,
)
from .fingerprint import content_fingerprint
from .errors import DomainSchemaError


@dataclass(frozen=True, slots=True)
class UnderstandingResult:
    cue_id: str
    round_id: str
    asr_original: str
    interpreted_source: str
    translated_zh: str
    confidence: float
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]
    model_invocation_record_id: str

    def __post_init__(self):
        for v, p in (
            (self.cue_id, "cue_id"),
            (self.round_id, "round_id"),
            (self.model_invocation_record_id, "model_invocation_record_id"),
        ):
            require_identifier(v, p)
        for v, p in (
            (self.asr_original, "asr_original"),
            (self.interpreted_source, "interpreted_source"),
            (self.translated_zh, "translated_zh"),
        ):
            require_str(v, p)
        require_probability(self.confidence, "confidence")
        if not isinstance(self.evidence, (list, tuple)) or not isinstance(
            self.warnings, (list, tuple)
        ):
            raise DomainSchemaError(
                "domain_field_invalid", "证据无效。", "请修正后重试。"
            )
        object.__setattr__(
            self, "evidence", tuple(require_str(x, "evidence") for x in self.evidence)
        )
        object.__setattr__(
            self, "warnings", tuple(require_str(x, "warnings") for x in self.warnings)
        )
        if not self.evidence or any(
            not isinstance(x, str) or not x for x in self.evidence
        ):
            raise DomainSchemaError(
                "domain_field_invalid", "证据无效。", "请修正后重试。"
            )
        # Scan the complete normalized durable representation, including all
        # evidence and warning strings, at the same boundary as from_dict.
        reject_private_data(self.to_dict(), "result")

    def to_dict(self):
        return {
            "schema_version": 1,
            "cue_id": self.cue_id,
            "round_id": self.round_id,
            "asr_original": self.asr_original,
            "interpreted_source": self.interpreted_source,
            "translated_zh": self.translated_zh,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
            "model_invocation_record_id": self.model_invocation_record_id,
        }

    def content_fingerprint(self):
        return content_fingerprint(self.to_dict())

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "result")
        reject_private_data(d, "result")
        require_current_schema(d, "result")
        require_exact_keys(
            d,
            {
                "schema_version",
                "cue_id",
                "round_id",
                "asr_original",
                "interpreted_source",
                "translated_zh",
                "confidence",
                "evidence",
                "warnings",
                "model_invocation_record_id",
            },
            set(),
            "result",
        )
        if not isinstance(d["evidence"], (list, tuple)) or not isinstance(
            d["warnings"], (list, tuple)
        ):
            raise DomainSchemaError("domain_field_invalid", "证据无效。", "请修正后重试。")
        return cls(
            d["cue_id"],
            d["round_id"],
            d["asr_original"],
            d["interpreted_source"],
            d["translated_zh"],
            d["confidence"],
            tuple(d["evidence"]),
            tuple(d["warnings"]),
            d["model_invocation_record_id"],
        )


@dataclass(frozen=True, slots=True)
class RoundUnderstandingDocument:
    round_id: str
    input_fingerprint: str
    model_configuration_snapshot_id: str
    invocation_record_id: str | None
    results: tuple[UnderstandingResult, ...]

    def __post_init__(self):
        reject_private_data(
            {
                "round_id": self.round_id,
                "input_fingerprint": self.input_fingerprint,
                "model_configuration_snapshot_id": self.model_configuration_snapshot_id,
                "invocation_record_id": self.invocation_record_id,
            },
            "round_understanding",
        )
        require_identifier(self.round_id, "round_id")
        require_sha256(self.input_fingerprint, "input_fingerprint")
        require_identifier(
            self.model_configuration_snapshot_id, "model_configuration_snapshot_id"
        )
        if not isinstance(self.results, (list, tuple)) or any(
            not isinstance(r, UnderstandingResult) for r in self.results
        ):
            raise DomainSchemaError(
                "domain_field_invalid", "回合文档无效。", "请修正后重试。"
            )
        object.__setattr__(self, "results", tuple(self.results))
        if (
            len({r.cue_id for r in self.results}) != len(self.results)
            or any(
                r.round_id != self.round_id
                or (
                    self.invocation_record_id is not None
                    and r.model_invocation_record_id != self.invocation_record_id
                )
                for r in self.results
            )
            or (self.results and self.invocation_record_id is None)
            or (not self.results and self.invocation_record_id is not None)
        ):
            raise DomainSchemaError(
                "round_reference_invalid", "回合文档无效。", "请修正后重试。"
            )
        if self.invocation_record_id is not None:
            require_identifier(self.invocation_record_id, "invocation_record_id")

    def to_dict(self):
        return {
            "schema_version": 1,
            "round_id": self.round_id,
            "input_fingerprint": self.input_fingerprint,
            "model_configuration_snapshot_id": self.model_configuration_snapshot_id,
            "invocation_record_id": self.invocation_record_id,
            "results": [r.to_dict() for r in self.results],
        }

    def content_fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "round_understanding")
        reject_private_data(d, "round_understanding")
        require_current_schema(d, "round_understanding")
        require_exact_keys(
            d,
            {
                "schema_version",
                "round_id",
                "input_fingerprint",
                "model_configuration_snapshot_id",
                "invocation_record_id",
                "results",
            },
            set(),
            "round_understanding",
        )
        if not isinstance(d["results"], (list, tuple)):
            raise DomainSchemaError(
                "domain_field_invalid", "结果无效。", "请修正后重试。"
            )
        return cls(
            d["round_id"],
            d["input_fingerprint"],
            d["model_configuration_snapshot_id"],
            d["invocation_record_id"],
            tuple(UnderstandingResult.from_dict(x) for x in d["results"]),
        )


def validate_understanding_against_transcript(result, cue):
    from .transcript import TranscriptCue

    if not isinstance(result, UnderstandingResult) or not isinstance(cue, TranscriptCue):
        raise DomainSchemaError("domain_field_invalid", "提示来源无效。", "请修正后重试。")
    if (
        result.cue_id != cue.cue_id
        or result.round_id != cue.round_id
        or result.asr_original != cue.asr_original
    ):
        raise DomainSchemaError(
            "cue_reference_invalid", "提示来源不匹配。", "请重新生成。"
        )
