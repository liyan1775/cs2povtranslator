"""Durable orchestration for the round translation phase.

The coordinator owns the small amount of application state between the pure
task transitions and the claim-fenced repository.  Workers only return typed
values; all source graph validation and all durable publication happens here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invalidation import (
    InvalidationRequest,
    JobInputChange,
    plan_invalidation,
    rewind_job_phase_for_invalidation,
)
from cs2pov.domain.job import (
    JobEvent,
    JobPhase,
    JobRunStatus,
)
from cs2pov.domain.invocation import ModelCapability
from cs2pov.domain.job_state import (
    advance_job_phase,
    derive_round_progress,
    derive_translation_run_status,
)
from cs2pov.domain.job_task_state import (
    cancel_task,
    fail_task,
    interrupt_task,
    reset_task,
    retry_task,
    start_task,
    succeed_task,
    supersede_task,
)
from cs2pov.domain.job_tasks import (
    RetryPolicy,
    RoundTaskSpec,
    RoundTaskStatus,
    RoundTranslationTask,
)
from cs2pov.domain.job import JobWriteClaim
from cs2pov.domain.timeline import Round
from cs2pov.domain.validation import (
    validate_transcript_against_timeline,
    validate_understanding_document_graph,
    validate_voice_activity_against_timeline,
)
from cs2pov.application.round_worker import (
    RoundWorkFailure,
    RoundWorkRequest,
    RoundWorkResult,
    build_round_work_request,
    validate_round_work_failure,
    validate_round_work_result,
)
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.storage.job_task_documents import task_input_fingerprint


_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def parse_canonical_utc(value: str) -> datetime:
    """Parse the repository's fixed-width UTC timestamp representation."""
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid canonical UTC timestamp") from exc


