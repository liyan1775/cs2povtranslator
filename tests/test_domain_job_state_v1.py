from dataclasses import FrozenInstanceError, replace
from itertools import combinations, product

import pytest

from cs2pov.domain import job_state
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job import (
    FinalArtifactEntry,
    FinalArtifactKind,
    JobManifest,
    JobPhase as P,
    JobRunStatus as R,
    RoundProgressSummary,
)
from cs2pov.domain.job_state import (
    advance_job_phase,
    derive_round_progress,
    derive_translation_run_status,
    is_legal_terminal,
)
from cs2pov.domain.job_tasks import (
    RoundAttemptStatus as A,
    RoundTaskAttempt,
    RoundTaskError,
    RoundTaskStatus as T,
    RoundTranslationTask,
)


TS_0 = "2026-09-03T01:02:00.000000Z"
TS_1 = "2026-09-03T01:02:01.000000Z"
TS_2 = "2026-09-03T01:02:02.000000Z"
TS_3 = "2026-09-03T01:02:03.000000Z"

# Independent specification oracle: all 19 x 19 phase pairs are checked below.
APPROVED_EDGES = frozenset({
    (P.CREATED, P.TIMELINE_READY),
    (P.TIMELINE_READY, P.VOICE_READY),
    (P.VOICE_READY, P.TRANSCRIBED),
    (P.TRANSCRIBED, P.CONTEXT_READY),
    (P.CONTEXT_READY, P.UNDERSTANDING_TRANSLATING),
    (P.UNDERSTANDING_TRANSLATING, P.UNDERSTOOD_TRANSLATED),
    (P.UNDERSTOOD_TRANSLATED, P.DRAFT_TIMELINE_READY),
    (P.DRAFT_TIMELINE_READY, P.COMPLETED_DRAFT),
    (P.DRAFT_TIMELINE_READY, P.REVIEW_PENDING),
    (P.REVIEW_PENDING, P.REVIEWED),
    (P.REVIEWED, P.FINAL_TIMELINE_READY),
    (P.FINAL_TIMELINE_READY, P.SUBTITLES_EXPORTED),
    (P.SUBTITLES_EXPORTED, P.GREEN_SCREEN_RENDERED),
    (P.GREEN_SCREEN_RENDERED, P.COMPLETED_WITHOUT_VIDEO),
    (P.GREEN_SCREEN_RENDERED, P.READY_FOR_RENDER),
    (P.READY_FOR_RENDER, P.RENDERING),
    (P.RENDERING, P.VIDEO_READY),
    (P.VIDEO_READY, P.COMPLETED_WITH_VIDEO),
})
DEFAULT_STATUSES = {
    P.CREATED: R.PENDING,
    P.TIMELINE_READY: R.SUCCEEDED,
    P.VOICE_READY: R.SUCCEEDED,
    P.TRANSCRIBED: R.SUCCEEDED,
    P.CONTEXT_READY: R.SUCCEEDED,
    P.UNDERSTANDING_TRANSLATING: R.RUNNING,
    P.UNDERSTOOD_TRANSLATED: R.SUCCEEDED,
    P.DRAFT_TIMELINE_READY: R.SUCCEEDED,
    P.COMPLETED_DRAFT: R.SUCCEEDED,
    P.REVIEW_PENDING: R.PENDING,
    P.REVIEWED: R.SUCCEEDED,
    P.FINAL_TIMELINE_READY: R.SUCCEEDED,
    P.SUBTITLES_EXPORTED: R.SUCCEEDED,
    P.GREEN_SCREEN_RENDERED: R.SUCCEEDED,
    P.COMPLETED_WITHOUT_VIDEO: R.SUCCEEDED,
    P.READY_FOR_RENDER: R.PENDING,
    P.RENDERING: R.RUNNING,
    P.VIDEO_READY: R.SUCCEEDED,
    P.COMPLETED_WITH_VIDEO: R.SUCCEEDED,
}


