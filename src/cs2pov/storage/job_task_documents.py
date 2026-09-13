"""Pure codecs and closure checks for durable round tasks.

Historical closure uses retained hashes and records, never today's transcript.
Freshness against today's input is a separate publication-time check.
"""

from dataclasses import replace
from collections.abc import Iterable

from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import ModelCapability
from cs2pov.domain.job_tasks import (
    RoundAttemptStatus,
    RoundTaskStatus,
    RoundTranslationTask,
)
from cs2pov.domain.timeline import DemoTimeline

from .atomic_documents import schema_aware_parser
from .job_errors import JobRepositoryError


ROUND_TASK_PARSER = schema_aware_parser(
    RoundTranslationTask.from_dict, expectations=("",),
)


def invalid(path, message="回合任务引用关系无效。", code="job_shard_invalid"):
    return JobRepositoryError(code, message, "请恢复一致的任务数据后重试。", path)


def task_path(task):
    return f"tasks/round_{task.round_id}.json"


def canonical_round_tasks(
    timeline: DemoTimeline, tasks: Iterable[RoundTranslationTask], *, complete=True,
) -> tuple[RoundTranslationTask, ...]:
    values = tuple(tasks)
    if any(type(t) is not RoundTranslationTask for t in values):
        raise invalid("tasks")
    by_id = {t.round_id: t for t in values}
    ids = tuple(r.round_id for r in timeline.rounds.rounds)
    if len(by_id) != len(values) or set(by_id) - set(ids):
        raise invalid("tasks")
    if complete and set(by_id) != set(ids):
        raise invalid("tasks", "初始化任务必须覆盖全部回合。")
    return tuple(by_id[i] for i in ids if i in by_id)


def task_input_fingerprint(document_input_fingerprint, configuration):
    return content_fingerprint({
        "document_input_fingerprint": document_input_fingerprint,
        "configuration_fingerprint": configuration.configuration_fingerprint,
    })


def require_task_configuration(snapshot_id, configurations, path):
    config = configurations.get(snapshot_id)
    if config is None or config.capability is not ModelCapability.UNDERSTANDING_TRANSLATION:
        raise invalid(path)
    return config


def validate_historical_document(document, configurations, invocations, path):
    require_task_configuration(document.model_configuration_snapshot_id, configurations, path)
    if not document.results:
        if document.invocation_record_id is not None or document.input_fingerprint != content_fingerprint({
            "round_id": document.round_id, "transcript_cues": [],
        }):
            raise invalid(path)
        return
    call = invocations.get(document.invocation_record_id)
    if (
        call is None or call.task_id != document.round_id
        or call.configuration_snapshot_id != document.model_configuration_snapshot_id
        or call.request_content_fingerprint != document.input_fingerprint
        or call.response_content_fingerprint != content_fingerprint({
            "round_id": document.round_id,
            "results": [r.to_dict() for r in document.results],
        })
        or any(r.model_invocation_record_id != call.invocation_id for r in document.results)
    ):
        raise invalid(path)


def validate_succeeded_task_result(task, document) -> None:
    if (
        task.status is not RoundTaskStatus.SUCCEEDED
        or task.round_id != document.round_id
        or task.result_fingerprint != document.content_fingerprint()
        or task.configuration_snapshot_id != document.model_configuration_snapshot_id
    ):
        raise invalid(task_path(task))


def validate_task_history(task, configurations, invocations, results):
    path = task_path(task)
    require_task_configuration(task.configuration_snapshot_id, configurations, path)
    for attempt in task.attempts:
        config = require_task_configuration(attempt.configuration_snapshot_id, configurations, path)
        for invocation_id in attempt.invocation_record_ids:
            call = invocations.get(invocation_id)
            if (
                call is None or call.task_id != task.task_id
                or call.configuration_snapshot_id != attempt.configuration_snapshot_id
                or task_input_fingerprint(call.request_content_fingerprint, config) != attempt.input_fingerprint
            ):
                raise invalid(path)
        if attempt.status is RoundAttemptStatus.SUCCEEDED:
            document = results.get((task.round_id, attempt.result_fingerprint))
            if document is None:
                raise invalid(path, "成功尝试缺少匹配的当前或历史结果。")
            validate_historical_document(document, configurations, invocations, path)
            if (
                document.model_configuration_snapshot_id != attempt.configuration_snapshot_id
                or task_input_fingerprint(document.input_fingerprint, config) != attempt.input_fingerprint
                or (document.invocation_record_id is not None and document.invocation_record_id not in attempt.invocation_record_ids)
            ):
                raise invalid(path)


def validate_task_replacement(old, new):
    """CAS cannot erase/rewrite history or bypass the task's state graph."""
    path = task_path(old)
    if (old.task_id, old.round_id) != (new.task_id, new.round_id) or new.updated_at <= old.updated_at:
        raise invalid(path)
    if len(new.attempts) < len(old.attempts):
        raise invalid(path)
    for index, previous in enumerate(old.attempts):
        candidate = new.attempts[index]
        if previous.status is not RoundAttemptStatus.RUNNING:
            if candidate != previous:
                raise invalid(path, "已结束的尝试历史不能改写。")
        else:
            if (
                replace(candidate, status=previous.status, finished_at=previous.finished_at,
                        error=previous.error, result_fingerprint=previous.result_fingerprint,
                        invocation_record_ids=previous.invocation_record_ids) != previous
                or candidate.invocation_record_ids[:len(previous.invocation_record_ids)] != previous.invocation_record_ids
            ):
                raise invalid(path, "运行中尝试只能追加引用或结束。")
    changed = (old.input_fingerprint, old.configuration_snapshot_id) != (new.input_fingerprint, new.configuration_snapshot_id)
    if changed:
        if old.status is RoundTaskStatus.RUNNING or new.status is not RoundTaskStatus.PENDING or new.attempts != old.attempts:
            raise invalid(path)
        return
    allowed = {
        RoundTaskStatus.PENDING: {RoundTaskStatus.RUNNING},
        RoundTaskStatus.RUNNING: {RoundTaskStatus.RUNNING, RoundTaskStatus.SUCCEEDED, RoundTaskStatus.RETRY_WAIT, RoundTaskStatus.FAILED, RoundTaskStatus.CANCELLED, RoundTaskStatus.INTERRUPTED},
        RoundTaskStatus.RETRY_WAIT: {RoundTaskStatus.RUNNING, RoundTaskStatus.CANCELLED},
        RoundTaskStatus.FAILED: {RoundTaskStatus.PENDING},
        RoundTaskStatus.CANCELLED: {RoundTaskStatus.PENDING},
        RoundTaskStatus.INTERRUPTED: {RoundTaskStatus.PENDING},
        RoundTaskStatus.SUCCEEDED: set(),
    }
    if new.status not in allowed[old.status]:
        raise invalid(path)
    starting = new.status is RoundTaskStatus.RUNNING and old.status is not RoundTaskStatus.RUNNING
    if len(new.attempts) != len(old.attempts) + int(starting):
        raise invalid(path)
    if starting and (new.attempts[-1].started_at != new.updated_at or (old.next_retry_at is not None and new.updated_at < old.next_retry_at)):
        raise invalid(path)
    if old.status is RoundTaskStatus.RUNNING and new.status is not RoundTaskStatus.RUNNING and new.attempts[-1].finished_at != new.updated_at:
        raise invalid(path)