def next_persisted_timestamp(now: datetime, *latest_values: str) -> str:
    """Allocate a timestamp strictly after all relevant persisted values."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    try:
        latest = max((parse_canonical_utc(value) for value in latest_values), default=None)
        candidate = now.astimezone(timezone.utc)
        if latest is not None and candidate <= latest:
            candidate = latest + timedelta(microseconds=1)
        return candidate.strftime(_TIMESTAMP_FORMAT)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("timestamp allocation failed") from exc


def _timestamp_error(cause: BaseException) -> JobRepositoryError:
    error = JobRepositoryError(
        "job_timestamp_invalid",
        "Job 时间无效。",
        "请检查系统时间后重试。",
        "job.json",
    )
    error.__cause__ = cause
    return error


def _conflict(message: str = "任务已被其他操作更新。") -> JobRepositoryError:
    return JobRepositoryError("job_task_conflict", message, "请重新读取任务后重试。", "tasks")


@dataclass(frozen=True, slots=True)
class PreparedRoundBatch:
    job_id: str
    configuration_snapshot_id: str
    tasks: tuple[RoundTranslationTask, ...]
    requests: tuple[RoundWorkRequest, ...]


class JobRoundCoordinator:
    def __init__(
        self,
        repository: FileSystemJobRepository,
        *,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], str],
    ) -> None:
        if not isinstance(repository, FileSystemJobRepository):
            raise TypeError("repository 必须是 FileSystemJobRepository。")
        if not callable(clock) or not callable(event_id_factory):
            raise TypeError("coordinator 依赖必须可调用。")
        self.repository = repository
        self.clock = clock
        self.event_id_factory = event_id_factory

    def _next_at(self, *latest_values: str) -> str:
        try:
            return next_persisted_timestamp(self.clock(), *latest_values)
        except (OverflowError, TypeError, ValueError) as exc:
            raise _timestamp_error(exc) from exc

    def _load_evidence(self, job_id: str):
        """Read the complete current source graph without current-result projection."""
        opened = self.repository.load_job(job_id)
        timeline = self.repository.load_demo_timeline(job_id)
        activities = self.repository.load_voice_activities(job_id)
        configurations = self.repository.load_model_configurations(job_id)
        invocations = self.repository.load_all_invocations(job_id)
        round_ids = tuple(value.round_id for value in timeline.rounds.rounds)
        transcripts = tuple(
            cue
            for round_id in round_ids
            for cue in self.repository.load_transcript_round(job_id, round_id)
        ) + self.repository.load_unassigned_transcript(job_id)
        try:
            for activity in activities:
                validate_voice_activity_against_timeline(activity, timeline)
            for cue in transcripts:
                validate_transcript_against_timeline(
                    cue, timeline, activities, configurations, invocations
                )
        except DomainSchemaError as exc:
            raise JobRepositoryError(
                "job_shard_invalid",
                "语言数据图引用关系无效。",
                "请恢复一致的语言数据后重试。",
                "language_graph",
            ) from exc
        return opened, timeline, activities, configurations, invocations, transcripts

    @staticmethod
    def _configuration(configurations, snapshot_id):
        try:
            value = next(value for value in configurations if value.snapshot_id == snapshot_id)
        except StopIteration as exc:
            raise JobRepositoryError(
                "job_shard_invalid",
                "模型配置快照不存在或能力不匹配。",
                "请使用已登记的理解翻译配置。",
                "models/snapshots",
            ) from exc
        if value.capability is not ModelCapability.UNDERSTANDING_TRANSLATION:
            raise JobRepositoryError(
                "job_shard_invalid",
                "模型配置快照不存在或能力不匹配。",
                "请使用已登记的理解翻译配置。",
                "models/snapshots",
            )
        return value

    def _preflight_invalidation(
        self, opened, affected, specs_by_id, existing_by_id, configuration
    ):
        if configuration.capability is not ModelCapability.UNDERSTANDING_TRANSLATION:
            raise JobRepositoryError(
                "job_shard_invalid",
                "模型配置快照能力不匹配。",
                "请使用已登记的理解翻译配置。",
                "models/snapshots",
            )
        for round_id in affected:
            old = existing_by_id[round_id]
            if old.status is RoundTaskStatus.RUNNING:
                raise _conflict("运行中的任务必须先结束后才能失效。")
            try:
                supersede_task(
                    old,
                    spec=specs_by_id[round_id],
                    at=self._next_at(old.updated_at, opened.manifest.updated_at),
                )
            except (DomainSchemaError, TypeError, ValueError) as exc:
                raise _conflict("任务失效前置条件不满足。") from exc

    def _preflight_resume(self, job_id, tasks, retry_ids):
        if not isinstance(retry_ids, set):
            raise JobRepositoryError(
                "job_task_conflict",
                "恢复任务列表格式无效。",
                "请重新指定要重试的回合。",
                "tasks",
            )
        known_ids = {task.round_id for task in tasks}
        if not retry_ids.issubset(known_ids):
            raise JobRepositoryError(
                "job_task_conflict",
                "恢复任务列表包含未知回合。",
                "请从当前 Job 状态中选择要重试的回合。",
                "tasks",
            )
        invalid_retry_ids = {
            task.round_id
            for task in tasks
            if task.round_id in retry_ids
            and task.status not in {RoundTaskStatus.FAILED, RoundTaskStatus.CANCELLED}
        }
        if invalid_retry_ids:
            raise _conflict("只有失败或取消的回合可以显式重试。")
        _, _, _, configurations, invocations, transcripts = self._load_evidence(job_id)
        for task in tasks:
            if task.status is not RoundTaskStatus.SUCCEEDED:
                continue
            document = self.repository.load_round_understanding(job_id, task.round_id)
            if (
                task.result_fingerprint != document.content_fingerprint()
                or task.configuration_snapshot_id
                != document.model_configuration_snapshot_id
            ):
                raise JobRepositoryError(
                    "job_shard_invalid",
                    "成功任务缺少匹配的理解翻译结果。",
                    "请恢复结果文件后再继续。",
                    f"understanding/round_{task.round_id}.json",
                )
            try:
                validate_understanding_document_graph(
                    document, transcripts, configurations, invocations
                )
            except DomainSchemaError as exc:
                raise JobRepositoryError(
                    "job_shard_invalid",
                    "成功任务的完整数据图无效。",
                    "请恢复结果文件后再继续。",
                    f"understanding/round_{task.round_id}.json",
                ) from exc

    @staticmethod
    def _document_digest(round_value: Round, transcripts) -> str:
        selected = sorted(
            (cue for cue in transcripts if cue.round_id == round_value.round_id),
            key=lambda cue: (cue.time_range.start_us, cue.time_range.end_us, cue.cue_id),
        )
        return content_fingerprint(
            {
                "round_id": round_value.round_id,
                "transcript_cues": [cue.to_dict() for cue in selected],
            }
        )

    def _desired_specs(self, timeline, transcripts, configuration):
        return tuple(
            RoundTaskSpec(
                value.round_id,
                value.round_id,
                task_input_fingerprint(
                    self._document_digest(value, transcripts), configuration
                ),
                configuration.snapshot_id,
            )
            for value in timeline.rounds.rounds
        )

    def _build_request(self, task, round_value, configuration, transcripts):
        return build_round_work_request(
            task=task,
            round=round_value,
            configuration=configuration,
            transcripts=transcripts,
        )

    def _runnable_batch(
        self, job_id, configuration_snapshot_id, tasks, timeline, configurations, transcripts
    ) -> PreparedRoundBatch:
        configuration = self._configuration(configurations, configuration_snapshot_id)
        rounds = {value.round_id: value for value in timeline.rounds.rounds}
        requests = tuple(
            self._build_request(task, rounds[task.round_id], configuration, transcripts)
            for task in tasks
            if task.status in {RoundTaskStatus.PENDING, RoundTaskStatus.RETRY_WAIT}
        )
        return PreparedRoundBatch(job_id, configuration_snapshot_id, tuple(tasks), requests)

    def _replace_manifest(self, job_id, tasks, claim, *, allow_phase_advance=True):
        opened = self.repository.load_job(job_id)
        progress = derive_round_progress(tasks)
        phase = opened.manifest.phase
        run_status = opened.manifest.run_status
        all_succeeded = bool(tasks) and all(
            task.status is RoundTaskStatus.SUCCEEDED for task in tasks
        )
        if phase is JobPhase.UNDERSTANDING_TRANSLATING:
            if all_succeeded and allow_phase_advance:
                at = self._next_at(
                    opened.manifest.updated_at,
                    *(task.updated_at for task in tasks),
                )
                candidate = advance_job_phase(
                    opened.manifest, JobPhase.UNDERSTOOD_TRANSLATED, at=at
                )
                candidate = replace(candidate, round_progress=progress)
            else:
                run_status = derive_translation_run_status(tasks)
                if (
                    progress == opened.manifest.round_progress
                    and run_status is opened.manifest.run_status
                ):
                    return opened
                at = self._next_at(
                    opened.manifest.updated_at,
                    *(task.updated_at for task in tasks),
                )
                candidate = replace(
                    opened.manifest,
                    updated_at=at,
                    round_progress=progress,
                    run_status=run_status,
                )
        elif phase is JobPhase.CONTEXT_READY:
            active = any(
                task.status in {RoundTaskStatus.RUNNING, RoundTaskStatus.RETRY_WAIT}
                for task in tasks
            )
            if active and allow_phase_advance:
                at = self._next_at(
                    opened.manifest.updated_at,
                    *(task.updated_at for task in tasks),
                )
                candidate = advance_job_phase(
                    opened.manifest, JobPhase.UNDERSTANDING_TRANSLATING, at=at
                )
                candidate = replace(candidate, round_progress=progress)
                return self.repository.replace_manifest(
                    job_id, opened.manifest.content_fingerprint(), candidate, claim
                )
            if (
                progress == opened.manifest.round_progress
                and opened.manifest.run_status is JobRunStatus.SUCCEEDED
            ):
                return opened
            at = self._next_at(
                opened.manifest.updated_at, *(task.updated_at for task in tasks)
            )
            candidate = replace(
                opened.manifest,
                updated_at=at,
                round_progress=progress,
                run_status=JobRunStatus.SUCCEEDED,
            )
        else:
            # Preparation/checkpoints are scoped to the translation phase.  A
            # later phase may still be read, but is never silently rewound.
            return opened
        return self.repository.replace_manifest(
            job_id, opened.manifest.content_fingerprint(), candidate, claim
        )

    def _append_event(self, job_id, claim, event_type, payload, tasks=()):
        opened = self.repository.load_job(job_id)
        latest = [opened.manifest.updated_at, *(task.updated_at for task in tasks)]
        try:
            journal = self.repository.read_events(job_id)
            if journal.events:
                latest.append(journal.events[-1].occurred_at)
        except JobRepositoryError:
            raise
        occurred_at = self._next_at(*latest)
        event = JobEvent(
            str(self.event_id_factory()),
            job_id,
            claim.run_id,
            occurred_at,
            event_type,
            payload,
        )
        self.repository.append_event(job_id, event, claim)

    def _find_current(self, job_id, supplied):
        if type(supplied) is not RoundTranslationTask:
            raise TypeError("task 必须是 RoundTranslationTask。")
        current = next(
            (
                value
                for value in self.repository.load_round_tasks(job_id)
                if value.task_id == supplied.task_id
            ),
            None,
        )
        if current is None or current.content_fingerprint() != supplied.content_fingerprint():
            raise _conflict()
        return current

    def _merge_invocations(self, existing, supplied):
        merged = {value.invocation_id: value for value in existing}
        for value in supplied:
            previous = merged.get(value.invocation_id)
            if previous is not None and previous != value:
                raise JobRepositoryError(
                    "job_shard_invalid",
                    "同一模型调用 ID 对应了不同内容。",
                    "请恢复一致的调用记录后重试。",
                    "models/invocations",
                )
            merged[value.invocation_id] = value
        return tuple(merged.values())

    def _validate_full_result(self, job_id, current, result):
        opened, timeline, activities, configurations, existing, transcripts = self._load_evidence(
            job_id
        )
        configuration = self._configuration(
            configurations, current.configuration_snapshot_id
        )
        round_value = next(
            value for value in timeline.rounds.rounds if value.round_id == current.round_id
        )
        request = self._build_request(current, round_value, configuration, transcripts)
        validate_round_work_result(request, result)
        merged = self._merge_invocations(existing, result.invocations)
        try:
            validate_understanding_document_graph(
                result.document, transcripts, configurations, merged
            )
        except DomainSchemaError as exc:
            raise JobRepositoryError(
                "job_shard_invalid",
                "理解翻译结果未通过完整数据图校验。",
                "请丢弃该回合结果并重新运行。",
                f"understanding/round_{current.round_id}.json",
            ) from exc
        return request, existing, merged, transcripts, configurations

    def _validate_full_failure(self, job_id, current, failure):
        opened, timeline, activities, configurations, existing, transcripts = self._load_evidence(
            job_id
        )
        configuration = self._configuration(
            configurations, current.configuration_snapshot_id
        )
        round_value = next(
            value for value in timeline.rounds.rounds if value.round_id == current.round_id
        )
        request = self._build_request(current, round_value, configuration, transcripts)
        validate_round_work_failure(request, failure)
        merged = self._merge_invocations(existing, failure.invocations)
        return request, existing, merged

    def prepare_translation(
        self,
        job_id: str,
        *,
        configuration_snapshot_id: str,
        claim: JobWriteClaim,
    ) -> PreparedRoundBatch:
        opened, timeline, _, configurations, _, transcripts = self._load_evidence(job_id)
        configuration = self._configuration(configurations, configuration_snapshot_id)
        existing = self.repository.load_round_tasks(job_id)
        existing_by_id = {value.round_id: value for value in existing}
        specs = self._desired_specs(timeline, transcripts, configuration)
        affected = tuple(
            spec.round_id
            for spec in specs
            if spec.round_id in existing_by_id
            and (
                existing_by_id[spec.round_id].input_fingerprint != spec.input_fingerprint
                or existing_by_id[spec.round_id].configuration_snapshot_id
                != spec.configuration_snapshot_id
            )
        )

        if affected:
            self._preflight_invalidation(
                opened,
                affected,
                {spec.round_id: spec for spec in specs},
                existing_by_id,
                configuration,
            )

        for spec in specs:
            old = existing_by_id.get(spec.round_id)
            if old is None or old.status is not RoundTaskStatus.SUCCEEDED:
                continue
            if spec.round_id in affected:
                continue
            document = self.repository.load_round_understanding(job_id, old.round_id)
            try:
                validate_understanding_document_graph(
                    document, transcripts, configurations, self.repository.load_all_invocations(job_id)
                )
            except DomainSchemaError as exc:
                raise JobRepositoryError(
                    "job_shard_invalid",
                    "已成功回合的理解翻译结果无效。",
                    "请恢复该回合的结果后重试。",
                    f"understanding/round_{old.round_id}.json",
                ) from exc
            if old.result_fingerprint != document.content_fingerprint():
                raise JobRepositoryError(
                    "job_shard_invalid",
                    "已成功回合的结果指纹不一致。",
                    "请恢复该回合的任务和结果后重试。",
                    f"tasks/round_{old.round_id}.json",
                )

        if affected:
            plan = plan_invalidation(
                InvalidationRequest(JobInputChange.TRANSLATION_CONFIGURATION, affected)
            )
            for round_id in affected:
                old = existing_by_id[round_id]
                if old.status is RoundTaskStatus.SUCCEEDED:
                    self.repository.archive_round_understanding(
                        job_id, round_id, old.result_fingerprint, claim
                    )
            current = self.repository.load_job(job_id)
            rewind_at = self._next_at(
                current.manifest.updated_at,
                *(value.updated_at for value in self.repository.load_round_tasks(job_id)),
            )
            rewound = rewind_job_phase_for_invalidation(
                current.manifest, plan, at=rewind_at
            )
            self.repository.replace_manifest(
                job_id,
                current.manifest.content_fingerprint(),
                rewound,
                claim,
            )
            for spec in specs:
                if spec.round_id not in affected:
                    continue
                current_task = next(
                    value
                    for value in self.repository.load_round_tasks(job_id)
                    if value.round_id == spec.round_id
                )
                at = self._next_at(
                    current_task.updated_at,
                    self.repository.load_job(job_id).manifest.updated_at,
                )
                replacement = supersede_task(current_task, spec=spec, at=at)
                self.repository.replace_round_task(
                    job_id, current_task.content_fingerprint(), replacement, claim
                )
            tasks = self.repository.load_round_tasks(job_id)
            self._replace_manifest(job_id, tasks, claim)
            self._append_event(
                job_id,
                claim,
                "round_tasks_invalidated",
                {"round_ids": list(affected), "first_invalid_phase": plan.first_invalid_phase.value},
                tasks,
            )

        current_tasks = self.repository.load_round_tasks(job_id)
        by_id = {value.round_id: value for value in current_tasks}
        last_values = [self.repository.load_job(job_id).manifest.updated_at]
        last_values.extend(value.updated_at for value in current_tasks)
        materialized = []
        for spec in specs:
            current = by_id.get(spec.round_id)
            if current is not None:
                materialized.append(current)
                continue
            at = self._next_at(*last_values)
            pending = RoundTranslationTask.pending(
                task_id=spec.task_id,
                round_id=spec.round_id,
                input_fingerprint=spec.input_fingerprint,
                configuration_snapshot_id=spec.configuration_snapshot_id,
                updated_at=at,
            )
            materialized.append(pending)
            last_values.append(at)
        persisted = self.repository.initialize_round_tasks(job_id, tuple(materialized), claim)
        self._replace_manifest(job_id, persisted, claim)
        return self._runnable_batch(
            job_id,
            configuration_snapshot_id,
            persisted,
            timeline,
            configurations,
            transcripts,
        )

    def mark_running(
        self, task: RoundTranslationTask, *, attempt_id: str, claim: JobWriteClaim
    ) -> RoundTranslationTask:
        job_id = claim.job_id
        current = self._find_current(job_id, task)
        opened = self.repository.load_job(job_id)
        at = self._next_at(current.updated_at, opened.manifest.updated_at)
        running = start_task(current, attempt_id=attempt_id, at=at)
        persisted = self.repository.replace_round_task(
            job_id, current.content_fingerprint(), running, claim
        )
        tasks = self.repository.load_round_tasks(job_id)
        self._replace_manifest(job_id, tasks, claim)
        self._append_event(
            job_id,
            claim,
            "round_task_started",
            {"round_id": current.round_id, "attempt_id": attempt_id},
            tasks,
        )
        return persisted

    def checkpoint_success(
        self,
        task: RoundTranslationTask,
        result: RoundWorkResult,
        *,
        claim: JobWriteClaim,
    ) -> RoundTranslationTask:
        job_id = claim.job_id
        current = self._find_current(job_id, task)
        if current.status is not RoundTaskStatus.RUNNING:
            raise _conflict("只有运行中的任务可以提交成功结果。")
        _, existing, merged, _, _ = self._validate_full_result(job_id, current, result)
        if result.invocations:
            self.repository.merge_task_invocations(
                job_id, current.task_id, result.invocations, claim
            )
        self.repository.save_round_understanding(job_id, result.document, claim)
        latest = self.repository.load_job(job_id).manifest.updated_at
        at = self._next_at(current.updated_at, latest)
        succeeded = succeed_task(
            current,
            at=at,
            result_fingerprint=result.document.content_fingerprint(),
            invocation_record_ids=tuple(value.invocation_id for value in result.invocations),
        )
        persisted = self.repository.replace_round_task(
            job_id, current.content_fingerprint(), succeeded, claim
        )
        tasks = self.repository.load_round_tasks(job_id)
        self._replace_manifest(job_id, tasks, claim)
        self._append_event(
            job_id,
            claim,
            "round_task_succeeded",
            {
                "round_id": current.round_id,
                "result_fingerprint": result.document.content_fingerprint(),
            },
            tasks,
        )
        return persisted

    def checkpoint_failure(
        self,
        task: RoundTranslationTask,
        failure: RoundWorkFailure,
        *,
        policy: RetryPolicy,
        claim: JobWriteClaim,
    ) -> RoundTranslationTask:
        job_id = claim.job_id
        current = self._find_current(job_id, task)
        if current.status is not RoundTaskStatus.RUNNING:
            raise _conflict("只有运行中的任务可以提交失败结果。")
        _, _, _ = self._validate_full_failure(job_id, current, failure)
        if failure.invocations:
            self.repository.merge_task_invocations(
                job_id, current.task_id, failure.invocations, claim
            )
        at = self._next_at(
            current.updated_at, self.repository.load_job(job_id).manifest.updated_at
        )
        if failure.error.retryable:
            next_task = retry_task(
                current,
                at=at,
                error=failure.error,
                policy=policy,
                invocation_record_ids=tuple(
                    value.invocation_id for value in failure.invocations
                ),
            )
        else:
            next_task = fail_task(
                current,
                at=at,
                error=failure.error,
                invocation_record_ids=tuple(
                    value.invocation_id for value in failure.invocations
                ),
            )
        persisted = self.repository.replace_round_task(
            job_id, current.content_fingerprint(), next_task, claim
        )
        tasks = self.repository.load_round_tasks(job_id)
        self._replace_manifest(job_id, tasks, claim)
        self._append_event(
            job_id,
            claim,
            "round_task_failed" if next_task.status is RoundTaskStatus.FAILED else "round_task_retry_wait",
            {"round_id": current.round_id, "error_code": failure.error.code},
            tasks,
        )
        return persisted

    def checkpoint_cancellation(
        self, task: RoundTranslationTask, *, claim: JobWriteClaim
    ) -> RoundTranslationTask:
        job_id = claim.job_id
        current = self._find_current(job_id, task)
        if current.status in {
            RoundTaskStatus.PENDING,
            RoundTaskStatus.SUCCEEDED,
            RoundTaskStatus.FAILED,
            RoundTaskStatus.CANCELLED,
            RoundTaskStatus.INTERRUPTED,
        }:
            return current
        at = self._next_at(
            current.updated_at, self.repository.load_job(job_id).manifest.updated_at
        )
        cancelled = cancel_task(current, at=at)
        persisted = self.repository.replace_round_task(
            job_id, current.content_fingerprint(), cancelled, claim
        )
        tasks = self.repository.load_round_tasks(job_id)
        self._replace_manifest(job_id, tasks, claim)
        self._append_event(
            job_id,
            claim,
            "round_task_cancelled",
            {"round_id": current.round_id},
            tasks,
        )
        return persisted

    def reconcile_for_resume(
        self,
        job_id: str,
        *,
        claim: JobWriteClaim,
        retry_round_ids: tuple[str, ...] = (),
    ) -> PreparedRoundBatch:
        tasks = self.repository.load_round_tasks(job_id)
        if not isinstance(retry_round_ids, (tuple, list)) or any(
            not isinstance(value, str) for value in retry_round_ids
        ):
            raise JobRepositoryError(
                "job_task_conflict",
                "恢复任务列表格式无效。",
                "请重新指定要重试的回合。",
                "tasks",
            )
        retry_ids = set(retry_round_ids)
        self._preflight_resume(job_id, tasks, retry_ids)
        for task in tasks:
            current = task
            if current.status is RoundTaskStatus.RUNNING:
                at = self._next_at(
                    current.updated_at, self.repository.load_job(job_id).manifest.updated_at
                )
                interrupted = interrupt_task(current, at=at)
                self.repository.replace_round_task(
                    job_id, current.content_fingerprint(), interrupted, claim
                )
                current = interrupted
                at = self._next_at(
                    current.updated_at, self.repository.load_job(job_id).manifest.updated_at
                )
                pending = reset_task(current, at=at)
                self.repository.replace_round_task(
                    job_id, current.content_fingerprint(), pending, claim
                )
            elif current.status in {RoundTaskStatus.FAILED, RoundTaskStatus.CANCELLED} and (
                current.round_id in retry_ids
            ):
                at = self._next_at(
                    current.updated_at, self.repository.load_job(job_id).manifest.updated_at
                )
                pending = reset_task(current, at=at)
                self.repository.replace_round_task(
                    job_id, current.content_fingerprint(), pending, claim
                )
            elif current.status is RoundTaskStatus.SUCCEEDED:
                # load_round_tasks already checked the task/result historical
                # closure.  This explicit read makes a missing claimed result
                # a stable failure before any resume write.
                self.repository.load_round_understanding(job_id, current.round_id)

        tasks = self.repository.load_round_tasks(job_id)
        self._replace_manifest(job_id, tasks, claim)
        self._append_event(
            job_id,
            claim,
            "round_tasks_reconciled",
            {"retry_round_ids": sorted(retry_ids)},
            tasks,
        )
        opened, timeline, _, configurations, _, transcripts = self._load_evidence(job_id)
        configuration_id = next(
            (
                value.configuration_snapshot_id
                for value in tasks
                if value.status in {RoundTaskStatus.PENDING, RoundTaskStatus.RETRY_WAIT}
            ),
            tasks[0].configuration_snapshot_id if tasks else "",
        )
        if not tasks:
            return PreparedRoundBatch(job_id, configuration_id, (), ())
        return self._runnable_batch(
            job_id,
            configuration_id,
            tasks,
            timeline,
            configurations,
            transcripts,
        )
