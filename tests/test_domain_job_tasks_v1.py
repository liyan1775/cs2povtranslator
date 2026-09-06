from dataclasses import FrozenInstanceError, replace

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.job_tasks import (
    RetryPolicy,
    RoundAttemptStatus,
    RoundTaskAttempt,
    RoundTaskError,
    RoundTaskSpec,
    RoundTaskStatus,
    RoundTranslationTask,
)
from cs2pov.domain.schema import require_canonical_utc_timestamp

T0 = "2026-09-05T00:00:00.000000Z"
T1 = "2026-09-05T00:00:01.000000Z"
T2 = "2026-09-05T00:00:02.000000Z"
T3 = "2026-09-05T00:00:03.000000Z"


def pending():
    return RoundTranslationTask.pending(
        task_id="round-001",
        round_id="round-001",
        input_fingerprint="1" * 64,
        configuration_snapshot_id="cfg",
        updated_at=T0,
    )


def error(retryable=True):
    return RoundTaskError(
        "provider_busy",
        "服务繁忙。",
        "本回合尚未完成。",
        "请稍后重试。",
        retryable,
        1_000_000 if retryable else None,
    )


def attempt(status=RoundAttemptStatus.RUNNING, **overrides):
    closed = status is not RoundAttemptStatus.RUNNING
    values = dict(
        attempt_id="attempt-1",
        attempt_number=1,
        input_fingerprint="1" * 64,
        configuration_snapshot_id="cfg",
        status=status,
        started_at=T1,
        finished_at=T2 if closed else None,
        invocation_record_ids=(),
        result_fingerprint="9" * 64 if status is RoundAttemptStatus.SUCCEEDED else None,
        error=error(status is not RoundAttemptStatus.FAILED)
        if status
        in {
            RoundAttemptStatus.FAILED,
            RoundAttemptStatus.EXHAUSTED,
            RoundAttemptStatus.RETRYABLE_FAILED,
        }
        else None,
    )
    values.update(overrides)
    return RoundTaskAttempt(**values)


def test_pending_round_task_has_exact_v1_wire_contract_and_fingerprint():
    task = pending()
    assert task.to_dict() == {
        "schema_version": 1,
        "task_id": "round-001",
        "round_id": "round-001",
        "status": "pending",
        "input_fingerprint": "1" * 64,
        "configuration_snapshot_id": "cfg",
        "result_fingerprint": None,
        "attempts": [],
        "next_retry_at": None,
        "updated_at": T0,
    }
    assert RoundTranslationTask.from_dict(task.to_dict()) == task
    assert task.content_fingerprint() == content_fingerprint(task.to_dict())
    with pytest.raises(FrozenInstanceError):
        task.status = RoundTaskStatus.RUNNING


@pytest.mark.parametrize(
    "factory",
    [
        pending,
        error,
        attempt,
        lambda: RoundTaskSpec("round-001", "round-001", "1" * 64, "cfg"),
        lambda: RetryPolicy(3, 1, 100),
    ],
)
def test_each_contract_round_trips_and_rejects_missing_unknown_keys(factory):
    value = factory()
    wire = value.to_dict()
    assert type(value).from_dict(wire) == value
    for key in wire:
        broken = dict(wire)
        del broken[key]
        with pytest.raises(DomainSchemaError):
            type(value).from_dict(broken)
    with pytest.raises(DomainSchemaError):
        type(value).from_dict(dict(wire, unknown="x"))
    with pytest.raises(DomainSchemaError):
        type(value).from_dict(dict(wire, password="hidden"))


@pytest.mark.parametrize("version", [None, True, 0, 2, "1"])
def test_task_requires_current_integer_schema(version):
    wire = pending().to_dict()
    wire["schema_version"] = version
    with pytest.raises(DomainSchemaError) as caught:
        RoundTranslationTask.from_dict(wire)
    assert caught.value.code == "domain_schema_unsupported"


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "other"),
        ("round_id", "../outside"),
        ("task_id", "CON"),
        ("input_fingerprint", "A" * 64),
        ("configuration_snapshot_id", "bad/path"),
        ("status", "pending"),
        ("attempts", {}),
        ("attempts", "bad"),
        ("result_fingerprint", "2" * 64),
        ("next_retry_at", T1),
        ("updated_at", "2026-09-05T00:00:00Z"),
    ],
)
def test_pending_rejects_invalid_direct_values(field, value):
    with pytest.raises(DomainSchemaError):
        replace(pending(), **{field: value})