def manifest(phase=P.CREATED, *, review_id="review-001", status=R.PENDING):
    return JobManifest(
        job_id="job-001", display_name="测试任务", created_at=TS_0,
        updated_at=TS_1, demo_asset_id="a" * 64, demo_display_name="match.dem",
        map_name=None, target_player_id=None, phase=phase, run_status=status,
        round_progress=RoundProgressSummary(3, 1, 1, 1),
        configuration_snapshot_ids=("snapshot-001", "snapshot-002"),
        active_review_id=review_id,
        final_artifacts=(FinalArtifactEntry(
            "artifact-001", FinalArtifactKind.TIMELINE,
            "final/timelines/round-001.json", "b" * 64, "round-001", None,
        ),),
    )


def task(status, number=1, *, attempt_status=None):
    """Construct validated Task 1 values without depending on Task 2 transitions."""
    identity = f"round-{number:03d}"
    if status is T.PENDING:
        return RoundTranslationTask.pending(
            task_id=identity, round_id=identity, input_fingerprint="1" * 64,
            configuration_snapshot_id="snapshot-001", updated_at=TS_1,
        )
    final_status = attempt_status or {
        T.RUNNING: A.RUNNING, T.RETRY_WAIT: A.RETRYABLE_FAILED,
        T.SUCCEEDED: A.SUCCEEDED, T.FAILED: A.FAILED,
        T.CANCELLED: A.CANCELLED, T.INTERRUPTED: A.INTERRUPTED,
    }[status]
    error = None
    if final_status in {A.RETRYABLE_FAILED, A.EXHAUSTED, A.FAILED}:
        error = RoundTaskError(
            "translation_failed", "回合处理失败。", "本回合尚未完成。",
            "请稍后重试。", final_status is not A.FAILED, None,
        )
    result = "9" * 64 if status is T.SUCCEEDED else None
    attempt = RoundTaskAttempt(
        attempt_id=f"attempt-{number:03d}", attempt_number=1,
        input_fingerprint="1" * 64, configuration_snapshot_id="snapshot-001",
        status=final_status, started_at=TS_0,
        finished_at=None if status is T.RUNNING else TS_1,
        invocation_record_ids=(), result_fingerprint=result, error=error,
    )
    return RoundTranslationTask(
        identity, identity, status, "1" * 64, "snapshot-001", result,
        (attempt,), TS_3 if status is T.RETRY_WAIT else None, TS_2,
    )


def assert_error(exc, code, path):
    assert exc.value.code == code
    assert exc.value.path == path
    assert exc.value.message
    assert exc.value.action


@pytest.mark.parametrize("source,target", product(P, repeat=2))
def test_exact_forward_graph(source, target):
    before = manifest(source)
    snapshot = before.to_dict()
    if (source, target) not in APPROVED_EDGES:
        with pytest.raises(DomainSchemaError) as exc:
            advance_job_phase(before, target, at=TS_2)
        assert_error(exc, "domain_state_transition_invalid", "job.phase")
    else:
        after = advance_job_phase(before, target, at=TS_2)
        assert after is not before
        assert after == replace(
            before, phase=target, run_status=DEFAULT_STATUSES[target], updated_at=TS_2,
        )
        assert JobManifest.from_dict(after.to_dict()) == after
    assert before.to_dict() == snapshot


@pytest.mark.parametrize("source,target", sorted(APPROVED_EDGES))
@pytest.mark.parametrize("status", R)
def test_phase_defaults_replace_every_previous_run_outcome(source, target, status):
    after = advance_job_phase(manifest(source, status=status), target, at=TS_2)
    assert after.run_status is DEFAULT_STATUSES[target]


def test_graph_and_default_status_mapping_are_deeply_immutable():
    assert dict(job_state._DEFAULT_RUN_STATUS) == DEFAULT_STATUSES
    assert set(job_state._FORWARD_PHASES) == set(P)
    assert {
        (source, target)
        for source, targets in job_state._FORWARD_PHASES.items()
        for target in targets
    } == APPROVED_EDGES
    with pytest.raises(TypeError):
        job_state._DEFAULT_RUN_STATUS[P.CREATED] = R.SUCCEEDED
    with pytest.raises(TypeError):
        job_state._FORWARD_PHASES[P.CREATED] = frozenset()
    assert all(isinstance(targets, frozenset) for targets in job_state._FORWARD_PHASES.values())
    before = manifest()
    after = advance_job_phase(before, P.TIMELINE_READY, at=TS_2)
    with pytest.raises(FrozenInstanceError):
        after.phase = P.COMPLETED_WITH_VIDEO


