"""Pure worker port: project evidence locally; validate full graphs at checkpoint.

The document digest commits to full persisted transcripts, not the worker's
projected request or provider transport bytes. No source objects are retained.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import (
    ModelCapability,
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.job_tasks import RoundTaskError, RoundTranslationTask
from cs2pov.domain.schema import (
    MAX_COUNT,
    reject_private_data,
    require_identifier,
    require_int,
    require_path_identifier,
    require_probability,
    require_sha256,
    require_str,
)
from cs2pov.domain.timebase import TimeRange
from cs2pov.domain.timeline import Round
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import RoundUnderstandingDocument


def _invalid(path, code="domain_field_invalid"):
    raise DomainSchemaError(code, "回合工作数据无效。", "请核对输入与调用记录。", path)


def _safe_payload(value):
    reject_private_data(value, "round_work")
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "input_fingerprint",
                "configuration_fingerprint",
                "request_content_fingerprint",
                "response_content_fingerprint",
            }:
                # Typed digests can contain 17-digit runs; they are not prose.
                require_sha256(item, key)
            else:
                _safe_payload(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _safe_payload(item)
    elif isinstance(value, str) and re.search(
        r"(?:[A-Za-z]:[\\/]|[A-Za-z][A-Za-z0-9+.-]*://|\\\\|(?<![A-Za-z0-9_])/\S|(?<![0-9])[0-9]{17}(?![0-9]))",
        value,
    ):
        _invalid("round_work", "domain_private_data_forbidden")


def _tuple_of(value, cls, path):
    if not isinstance(value, (tuple, list)) or any(type(v) is not cls for v in value):
        _invalid(path)
    return tuple(value)


def _task_hash(document_hash, configuration):
    return content_fingerprint(
        {
            "document_input_fingerprint": document_hash,
            "configuration_fingerprint": configuration.configuration_fingerprint,
        }
    )


@dataclass(frozen=True, slots=True)
class RoundWorkCue:
    cue_id: str
    speaker_token: str
    start_us: int
    end_us: int
    asr_original: str
    language: str
    confidence: float | None

    def __post_init__(self):
        require_identifier(self.cue_id, "cue_id")
        require_str(self.speaker_token, "speaker_token")
        if re.fullmatch(r"speaker-[0-9]{3,}", self.speaker_token) is None:
            _invalid("speaker_token")
        TimeRange(self.start_us, self.end_us)
        require_str(self.asr_original, "asr_original")
        require_identifier(self.language, "language")
        if self.confidence is not None:
            require_probability(self.confidence, "confidence")
        _safe_payload(
            (self.cue_id, self.speaker_token, self.asr_original, self.language)
        )


@dataclass(frozen=True, slots=True)
class RoundWorkRequest:
    task_id: str
    round_id: str
    round_number: int
    configuration: ModelConfigurationSnapshot
    cues: tuple[RoundWorkCue, ...]
    document_input_fingerprint: str
    task_input_fingerprint: str

    def __post_init__(self):
        require_path_identifier(self.task_id, "task_id")
        require_path_identifier(self.round_id, "round_id")
        if self.task_id != self.round_id:
            _invalid("task_id", "round_reference_invalid")
        require_int(self.round_number, "round_number", minimum=1, maximum=MAX_COUNT)
        if (
            type(self.configuration) is not ModelConfigurationSnapshot
            or self.configuration.capability
            is not ModelCapability.UNDERSTANDING_TRANSLATION
        ):
            _invalid("configuration")
        _safe_payload(self.configuration.to_dict())
        cues = _tuple_of(self.cues, RoundWorkCue, "cues")
        if len({cue.cue_id for cue in cues}) != len(cues) or cues != tuple(
            sorted(cues, key=lambda cue: (cue.start_us, cue.end_us, cue.cue_id))
        ):
            _invalid("cues", "cue_reference_invalid")
        speakers = set()
        for cue in cues:
            if cue.speaker_token not in speakers:
                if cue.speaker_token != f"speaker-{len(speakers) + 1:03d}":
                    _invalid("speaker_token")
                speakers.add(cue.speaker_token)
        object.__setattr__(self, "cues", cues)
        require_sha256(self.document_input_fingerprint, "document_input_fingerprint")
        require_sha256(self.task_input_fingerprint, "task_input_fingerprint")
        if self.task_input_fingerprint != _task_hash(
            self.document_input_fingerprint, self.configuration
        ):
            _invalid("task_input_fingerprint", "domain_fingerprint_mismatch")


def _records(records):
    records = _tuple_of(records, ModelInvocationRecord, "invocations")
    if len({record.invocation_id for record in records}) != len(records):
        _invalid("invocations", "invocation_reference_invalid")
    for record in records:
        _safe_payload(record.to_dict())
    return records


@dataclass(frozen=True, slots=True)
class RoundWorkResult:
    document: RoundUnderstandingDocument
    invocations: tuple[ModelInvocationRecord, ...]

    def __post_init__(self):
        if type(self.document) is not RoundUnderstandingDocument:
            _invalid("document")
        _safe_payload(self.document.to_dict())
        object.__setattr__(self, "invocations", _records(self.invocations))


class RoundWorkFailure(RuntimeError):
    error: RoundTaskError
    invocations: tuple[ModelInvocationRecord, ...]

    def __init__(self, error, invocations=(), *, cause=None):
        if type(error) is not RoundTaskError:
            _invalid("error")
        if cause is not None and not isinstance(cause, BaseException):
            _invalid("cause")
        self.error = error
        self.invocations = _records(invocations)
        super().__init__(error.message_zh)
        if cause is not None:
            self.__cause__ = cause


class RoundTranslationWorker(Protocol):
    async def translate(self, request: RoundWorkRequest) -> RoundWorkResult: ...


def build_round_work_request(
    *,
    task: RoundTranslationTask,
    round: Round,
    configuration: ModelConfigurationSnapshot,
    transcripts: tuple[TranscriptCue, ...],
) -> RoundWorkRequest:
    """Trusted application boundary; transcripts must be the full persisted set.

    This factory verifies hashes against the task, but cannot prove that a
    caller supplied every persisted cue. The coordinator owns that read.
    """
    if type(task) is not RoundTranslationTask or type(round) is not Round:
        _invalid("task")
    if (
        type(configuration) is not ModelConfigurationSnapshot
        or configuration.capability is not ModelCapability.UNDERSTANDING_TRANSLATION
    ):
        _invalid("configuration")
    if (
        task.task_id != round.round_id
        or task.round_id != round.round_id
        or task.configuration_snapshot_id != configuration.snapshot_id
    ):
        _invalid("task", "round_reference_invalid")
    full = _tuple_of(transcripts, TranscriptCue, "transcripts")
    selected = sorted(
        (cue for cue in full if cue.round_id == round.round_id),
        key=lambda cue: (cue.time_range.start_us, cue.time_range.end_us, cue.cue_id),
    )
    if len({cue.cue_id for cue in selected}) != len(selected):
        _invalid("transcripts", "cue_reference_invalid")
    digest = content_fingerprint(
        {
            "round_id": round.round_id,
            "transcript_cues": [cue.to_dict() for cue in selected],
        }
    )
    speakers = {}
    cues = []
    for cue in selected:
        token = speakers.setdefault(cue.player_id, f"speaker-{len(speakers) + 1:03d}")
        cues.append(
            RoundWorkCue(
                cue.cue_id,
                token,
                cue.time_range.start_us,
                cue.time_range.end_us,
                cue.asr_original,
                cue.language,
                cue.confidence,
            )
        )
    return RoundWorkRequest(
        task.task_id,
        round.round_id,
        round.display_number,
        configuration,
        tuple(cues),
        digest,
        task.input_fingerprint,
    )


def _validate_record_ownership(request, records):
    if type(request) is not RoundWorkRequest:
        _invalid("request")
    for record in _records(records):
        if (
            record.task_id != request.task_id
            or record.configuration_snapshot_id != request.configuration.snapshot_id
            or record.request_content_fingerprint != request.document_input_fingerprint
        ):
            _invalid("invocations", "invocation_reference_invalid")


def validate_round_work_result(
    request: RoundWorkRequest, result: RoundWorkResult
) -> None:
    """Validate only facts available in the projection; never forge source cues.

    Before publishing, the coordinator must rebuild from persisted inputs and
    run validate_understanding_document_graph with the full evidence graph.
    """
    if type(result) is not RoundWorkResult:
        _invalid("result")
    _validate_record_ownership(request, result.invocations)
    document = result.document
    if (
        document.round_id != request.round_id
        or document.model_configuration_snapshot_id != request.configuration.snapshot_id
        or document.input_fingerprint != request.document_input_fingerprint
    ):
        _invalid("document", "domain_fingerprint_mismatch")
    if tuple((r.cue_id, r.round_id, r.asr_original) for r in document.results) != tuple(
        (cue.cue_id, request.round_id, cue.asr_original) for cue in request.cues
    ):
        _invalid("results", "cue_reference_invalid")
    if not request.cues:
        if document.invocation_record_id is not None or result.invocations:
            _invalid("invocations", "invocation_reference_invalid")
        return
    authoritative = next(
        (
            record
            for record in result.invocations
            if record.invocation_id == document.invocation_record_id
        ),
        None,
    )
    if authoritative is None or any(
        r.model_invocation_record_id != authoritative.invocation_id
        for r in document.results
    ):
        _invalid("invocations", "invocation_reference_invalid")
    response_hash = content_fingerprint(
        {
            "round_id": request.round_id,
            "results": [r.to_dict() for r in document.results],
        }
    )
    if authoritative.response_content_fingerprint != response_hash:
        _invalid("invocations", "domain_fingerprint_mismatch")


def validate_round_work_failure(
    request: RoundWorkRequest, failure: RoundWorkFailure
) -> None:
    if (
        type(failure) is not RoundWorkFailure
        or type(failure.error) is not RoundTaskError
    ):
        _invalid("failure")
    _validate_record_ownership(request, failure.invocations)