@pytest.mark.parametrize(
    "timestamp",
    [
        "",
        None,
        0,
        "2026-02-30T00:00:00.000000Z",
        "2026-09-05T00:00:00Z",
        "2026-09-05T00:00:00.000000+00:00",
        T0 + " ",
    ],
)
def test_canonical_timestamp_rejects_noncanonical_values(timestamp):
    with pytest.raises(DomainSchemaError) as caught:
        require_canonical_utc_timestamp(timestamp, "clock")
    assert caught.value.code == "domain_field_invalid"
    assert caught.value.path == "clock"


@pytest.mark.parametrize("timestamp", [T0, "0001-01-01T00:00:00.000000Z"])
def test_timestamp_preserves_canonical_bytes(timestamp):
    assert require_canonical_utc_timestamp(timestamp, "clock") == timestamp


@pytest.mark.parametrize("status", list(RoundAttemptStatus))
def test_attempt_status_shapes_round_trip(status):
    value = attempt(status)
    assert RoundTaskAttempt.from_dict(value.to_dict()) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_number", True),
        ("attempt_number", 0),
        ("attempt_id", "bad/path"),
        ("finished_at", T0),
        ("finished_at", T1),
        ("status", "running"),
        ("invocation_record_ids", "call"),
        ("invocation_record_ids", ["x", "x"]),
    ],
)
def test_attempt_rejects_invalid_fields(field, value):
    with pytest.raises(DomainSchemaError):
        replace(attempt(), **{field: value})


def test_attempt_rejects_contradictory_outcomes():
    with pytest.raises(DomainSchemaError):
        replace(attempt(), error=error())
    with pytest.raises(DomainSchemaError):
        replace(attempt(RoundAttemptStatus.SUCCEEDED), result_fingerprint=None)
    with pytest.raises(DomainSchemaError):
        replace(attempt(RoundAttemptStatus.FAILED), error=error(True))
    with pytest.raises(DomainSchemaError):
        replace(attempt(RoundAttemptStatus.EXHAUSTED), error=error(False))
    with pytest.raises(DomainSchemaError):
        replace(attempt(RoundAttemptStatus.CANCELLED), result_fingerprint="9" * 64)


@pytest.mark.parametrize(
    "status,attempt_status",
    [
        (RoundTaskStatus.RUNNING, RoundAttemptStatus.RUNNING),
        (RoundTaskStatus.SUCCEEDED, RoundAttemptStatus.SUCCEEDED),
        (RoundTaskStatus.FAILED, RoundAttemptStatus.FAILED),
        (RoundTaskStatus.FAILED, RoundAttemptStatus.EXHAUSTED),
        (RoundTaskStatus.CANCELLED, RoundAttemptStatus.CANCELLED),
        (RoundTaskStatus.CANCELLED, RoundAttemptStatus.RETRYABLE_FAILED),
        (RoundTaskStatus.INTERRUPTED, RoundAttemptStatus.INTERRUPTED),
        (RoundTaskStatus.RETRY_WAIT, RoundAttemptStatus.RETRYABLE_FAILED),
    ],
)
def test_task_status_is_self_verifiable_without_runtime_policy(status, attempt_status):
    value = replace(
        pending(),
        status=status,
        attempts=(attempt(attempt_status),),
        updated_at=T2,
        result_fingerprint="9" * 64 if status is RoundTaskStatus.SUCCEEDED else None,
        next_retry_at=T3 if status is RoundTaskStatus.RETRY_WAIT else None,
    )
    assert RoundTranslationTask.from_dict(value.to_dict()) == value
    with pytest.raises(DomainSchemaError):
        replace(value, attempts=())
    with pytest.raises(DomainSchemaError):
        replace(value, input_fingerprint="2" * 64)


def test_pending_preserves_closed_history_across_input_generations():
    history = attempt(RoundAttemptStatus.SUCCEEDED)
    value = replace(
        pending(), input_fingerprint="2" * 64, attempts=[history], updated_at=T3
    )
    assert value.attempts == (history,)
    assert RoundTranslationTask.from_dict(value.to_dict()) == value
    with pytest.raises(DomainSchemaError):
        replace(value, attempts=(attempt(),))