@pytest.mark.parametrize("source", P)
@pytest.mark.parametrize("target", [P.REVIEWED, P.FINAL_TIMELINE_READY])
def test_no_phase_can_promote_to_reviewed_output_without_active_review(source, target):
    before = manifest(source, review_id=None)
    with pytest.raises(DomainSchemaError) as exc:
        advance_job_phase(before, target, at=TS_2)
    path = "job.active_review_id" if (source, target) in APPROVED_EDGES else "job.phase"
    assert_error(exc, "domain_state_transition_invalid", path)
    assert before.active_review_id is None


def test_draft_terminal_and_review_pending_require_no_review():
    before = manifest(P.DRAFT_TIMELINE_READY, review_id=None)
    draft = advance_job_phase(before, P.COMPLETED_DRAFT, at=TS_2)
    pending = advance_job_phase(before, P.REVIEW_PENDING, at=TS_2)
    assert draft.active_review_id is pending.active_review_id is None
    assert draft.run_status is R.SUCCEEDED
    assert pending.run_status is R.PENDING
    with pytest.raises(DomainSchemaError):
        advance_job_phase(draft, P.REVIEWED, at=TS_3)


@pytest.mark.parametrize("phase", P)
def test_exact_terminal_phases(phase):
    assert is_legal_terminal(phase) is (phase in {
        P.COMPLETED_DRAFT, P.COMPLETED_WITHOUT_VIDEO, P.COMPLETED_WITH_VIDEO,
    })


def test_without_video_terminal_and_render_handoff_use_only_domain_values():
    before = manifest(P.GREEN_SCREEN_RENDERED)
    completed = advance_job_phase(before, P.COMPLETED_WITHOUT_VIDEO, at=TS_2)
    handoff = advance_job_phase(before, P.READY_FOR_RENDER, at=TS_2)
    assert is_legal_terminal(completed.phase)
    assert completed.run_status is R.SUCCEEDED
    assert not is_legal_terminal(handoff.phase)
    assert handoff.run_status is R.PENDING
    assert not any(a.kind is FinalArtifactKind.VIDEO for a in completed.final_artifacts)


@pytest.mark.parametrize("at", [
    None, True, 1, [], {}, "", "2026-09-03T01:02:02Z",
    "2026-09-03T01:02:02.00000Z", "2026-09-03T01:02:02.000000+00:00",
    "2026-02-30T01:02:02.000000Z", "2026-09-03T01:02:02.000000Z ",
    TS_0, TS_1,
])
def test_phase_timestamp_must_be_canonical_and_strictly_increase(at):
    before = manifest()
    with pytest.raises(DomainSchemaError) as exc:
        advance_job_phase(before, P.TIMELINE_READY, at=at)
    assert_error(exc, "domain_field_invalid", "job.updated_at")
    assert before.updated_at == TS_1


def test_phase_accepts_the_next_microsecond():
    at = "2026-09-03T01:02:01.000001Z"
    assert advance_job_phase(manifest(), P.TIMELINE_READY, at=at).updated_at == at


@pytest.mark.parametrize("value", [None, True, 1, "created", "completed_draft", [], {}, R.SUCCEEDED])
def test_phase_public_inputs_reject_non_phase_values(value):
    with pytest.raises(DomainSchemaError) as exc:
        is_legal_terminal(value)
    assert_error(exc, "domain_field_invalid", "job.phase")
    with pytest.raises(DomainSchemaError) as exc:
        advance_job_phase(manifest(), value, at=TS_2)
    assert_error(exc, "domain_field_invalid", "job.phase")


@pytest.mark.parametrize("value", [None, True, 1, "job-001", [], {}, RoundProgressSummary(0, 0, 0, 0)])
def test_phase_public_input_requires_a_validated_manifest(value):
    with pytest.raises(DomainSchemaError) as exc:
        advance_job_phase(value, P.TIMELINE_READY, at=TS_2)
    assert_error(exc, "domain_field_invalid", "job")


