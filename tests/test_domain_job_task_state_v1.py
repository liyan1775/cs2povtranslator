from dataclasses import replace

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job_tasks import (
    RetryPolicy,
    RoundAttemptStatus,
    RoundTaskError,
    RoundTaskSpec,
    RoundTaskStatus,
    RoundTranslationTask,
)
from cs2pov.domain.job_task_state import (
    cancel_task,
    fail_task,
    interrupt_task,
    reset_task,
    retry_delay_us,
    retry_task,
    start_task,
    succeed_task,
    supersede_task,
)


def ts(second):
    return f"2026-09-05T00:00:{second:02}.000000Z"


def pending():
    return RoundTranslationTask.pending(
        task_id="round-001",
        round_id="round-001",
        input_fingerprint="1" * 64,
        configuration_snapshot_id="cfg",
        updated_at=ts(0),
    )


def busy(delay=None):
    return RoundTaskError(
        "provider_busy", "服务繁忙。", "本回合未完成。", "稍后重试。", True, delay
    )


def failure():
    return RoundTaskError(
        "provider_failed", "服务异常。", "本回合失败。", "检查配置。", False, None
    )


def test_real_retry_history_round_trip_and_earliest_restart():
    initial = pending()
    running = start_task(initial, attempt_id="try-1", at=ts(1))
    waiting = retry_task(
        running,
        at=ts(2),
        error=busy(2_000_000),
        policy=RetryPolicy(3, 1_000_000, 8_000_000),
        invocation_record_ids=("call-1",),
    )
    assert waiting.next_retry_at == ts(4)
    with pytest.raises(DomainSchemaError):
        start_task(waiting, attempt_id="try-2", at="2026-09-05T00:00:03.999999Z")
    restarted = start_task(waiting, attempt_id="try-2", at=ts(4))
    succeeded = succeed_task(
        restarted,
        at=ts(5),
        result_fingerprint="9" * 64,
        invocation_record_ids=("call-2",),
    )
    assert succeeded.status is RoundTaskStatus.SUCCEEDED
    assert [a.attempt_number for a in succeeded.attempts] == [1, 2]
    assert [a.invocation_record_ids for a in succeeded.attempts] == [
        ("call-1",),
        ("call-2",),
    ]
    assert initial.status is RoundTaskStatus.PENDING and initial.attempts == ()
    assert RoundTranslationTask.from_dict(succeeded.to_dict()) == succeeded


def test_exhaustion_is_durable_and_never_creates_extra_attempt():
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    exhausted = retry_task(
        running, at=ts(2), error=busy(), policy=RetryPolicy(1, 1, 10)
    )
    assert exhausted.status is RoundTaskStatus.FAILED
    assert exhausted.attempts[-1].status is RoundAttemptStatus.EXHAUSTED
    assert exhausted.attempts[-1].error.retryable
    assert exhausted.next_retry_at is None and len(exhausted.attempts) == 1
    with pytest.raises(DomainSchemaError):
        start_task(exhausted, attempt_id="try-2", at=ts(3))


def test_minimum_retry_wait_and_checked_timestamp_overflow():
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    waiting = retry_task(running, at=ts(2), error=busy(0), policy=RetryPolicy(2, 1, 1))
    assert waiting.next_retry_at == "2026-09-05T00:00:02.000001Z"
    with pytest.raises(DomainSchemaError):
        retry_task(
            running,
            at="9999-12-31T23:59:59.999999Z",
            error=busy(),
            policy=RetryPolicy(2, 1, 1),
        )


@pytest.mark.parametrize(
    "count,delay,expected",
    [
        (1, None, 10),
        (2, None, 20),
        (3, None, 40),
        (4, None, 40),
        (2_147_483_647, None, 40),
        (1, 100, 100),
    ],
)
def test_retry_delay_obeys_exponential_cap_and_server_minimum(count, delay, expected):
    assert retry_delay_us(count, busy(delay), RetryPolicy(3, 10, 40)) == expected


@pytest.mark.parametrize("count", [True, 0, -1, "1", 2_147_483_648])
def test_retry_delay_rejects_invalid_counts(count):
    with pytest.raises(DomainSchemaError):
        retry_delay_us(count, busy(), RetryPolicy(3, 1, 10))


def test_cancel_wait_retains_closed_attempt_and_reset_retains_history():
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    waiting = retry_task(running, at=ts(2), error=busy(), policy=RetryPolicy(3, 1, 10))
    cancelled = cancel_task(waiting, at=ts(3))
    assert cancelled.status is RoundTaskStatus.CANCELLED
    assert cancelled.attempts == waiting.attempts and cancelled.next_retry_at is None
    reset = reset_task(cancelled, at=ts(4))
    next_run = start_task(reset, attempt_id="try-2", at=ts(5))
    assert next_run.attempts[-1].attempt_number == 2
    assert next_run.attempts[0] == waiting.attempts[0]


def test_cancel_active_work_and_recover_interruption():
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    assert (
        cancel_task(running, at=ts(2)).attempts[-1].status
        is RoundAttemptStatus.CANCELLED
    )
    interrupted = interrupt_task(running, at=ts(2))
    assert interrupted.attempts[-1].status is RoundAttemptStatus.INTERRUPTED
    assert interrupt_task(interrupted, at=ts(2)) == interrupted
    recovered = start_task(
        reset_task(interrupted, at=ts(3)), attempt_id="try-2", at=ts(4)
    )
    assert recovered.attempts[0] == interrupted.attempts[0]


