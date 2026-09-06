"""Immutable current-version round tasks and their retained attempt history."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from enum import Enum

from .errors import DomainSchemaError
from .fingerprint import content_fingerprint
from .schema import (
    MAX_COUNT,
    reject_private_data,
    require_canonical_utc_timestamp,
    require_current_schema,
    require_exact_keys,
    require_int,
    require_mapping,
    require_path_identifier,
    require_sha256,
    require_str,
)

MAX_RETRY_DELAY_US = 86_400_000_000


def _invalid(path: str) -> None:
    raise DomainSchemaError(
        "domain_field_invalid", "回合任务数据无效。", "请修正后重试。", path
    )


def _sequence(value: object, path: str) -> tuple:
    if not isinstance(value, (tuple, list)):
        _invalid(path)
    return tuple(value)


def _wire(cls, value, path, *, versioned=False):
    data = require_mapping(value, path)
    reject_private_data(data, path)
    if versioned:
        require_current_schema(data, path)
    keys = {field.name for field in fields(cls)}
    require_exact_keys(
        data, keys | ({"schema_version"} if versioned else set()), set(), path
    )
    return {key: data[key] for key in keys}


def _enum(cls, value, path):
    try:
        return cls(value)
    except (ValueError, TypeError) as exc:
        raise DomainSchemaError(
            "domain_field_invalid", "任务状态无效。", "请修正后重试。", path
        ) from exc


def _identity(task_id, round_id, fingerprint, configuration):
    require_path_identifier(task_id, "task_id")
    require_path_identifier(round_id, "round_id")
    if task_id != round_id:
        _invalid("task_id")
    require_sha256(fingerprint, "input_fingerprint")
    require_path_identifier(configuration, "configuration_snapshot_id")


class RoundTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RoundAttemptStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    EXHAUSTED = "exhausted"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class RoundTaskError:
    code: str
    message_zh: str
    impact_zh: str
    suggestion_zh: str
    retryable: bool
    retry_after_us: int | None

    def __post_init__(self):
        require_path_identifier(self.code, "round_task_error.code")
        for name in ("message_zh", "impact_zh", "suggestion_zh"):
            value = require_str(getattr(self, name), name)
            if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
                _invalid(name)
            # Durable diagnostic text is a curated projection, never raw worker text.
            # Path-like slash tokens need no leading whitespace; Chinese letters
            # are word characters, so 17-digit runs use digit-only boundaries.
            if re.search(
                r"(?:[A-Za-z]:[\\/]|[A-Za-z][A-Za-z0-9+.-]*://|\\\\|/\S|(?<![0-9])[0-9]{17}(?![0-9]))",
                value,
            ):
                _invalid(name)
        if type(self.retryable) is not bool:
            _invalid("retryable")
        if self.retry_after_us is not None:
            require_int(
                self.retry_after_us,
                "retry_after_us",
                minimum=0,
                maximum=MAX_RETRY_DELAY_US,
            )
        reject_private_data(self.to_dict(), "round_task_error")

    def to_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, value):
        return cls(**_wire(cls, value, "round_task_error"))


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_delay_us: int
    max_delay_us: int

    def __post_init__(self):
        require_int(self.max_attempts, "max_attempts", minimum=1, maximum=100)
        require_int(
            self.base_delay_us, "base_delay_us", minimum=1, maximum=MAX_RETRY_DELAY_US
        )
        require_int(
            self.max_delay_us,
            "max_delay_us",
            minimum=self.base_delay_us,
            maximum=MAX_RETRY_DELAY_US,
        )

    def to_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, value):
        return cls(**_wire(cls, value, "retry_policy"))


@dataclass(frozen=True, slots=True)
class RoundTaskAttempt:
    attempt_id: str
    attempt_number: int
    input_fingerprint: str
    configuration_snapshot_id: str
    status: RoundAttemptStatus
    started_at: str
    finished_at: str | None
    invocation_record_ids: tuple[str, ...]
    result_fingerprint: str | None
    error: RoundTaskError | None

    def __post_init__(self):
        require_path_identifier(self.attempt_id, "attempt_id")
        require_int(self.attempt_number, "attempt_number", minimum=1, maximum=MAX_COUNT)
        require_sha256(self.input_fingerprint, "input_fingerprint")
        require_path_identifier(
            self.configuration_snapshot_id, "configuration_snapshot_id"
        )
        if not isinstance(self.status, RoundAttemptStatus):
            _invalid("attempt.status")
        require_canonical_utc_timestamp(self.started_at, "started_at")
        if self.finished_at is not None:
            require_canonical_utc_timestamp(self.finished_at, "finished_at")
            if self.finished_at <= self.started_at:
                _invalid("finished_at")
        ids = _sequence(self.invocation_record_ids, "invocation_record_ids")
        for item in ids:
            require_path_identifier(item, "invocation_record_ids[]")
        if len(set(ids)) != len(ids):
            _invalid("invocation_record_ids")
        object.__setattr__(self, "invocation_record_ids", ids)
        if self.result_fingerprint is not None:
            require_sha256(self.result_fingerprint, "result_fingerprint")
        if self.error is not None and not isinstance(self.error, RoundTaskError):
            _invalid("attempt.error")
        if (self.status is RoundAttemptStatus.RUNNING) != (self.finished_at is None):
            _invalid("finished_at")
        if (self.status is RoundAttemptStatus.SUCCEEDED) != (
            self.result_fingerprint is not None
        ):
            _invalid("result_fingerprint")
        failures = {
            RoundAttemptStatus.RETRYABLE_FAILED,
            RoundAttemptStatus.EXHAUSTED,
            RoundAttemptStatus.FAILED,
        }
        if (self.status in failures) != (self.error is not None):
            _invalid("attempt.error")
        if self.error is not None and self.error.retryable != (
            self.status is not RoundAttemptStatus.FAILED
        ):
            _invalid("attempt.error.retryable")

    def to_dict(self):
        return {
            "attempt_id": self.attempt_id,
            "attempt_number": self.attempt_number,
            "input_fingerprint": self.input_fingerprint,
            "configuration_snapshot_id": self.configuration_snapshot_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "invocation_record_ids": list(self.invocation_record_ids),
            "result_fingerprint": self.result_fingerprint,
            "error": None if self.error is None else self.error.to_dict(),
        }

    @classmethod
    def from_dict(cls, value):
        d = _wire(cls, value, "round_task_attempt")
        d["status"] = _enum(RoundAttemptStatus, d["status"], "attempt.status")
        if d["error"] is not None:
            d["error"] = RoundTaskError.from_dict(d["error"])
        return cls(**d)


@dataclass(frozen=True, slots=True)
class RoundTaskSpec:
    task_id: str
    round_id: str
    input_fingerprint: str
    configuration_snapshot_id: str

    def __post_init__(self):
        _identity(
            self.task_id,
            self.round_id,
            self.input_fingerprint,
            self.configuration_snapshot_id,
        )

    def to_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, value):
        return cls(**_wire(cls, value, "round_task_spec"))


@dataclass(frozen=True, slots=True)
class RoundTranslationTask:
    task_id: str
    round_id: str
    status: RoundTaskStatus
    input_fingerprint: str
    configuration_snapshot_id: str
    result_fingerprint: str | None
    attempts: tuple[RoundTaskAttempt, ...]
    next_retry_at: str | None
    updated_at: str

    def __post_init__(self):
        _identity(
            self.task_id,
            self.round_id,
            self.input_fingerprint,
            self.configuration_snapshot_id,
        )
        if not isinstance(self.status, RoundTaskStatus):
            _invalid("round_task.status")
        require_canonical_utc_timestamp(self.updated_at, "updated_at")
        if self.result_fingerprint is not None:
            require_sha256(self.result_fingerprint, "result_fingerprint")
        if self.next_retry_at is not None:
            require_canonical_utc_timestamp(self.next_retry_at, "next_retry_at")
            if self.next_retry_at <= self.updated_at:
                _invalid("next_retry_at")
        attempts = _sequence(self.attempts, "attempts")
        previous_end = None
        identifiers = set()
        for index, attempt in enumerate(attempts, 1):
            if not isinstance(attempt, RoundTaskAttempt):
                _invalid("attempts")
            if attempt.attempt_number != index or attempt.attempt_id in identifiers:
                _invalid("attempts")
            identifiers.add(attempt.attempt_id)
            if previous_end is not None and attempt.started_at <= previous_end:
                _invalid("attempts.started_at")
            if index < len(attempts) and attempt.status is RoundAttemptStatus.RUNNING:
                _invalid("attempts.status")
            previous_end = attempt.finished_at or attempt.started_at
            if previous_end > self.updated_at:
                _invalid("updated_at")
        object.__setattr__(self, "attempts", attempts)
        if (self.status is RoundTaskStatus.SUCCEEDED) != (
            self.result_fingerprint is not None
        ):
            _invalid("result_fingerprint")
        if (self.status is RoundTaskStatus.RETRY_WAIT) != (
            self.next_retry_at is not None
        ):
            _invalid("next_retry_at")
        last = attempts[-1] if attempts else None
        if self.status is RoundTaskStatus.PENDING:
            if last is not None and last.status is RoundAttemptStatus.RUNNING:
                _invalid("attempts")
            return
        if last is None or (last.input_fingerprint, last.configuration_snapshot_id) != (
            self.input_fingerprint,
            self.configuration_snapshot_id,
        ):
            _invalid("attempts")
        allowed = {
            RoundTaskStatus.RUNNING: {RoundAttemptStatus.RUNNING},
            RoundTaskStatus.RETRY_WAIT: {RoundAttemptStatus.RETRYABLE_FAILED},
            RoundTaskStatus.SUCCEEDED: {RoundAttemptStatus.SUCCEEDED},
            RoundTaskStatus.FAILED: {
                RoundAttemptStatus.FAILED,
                RoundAttemptStatus.EXHAUSTED,
            },
            RoundTaskStatus.CANCELLED: {
                RoundAttemptStatus.CANCELLED,
                RoundAttemptStatus.RETRYABLE_FAILED,
            },
            RoundTaskStatus.INTERRUPTED: {RoundAttemptStatus.INTERRUPTED},
        }
        if last.status not in allowed[self.status]:
            _invalid("round_task.status")
        if (
            self.status is RoundTaskStatus.SUCCEEDED
            and self.result_fingerprint != last.result_fingerprint
        ):
            _invalid("result_fingerprint")

    @classmethod
    def pending(
        cls,
        *,
        task_id,
        round_id,
        input_fingerprint,
        configuration_snapshot_id,
        updated_at,
    ):
        return cls(
            task_id,
            round_id,
            RoundTaskStatus.PENDING,
            input_fingerprint,
            configuration_snapshot_id,
            None,
            (),
            None,
            updated_at,
        )

    def to_dict(self):
        return {
            "schema_version": 1,
            "task_id": self.task_id,
            "round_id": self.round_id,
            "status": self.status.value,
            "input_fingerprint": self.input_fingerprint,
            "configuration_snapshot_id": self.configuration_snapshot_id,
            "result_fingerprint": self.result_fingerprint,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "next_retry_at": self.next_retry_at,
            "updated_at": self.updated_at,
        }

    def content_fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        d = _wire(cls, value, "round_task", versioned=True)
        d["status"] = _enum(RoundTaskStatus, d["status"], "round_task.status")
        d["attempts"] = tuple(
            RoundTaskAttempt.from_dict(a) for a in _sequence(d["attempts"], "attempts")
        )
        return cls(**d)