@pytest.mark.parametrize("review_flags", product([False, True], repeat=len(T)))
def test_progress_counters_are_exclusive_for_every_review_subset(review_flags):
    tasks = [task(status, number) for number, status in enumerate(T, 1)]
    before = [item.to_dict() for item in tasks]
    reviewed_ids = tuple(item.round_id for item, flag in zip(tasks, review_flags) if flag)
    succeeded_is_pending_review = review_flags[list(T).index(T.SUCCEEDED)]
    expected = RoundProgressSummary(
        total=7, succeeded=int(not succeeded_is_pending_review), failed=1,
        review_pending=int(succeeded_is_pending_review),
    )
    assert derive_round_progress(tasks, reviewed_ids) == expected
    assert derive_round_progress(reversed(tasks), reversed(reviewed_ids)) == expected
    assert [item.to_dict() for item in tasks] == before


def test_progress_counts_multiple_successes_and_normalizes_review_set_membership():
    tasks = [task(T.SUCCEEDED, n) for n in range(1, 4)]
    expected = RoundProgressSummary(3, 2, 0, 1)
    for review_ids in [("round-001",) * 2, {"round-001"}, frozenset({"round-001"})]:
        assert derive_round_progress(tasks, review_ids) == expected
    assert derive_round_progress(tasks) == RoundProgressSummary(3, 3, 0, 0)
    assert derive_round_progress(()) == RoundProgressSummary(0, 0, 0, 0)
    with pytest.raises(FrozenInstanceError):
        expected.review_pending = 0


@pytest.mark.parametrize("derive", [derive_round_progress, derive_translation_run_status])
@pytest.mark.parametrize("different_status", [False, True])
def test_derivations_reject_duplicate_canonical_round_and_task_ids(derive, different_status):
    first = task(T.SUCCEEDED)
    second = task(T.FAILED) if different_status else replace(first)
    assert first.task_id == second.task_id == first.round_id == second.round_id
    with pytest.raises(DomainSchemaError) as exc:
        derive([first, second])
    assert_error(exc, "domain_field_invalid", "round_tasks")


@pytest.mark.parametrize("derive", [derive_round_progress, derive_translation_run_status])
@pytest.mark.parametrize("value", [None, True, 1, "", "round-001", b"", {}, {"round-001": None}])
def test_derivations_reject_invalid_task_containers(derive, value):
    with pytest.raises(DomainSchemaError) as exc:
        derive(value)
    assert_error(exc, "domain_field_invalid", "round_tasks")


@pytest.mark.parametrize("derive", [derive_round_progress, derive_translation_run_status])
@pytest.mark.parametrize("value", [None, True, 1, "succeeded", [], {}, T.SUCCEEDED])
def test_derivations_validate_every_task_even_after_running_work(derive, value):
    with pytest.raises(DomainSchemaError) as exc:
        derive([task(T.RUNNING), value])
    assert_error(exc, "domain_field_invalid", "round_tasks[]")


@pytest.mark.parametrize("value", [None, True, 1, "", "round-001", b"", {}, {"round-001": True}])
def test_progress_rejects_invalid_review_containers(value):
    with pytest.raises(DomainSchemaError) as exc:
        derive_round_progress([task(T.SUCCEEDED)], value)
    assert_error(exc, "domain_field_invalid", "review_pending_round_ids")


@pytest.mark.parametrize("value", [None, True, 1, [], {}, "", "Round-001", "../round-001", "con"])
def test_progress_validates_review_identifiers_before_hashing(value):
    with pytest.raises(DomainSchemaError) as exc:
        derive_round_progress([task(T.SUCCEEDED)], [value])
    assert_error(exc, "domain_identifier_invalid", "review_pending_round_ids[]")


@pytest.mark.parametrize("tasks", [(), (task(T.SUCCEEDED),)])
def test_progress_rejects_review_ids_outside_canonical_task_set(tasks):
    with pytest.raises(DomainSchemaError) as exc:
        derive_round_progress(tasks, ["round-999"])
    assert_error(exc, "round_reference_invalid", "review_pending_round_ids")