def test_empty_round_succeeds_without_fabricating_model_calls():
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    succeeded = succeed_task(running, at=ts(2), result_fingerprint="9" * 64)
    assert succeeded.attempts[0].invocation_record_ids == ()


@pytest.mark.parametrize(
    "supplied,expected",
    [
        ((), ("call-1", "call-2")),
        (("call-2", "call-3"), ("call-1", "call-2", "call-3")),
    ],
)
@pytest.mark.parametrize("finish", ["succeed", "retry", "fail"])
def test_finish_preserves_prior_invocation_refs_and_appends_new_refs(
    finish, supplied, expected
):
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    running = replace(
        running,
        attempts=(
            replace(
                running.attempts[-1],
                invocation_record_ids=("call-1", "call-2"),
            ),
        ),
    )

    if finish == "succeed":
        completed = succeed_task(
            running,
            at=ts(2),
            result_fingerprint="9" * 64,
            invocation_record_ids=supplied,
        )
    elif finish == "retry":
        completed = retry_task(
            running,
            at=ts(2),
            error=busy(),
            policy=RetryPolicy(3, 1, 10),
            invocation_record_ids=supplied,
        )
    else:
        completed = fail_task(
            running,
            at=ts(2),
            error=failure(),
            invocation_record_ids=supplied,
        )

    assert completed.attempts[-1].invocation_record_ids == expected


@pytest.mark.parametrize("finish", ["succeed", "retry", "fail"])
def test_finish_rejects_duplicate_supplied_invocation_refs(finish):
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    duplicate_ids = ("call-1", "call-1")

    with pytest.raises(DomainSchemaError):
        if finish == "succeed":
            succeed_task(
                running,
                at=ts(2),
                result_fingerprint="9" * 64,
                invocation_record_ids=duplicate_ids,
            )
        elif finish == "retry":
            retry_task(
                running,
                at=ts(2),
                error=busy(),
                policy=RetryPolicy(3, 1, 10),
                invocation_record_ids=duplicate_ids,
            )
        else:
            fail_task(
                running,
                at=ts(2),
                error=failure(),
                invocation_record_ids=duplicate_ids,
            )


def test_failure_retains_real_calls_and_superseding_resets_current_retry_budget():
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    failed = fail_task(
        running, at=ts(2), error=failure(), invocation_record_ids=("call-1",)
    )
    spec = RoundTaskSpec("round-001", "round-001", "2" * 64, "cfg")
    changed = supersede_task(failed, spec=spec, at=ts(3))
    assert changed.attempts == failed.attempts
    new_running = start_task(changed, attempt_id="try-2", at=ts(4))
    waiting = retry_task(
        new_running, at=ts(5), error=busy(), policy=RetryPolicy(2, 1, 2)
    )
    assert waiting.status is RoundTaskStatus.RETRY_WAIT
    assert waiting.attempts[-1].attempt_number == 2


def states():
    p = pending()
    r = start_task(p, attempt_id="try-1", at=ts(1))
    return [
        p,
        r,
        retry_task(r, at=ts(2), error=busy(), policy=RetryPolicy(3, 1, 10)),
        succeed_task(r, at=ts(2), result_fingerprint="9" * 64),
        fail_task(r, at=ts(2), error=failure()),
        cancel_task(r, at=ts(2)),
        interrupt_task(r, at=ts(2)),
    ]


@pytest.mark.parametrize(
    "operation,allowed",
    [
        (
            lambda t: start_task(t, attempt_id="try-2", at=ts(5)),
            {"pending", "retry_wait"},
        ),
        (lambda t: succeed_task(t, at=ts(5), result_fingerprint="9" * 64), {"running"}),
        (
            lambda t: retry_task(
                t, at=ts(5), error=busy(), policy=RetryPolicy(3, 1, 10)
            ),
            {"running"},
        ),
        (lambda t: fail_task(t, at=ts(5), error=failure()), {"running"}),
        (lambda t: cancel_task(t, at=ts(5)), {"running", "retry_wait"}),
        (lambda t: interrupt_task(t, at=ts(5)), {"running", "interrupted"}),
        (lambda t: reset_task(t, at=ts(5)), {"failed", "cancelled", "interrupted"}),
    ],
)
def test_complete_source_state_matrix(operation, allowed):
    for task in states():
        if task.status.value in allowed:
            result = operation(task)
            assert RoundTranslationTask.from_dict(result.to_dict()) == result
        else:
            with pytest.raises(DomainSchemaError) as caught:
                operation(task)
            assert caught.value.code == "domain_state_transition_invalid"
            assert caught.value.path == "round_task.status"


def test_invalid_transition_arguments_are_rejected_without_mutation():
    running = start_task(pending(), attempt_id="try-1", at=ts(1))
    with pytest.raises(DomainSchemaError):
        succeed_task(running, at=ts(1), result_fingerprint="9" * 64)
    with pytest.raises(DomainSchemaError):
        retry_task(running, at=ts(2), error=failure(), policy=RetryPolicy(3, 1, 10))
    with pytest.raises(DomainSchemaError):
        fail_task(running, at=ts(2), error=busy())
    same = RoundTaskSpec("round-001", "round-001", "1" * 64, "cfg")
    with pytest.raises(DomainSchemaError):
        supersede_task(pending(), spec=same, at=ts(2))
    with pytest.raises(DomainSchemaError):
        supersede_task(
            pending(),
            spec=replace(same, task_id="round-002", round_id="round-002"),
            at=ts(2),
        )
    with pytest.raises(DomainSchemaError):
        supersede_task(
            running, spec=replace(same, input_fingerprint="2" * 64), at=ts(2)
        )