def test_task_rejects_noncontiguous_duplicate_or_overlapping_attempt_history():
    first = attempt(RoundAttemptStatus.FAILED)
    second = attempt(
        RoundAttemptStatus.SUCCEEDED,
        attempt_id="attempt-2",
        attempt_number=2,
        started_at=T3,
        finished_at="2026-09-05T00:00:04.000000Z",
    )
    valid = replace(pending(), attempts=(first, second), updated_at=second.finished_at)
    assert len(valid.attempts) == 2
    for invalid_second in [
        replace(second, attempt_number=3),
        replace(second, attempt_id=first.attempt_id),
        replace(second, started_at=T1),
    ]:
        with pytest.raises(DomainSchemaError):
            replace(valid, attempts=(first, invalid_second))
    with pytest.raises(DomainSchemaError):
        replace(valid, updated_at=T1)


def test_success_and_retry_deadline_must_match_current_attempt():
    succeeded = replace(
        pending(),
        status=RoundTaskStatus.SUCCEEDED,
        attempts=(attempt(RoundAttemptStatus.SUCCEEDED),),
        result_fingerprint="9" * 64,
        updated_at=T2,
    )
    with pytest.raises(DomainSchemaError):
        replace(succeeded, result_fingerprint="8" * 64)
    with pytest.raises(DomainSchemaError):
        replace(
            pending(),
            status=RoundTaskStatus.RETRY_WAIT,
            attempts=(attempt(RoundAttemptStatus.RETRYABLE_FAILED),),
            updated_at=T2,
            next_retry_at=T2,
        )


@pytest.mark.parametrize(
    "args",
    [
        (True, 1, 10),
        (0, 1, 10),
        (101, 1, 10),
        (3, 0, 10),
        (3, 11, 10),
        (3, 1, 86_400_000_001),
    ],
)
def test_retry_policy_bounds(args):
    with pytest.raises(DomainSchemaError):
        RetryPolicy(*args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("retryable", 1),
        ("retry_after_us", True),
        ("retry_after_us", -1),
        ("retry_after_us", 86_400_000_001),
        ("code", "../error"),
        ("message_zh", " "),
        ("impact_zh", ""),
        ("suggestion_zh", "请\n重试"),
        ("message_zh", "请检查 C:/private/input 文件。"),
    ],
)
def test_error_rejects_unsafe_or_invalid_durable_values(field, value):
    with pytest.raises(DomainSchemaError):
        replace(error(), **{field: value})


@pytest.mark.parametrize("field", ["message_zh", "impact_zh", "suggestion_zh"])
@pytest.mark.parametrize(
    "value",
    [
        "读取失败：/home/example/input.wav",
        "读取/home/example/input.wav失败。",
        "读取失败（/home/example/input.wav）。",
        "玩家76561198000000001的转录失败。",
    ],
)
@pytest.mark.parametrize("entry", ["constructor", "from_dict", "failed_task"])
def test_error_rejects_private_values_adjacent_to_chinese(field, value, entry):
    wire = error(False).to_dict()
    wire[field] = value
    if entry == "failed_task":
        task = replace(
            pending(),
            status=RoundTaskStatus.FAILED,
            attempts=(attempt(RoundAttemptStatus.FAILED),),
            updated_at=T2,
        )
        assert RoundTranslationTask.from_dict(task.to_dict()) == task
        task_wire = task.to_dict()
        task_wire["attempts"][0]["error"] = wire

    with pytest.raises(DomainSchemaError) as caught:
        if entry == "constructor":
            RoundTaskError(**wire)
        elif entry == "from_dict":
            RoundTaskError.from_dict(wire)
        else:
            RoundTranslationTask.from_dict(task_wire)
    assert caught.value.code == "domain_field_invalid"
    assert caught.value.path == field


@pytest.mark.parametrize("field", ["message_zh", "impact_zh", "suggestion_zh"])
@pytest.mark.parametrize(
    "value",
    ["本回合失败，请稍后重试。", "计数1234567890123456。", "计数123456789012345678。"],
)
def test_error_preserves_safe_text_and_other_digit_lengths(field, value):
    diagnostic = replace(error(), **{field: value})
    assert diagnostic.to_dict()[field] == value
    assert RoundTaskError.from_dict(diagnostic.to_dict()) == diagnostic