# Explicit row oracles: empty, single-status, and every unordered mixed pair.
STATUS_CASES = [
    ((), R.PENDING),
    ((T.PENDING,), R.PENDING), ((T.RUNNING,), R.RUNNING),
    ((T.RETRY_WAIT,), R.RUNNING), ((T.SUCCEEDED,), R.SUCCEEDED),
    ((T.FAILED,), R.FAILED), ((T.CANCELLED,), R.CANCELLED),
    ((T.INTERRUPTED,), R.INTERRUPTED),
    ((T.PENDING, T.RUNNING), R.RUNNING),
    ((T.PENDING, T.RETRY_WAIT), R.RUNNING),
    ((T.PENDING, T.SUCCEEDED), R.PENDING),
    ((T.PENDING, T.FAILED), R.PENDING),
    ((T.PENDING, T.CANCELLED), R.PENDING),
    ((T.PENDING, T.INTERRUPTED), R.PENDING),
    ((T.RUNNING, T.RETRY_WAIT), R.RUNNING),
    ((T.RUNNING, T.SUCCEEDED), R.RUNNING),
    ((T.RUNNING, T.FAILED), R.RUNNING),
    ((T.RUNNING, T.CANCELLED), R.RUNNING),
    ((T.RUNNING, T.INTERRUPTED), R.RUNNING),
    ((T.RETRY_WAIT, T.SUCCEEDED), R.RUNNING),
    ((T.RETRY_WAIT, T.FAILED), R.RUNNING),
    ((T.RETRY_WAIT, T.CANCELLED), R.RUNNING),
    ((T.RETRY_WAIT, T.INTERRUPTED), R.RUNNING),
    ((T.SUCCEEDED, T.FAILED), R.FAILED),
    ((T.SUCCEEDED, T.CANCELLED), R.CANCELLED),
    ((T.SUCCEEDED, T.INTERRUPTED), R.INTERRUPTED),
    ((T.FAILED, T.CANCELLED), R.FAILED),
    ((T.FAILED, T.INTERRUPTED), R.FAILED),
    ((T.CANCELLED, T.INTERRUPTED), R.INTERRUPTED),
    ((T.FAILED, T.CANCELLED, T.INTERRUPTED, T.SUCCEEDED), R.FAILED),
    ((T.INTERRUPTED, T.CANCELLED, T.SUCCEEDED), R.INTERRUPTED),
    ((T.PENDING, T.FAILED, T.CANCELLED, T.INTERRUPTED, T.SUCCEEDED), R.PENDING),
    (tuple(T), R.RUNNING),
]


def test_status_oracles_cover_every_singleton_and_mixed_pair():
    covered = {frozenset(statuses) for statuses, _ in STATUS_CASES}
    assert all(frozenset(pair) in covered for pair in combinations(T, 2))
    assert all(frozenset({status}) in covered for status in T)


@pytest.mark.parametrize("statuses,expected", STATUS_CASES)
def test_translation_status_precedence_and_order_independence(statuses, expected):
    tasks = [task(status, number) for number, status in enumerate(statuses, 1)]
    before = [item.to_dict() for item in tasks]
    assert derive_translation_run_status(tasks) is expected
    assert derive_translation_run_status(reversed(tasks)) is expected
    # More rounds with the same statuses must not change the outcome.
    repeated = [task(status, number) for number, status in enumerate(statuses * 2, 1)]
    assert derive_translation_run_status(repeated) is expected
    assert [item.to_dict() for item in tasks] == before


@pytest.mark.parametrize("status,attempt_status,expected,failed", [
    (T.FAILED, A.EXHAUSTED, R.FAILED, 1),
    (T.CANCELLED, A.RETRYABLE_FAILED, R.CANCELLED, 0),
])
def test_derivations_use_current_task_status_not_attempt_outcome(status, attempt_status, expected, failed):
    current = task(status, attempt_status=attempt_status)
    assert derive_translation_run_status([current]) is expected
    assert derive_round_progress([current]) == RoundProgressSummary(1, 0, failed, 0)


def test_reset_pending_history_is_not_counted_as_a_current_success():
    pending = replace(task(T.SUCCEEDED), status=T.PENDING, result_fingerprint=None, updated_at=TS_3)
    assert derive_translation_run_status([pending]) is R.PENDING
    assert derive_round_progress([pending], [pending.round_id]) == RoundProgressSummary(1, 0, 0, 0)
