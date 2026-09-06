"""Pure task transitions; retries are counted per input/configuration pair."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from .errors import DomainSchemaError
from .job_tasks import (
    RetryPolicy,
    RoundAttemptStatus,
    RoundTaskAttempt,
    RoundTaskError,
    RoundTaskSpec,
    RoundTaskStatus,
    RoundTranslationTask,
)
from .schema import (
    MAX_COUNT,
    require_canonical_utc_timestamp,
    require_int,
    require_path_identifier,
)


def _invalid() -> None:
    raise DomainSchemaError(
        "domain_state_transition_invalid",
        "当前回合状态不允许此操作。",
        "请重新读取任务状态后重试。",
        "round_task.status",
    )


def _check(task, allowed, at):
    if not isinstance(task, RoundTranslationTask) or task.status not in allowed:
        _invalid()
    require_canonical_utc_timestamp(at, "round_task.updated_at")
    if at <= task.updated_at:
        _invalid()


def _merge_invocation_record_ids(existing, supplied):
    if not isinstance(supplied, (tuple, list)):
        raise DomainSchemaError(
            "domain_field_invalid",
            "调用记录引用无效。",
            "请修正后重试。",
            "invocation_record_ids",
        )
    seen = set()
    supplied_ids = []
    for invocation_record_id in supplied:
        require_path_identifier(invocation_record_id, "invocation_record_ids[]")
        if invocation_record_id in seen:
            raise DomainSchemaError(
                "domain_field_invalid",
                "调用记录引用无效。",
                "请修正后重试。",
                "invocation_record_ids",
            )
        seen.add(invocation_record_id)
        supplied_ids.append(invocation_record_id)
    return existing + tuple(
        invocation_record_id
        for invocation_record_id in supplied_ids
        if invocation_record_id not in existing
    )


def _finish(
    task,
    *,
    at,
    status,
    attempt_status,
    error=None,
    result_fingerprint=None,
    invocation_record_ids=(),
    next_retry_at=None,
):
    invocation_record_ids = _merge_invocation_record_ids(
        task.attempts[-1].invocation_record_ids, invocation_record_ids
    )
    closed = replace(
        task.attempts[-1],
        status=attempt_status,
        finished_at=at,
        error=error,
        result_fingerprint=result_fingerprint,
        invocation_record_ids=invocation_record_ids,
    )
    return replace(
        task,
        status=status,
        attempts=(*task.attempts[:-1], closed),
        updated_at=at,
        result_fingerprint=result_fingerprint,
        next_retry_at=next_retry_at,
    )


def start_task(task, *, attempt_id: str, at: str) -> RoundTranslationTask:
    _check(task, {RoundTaskStatus.PENDING, RoundTaskStatus.RETRY_WAIT}, at)
    if task.next_retry_at is not None and at < task.next_retry_at:
        _invalid()
    attempt = RoundTaskAttempt(
        attempt_id,
        len(task.attempts) + 1,
        task.input_fingerprint,
        task.configuration_snapshot_id,
        RoundAttemptStatus.RUNNING,
        at,
        None,
        (),
        None,
        None,
    )
    return replace(
        task,
        status=RoundTaskStatus.RUNNING,
        attempts=(*task.attempts, attempt),
        next_retry_at=None,
        updated_at=at,
    )


def succeed_task(
    task,
    *,
    at: str,
    result_fingerprint: str,
    invocation_record_ids: tuple[str, ...] = (),
) -> RoundTranslationTask:
    _check(task, {RoundTaskStatus.RUNNING}, at)
    return _finish(
        task,
        at=at,
        status=RoundTaskStatus.SUCCEEDED,
        attempt_status=RoundAttemptStatus.SUCCEEDED,
        result_fingerprint=result_fingerprint,
        invocation_record_ids=invocation_record_ids,
    )


def retry_delay_us(
    completed_attempt_count: int, error: RoundTaskError, policy: RetryPolicy
) -> int:
    require_int(
        completed_attempt_count, "completed_attempt_count", minimum=1, maximum=MAX_COUNT
    )
    if (
        not isinstance(error, RoundTaskError)
        or not error.retryable
        or not isinstance(policy, RetryPolicy)
    ):
        _invalid()
    # Once this exponent saturates the cap, larger input counts are equivalent.
    exponent = min(completed_attempt_count - 1, policy.max_delay_us.bit_length())
    exponential = min(policy.base_delay_us * (1 << exponent), policy.max_delay_us)
    return max(exponential, error.retry_after_us or 0)


def retry_task(
    task,
    *,
    at: str,
    error: RoundTaskError,
    policy: RetryPolicy,
    invocation_record_ids: tuple[str, ...] = (),
) -> RoundTranslationTask:
    _check(task, {RoundTaskStatus.RUNNING}, at)
    if (
        not isinstance(error, RoundTaskError)
        or not error.retryable
        or not isinstance(policy, RetryPolicy)
    ):
        _invalid()
    count = sum(
        (a.input_fingerprint, a.configuration_snapshot_id)
        == (task.input_fingerprint, task.configuration_snapshot_id)
        for a in task.attempts
    )
    if count >= policy.max_attempts:
        return _finish(
            task,
            at=at,
            status=RoundTaskStatus.FAILED,
            attempt_status=RoundAttemptStatus.EXHAUSTED,
            error=error,
            invocation_record_ids=invocation_record_ids,
        )
    delay = retry_delay_us(count, error, policy)
    try:
        deadline = datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(
            microseconds=delay
        )
    except (ValueError, OverflowError) as exc:
        raise DomainSchemaError(
            "domain_field_invalid",
            "重试时间超出范围。",
            "请修正任务时间。",
            "round_task.next_retry_at",
        ) from exc
    # isoformat pads early years portably; timestamps always remain UTC.
    next_retry_at = deadline.isoformat(timespec="microseconds") + "Z"
    return _finish(
        task,
        at=at,
        status=RoundTaskStatus.RETRY_WAIT,
        attempt_status=RoundAttemptStatus.RETRYABLE_FAILED,
        error=error,
        invocation_record_ids=invocation_record_ids,
        next_retry_at=next_retry_at,
    )


def fail_task(
    task, *, at: str, error: RoundTaskError, invocation_record_ids: tuple[str, ...] = ()
) -> RoundTranslationTask:
    _check(task, {RoundTaskStatus.RUNNING}, at)
    if not isinstance(error, RoundTaskError) or error.retryable:
        _invalid()
    return _finish(
        task,
        at=at,
        status=RoundTaskStatus.FAILED,
        attempt_status=RoundAttemptStatus.FAILED,
        error=error,
        invocation_record_ids=invocation_record_ids,
    )


def cancel_task(task, *, at: str) -> RoundTranslationTask:
    _check(task, {RoundTaskStatus.RUNNING, RoundTaskStatus.RETRY_WAIT}, at)
    if task.status is RoundTaskStatus.RETRY_WAIT:
        return replace(
            task, status=RoundTaskStatus.CANCELLED, next_retry_at=None, updated_at=at
        )
    return _finish(
        task,
        at=at,
        status=RoundTaskStatus.CANCELLED,
        attempt_status=RoundAttemptStatus.CANCELLED,
        invocation_record_ids=task.attempts[-1].invocation_record_ids,
    )


def interrupt_task(task, *, at: str) -> RoundTranslationTask:
    if (
        isinstance(task, RoundTranslationTask)
        and task.status is RoundTaskStatus.INTERRUPTED
    ):
        require_canonical_utc_timestamp(at, "round_task.updated_at")
        if at < task.updated_at:
            _invalid()
        return task
    _check(task, {RoundTaskStatus.RUNNING}, at)
    return _finish(
        task,
        at=at,
        status=RoundTaskStatus.INTERRUPTED,
        attempt_status=RoundAttemptStatus.INTERRUPTED,
        invocation_record_ids=task.attempts[-1].invocation_record_ids,
    )


def reset_task(task, *, at: str) -> RoundTranslationTask:
    _check(
        task,
        {
            RoundTaskStatus.FAILED,
            RoundTaskStatus.CANCELLED,
            RoundTaskStatus.INTERRUPTED,
        },
        at,
    )
    return replace(
        task,
        status=RoundTaskStatus.PENDING,
        result_fingerprint=None,
        next_retry_at=None,
        updated_at=at,
    )


def supersede_task(task, *, spec: RoundTaskSpec, at: str) -> RoundTranslationTask:
    """Active work must be cancelled/interrupted before changing its input."""
    _check(task, set(RoundTaskStatus) - {RoundTaskStatus.RUNNING}, at)
    if not isinstance(spec, RoundTaskSpec) or (task.task_id, task.round_id) != (
        spec.task_id,
        spec.round_id,
    ):
        _invalid()
    if (task.input_fingerprint, task.configuration_snapshot_id) == (
        spec.input_fingerprint,
        spec.configuration_snapshot_id,
    ):
        _invalid()
    return replace(
        task,
        status=RoundTaskStatus.PENDING,
        input_fingerprint=spec.input_fingerprint,
        configuration_snapshot_id=spec.configuration_snapshot_id,
        result_fingerprint=None,
        next_retry_at=None,
        updated_at=at,
    )
