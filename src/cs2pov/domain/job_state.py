"""Pure Job phase gates and task-derived progress."""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from types import MappingProxyType

from .errors import DomainSchemaError
from .job import JobManifest, JobPhase as P, JobRunStatus as R, RoundProgressSummary
from .job_tasks import RoundTaskStatus as T, RoundTranslationTask
from .schema import require_canonical_utc_timestamp, require_path_identifier


_FORWARD_PHASES = MappingProxyType(
    {
        P.CREATED: frozenset({P.TIMELINE_READY}),
        P.TIMELINE_READY: frozenset({P.VOICE_READY}),
        P.VOICE_READY: frozenset({P.TRANSCRIBED}),
        P.TRANSCRIBED: frozenset({P.CONTEXT_READY}),
        P.CONTEXT_READY: frozenset({P.UNDERSTANDING_TRANSLATING}),
        P.UNDERSTANDING_TRANSLATING: frozenset({P.UNDERSTOOD_TRANSLATED}),
        P.UNDERSTOOD_TRANSLATED: frozenset({P.DRAFT_TIMELINE_READY}),
        P.DRAFT_TIMELINE_READY: frozenset({P.COMPLETED_DRAFT, P.REVIEW_PENDING}),
        P.COMPLETED_DRAFT: frozenset(),
        P.REVIEW_PENDING: frozenset({P.REVIEWED}),
        P.REVIEWED: frozenset({P.FINAL_TIMELINE_READY}),
        P.FINAL_TIMELINE_READY: frozenset({P.SUBTITLES_EXPORTED}),
        P.SUBTITLES_EXPORTED: frozenset({P.GREEN_SCREEN_RENDERED}),
        P.GREEN_SCREEN_RENDERED: frozenset(
            {P.COMPLETED_WITHOUT_VIDEO, P.READY_FOR_RENDER}
        ),
        P.COMPLETED_WITHOUT_VIDEO: frozenset(),
        P.READY_FOR_RENDER: frozenset({P.RENDERING}),
        P.RENDERING: frozenset({P.VIDEO_READY}),
        P.VIDEO_READY: frozenset({P.COMPLETED_WITH_VIDEO}),
        P.COMPLETED_WITH_VIDEO: frozenset(),
    }
)
_DEFAULT_RUN_STATUS = MappingProxyType(
    {
        phase: (
            R.PENDING
            if phase in {P.CREATED, P.REVIEW_PENDING, P.READY_FOR_RENDER}
            else R.RUNNING
            if phase in {P.UNDERSTANDING_TRANSLATING, P.RENDERING}
            else R.SUCCEEDED
        )
        for phase in P
    }
)
_TERMINALS = frozenset(
    {P.COMPLETED_DRAFT, P.COMPLETED_WITHOUT_VIDEO, P.COMPLETED_WITH_VIDEO}
)


def _invalid(path, code="domain_field_invalid"):
    raise DomainSchemaError(
        code, "Job 状态数据无效。", "请核对任务阶段和回合记录。", path
    )


def is_legal_terminal(phase: P) -> bool:
    if not isinstance(phase, P):
        _invalid("job.phase")
    return phase in _TERMINALS


def advance_job_phase(manifest: JobManifest, target: P, *, at: str) -> JobManifest:
    """Advance one edge; the coordinator separately validates referenced outputs."""
    if not isinstance(manifest, JobManifest):
        _invalid("job")
    if not isinstance(target, P):
        _invalid("job.phase")
    if target not in _FORWARD_PHASES[manifest.phase]:
        _invalid("job.phase", "domain_state_transition_invalid")
    if (
        target in {P.REVIEWED, P.FINAL_TIMELINE_READY}
        and manifest.active_review_id is None
    ):
        _invalid("job.active_review_id", "domain_state_transition_invalid")
    require_canonical_utc_timestamp(at, "job.updated_at")
    if at <= manifest.updated_at:
        _invalid("job.updated_at")
    return replace(
        manifest, phase=target, run_status=_DEFAULT_RUN_STATUS[target], updated_at=at
    )


def _items(value, path):
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        _invalid(path)
    return tuple(value)


def _tasks(value) -> tuple[RoundTranslationTask, ...]:
    tasks = _items(value, "round_tasks")
    task_ids, round_ids = set(), set()
    for task in tasks:
        if not isinstance(task, RoundTranslationTask):
            _invalid("round_tasks[]")
        if task.task_id in task_ids or task.round_id in round_ids:
            _invalid("round_tasks")
        task_ids.add(task.task_id)
        round_ids.add(task.round_id)
    return tasks


def derive_round_progress(tasks, review_pending_round_ids=()) -> RoundProgressSummary:
    tasks = _tasks(tasks)
    review_ids = _items(review_pending_round_ids, "review_pending_round_ids")
    for round_id in review_ids:
        require_path_identifier(round_id, "review_pending_round_ids[]")
    review_ids = set(review_ids)
    if review_ids - {task.round_id for task in tasks}:
        _invalid("review_pending_round_ids", "round_reference_invalid")
    successes = {task.round_id for task in tasks if task.status is T.SUCCEEDED}
    return RoundProgressSummary(
        len(tasks),
        len(successes - review_ids),
        sum(task.status is T.FAILED for task in tasks),
        len(successes & review_ids),
    )


def derive_translation_run_status(tasks) -> R:
    """Precedence: active/retrying > pending > failed > interrupted > cancelled.

    Only all-succeeded nonempty sets succeed. Pending work prevents a terminal
    aggregate outcome; the coordinator records explicit cancellation separately.
    """
    statuses = {task.status for task in _tasks(tasks)}
    if statuses & {T.RUNNING, T.RETRY_WAIT}:
        return R.RUNNING
    if not statuses or T.PENDING in statuses:
        return R.PENDING
    if T.FAILED in statuses:
        return R.FAILED
    if T.INTERRUPTED in statuses:
        return R.INTERRUPTED
    if T.CANCELLED in statuses:
        return R.CANCELLED
    return R.SUCCEEDED
