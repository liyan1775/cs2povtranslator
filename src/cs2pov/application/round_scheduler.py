"""Bounded asynchronous execution for prepared round work."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job_tasks import RetryPolicy, RoundTaskError, RoundTranslationTask
from cs2pov.storage.job_errors import JobRepositoryError

from .job_coordinator import JobRoundCoordinator
from .round_worker import (
    RoundTranslationWorker,
    RoundWorkFailure,
    validate_round_work_failure,
    validate_round_work_result,
)


def _invalid(path: str, message: str = "调度器设置无效。") -> None:
    raise DomainSchemaError(
        "domain_field_invalid", message, "请修正设置后重试。", path
    )


@dataclass(frozen=True, slots=True)
class RoundSchedulerSettings:
    max_concurrency: int
    claim_lease_us: int
    heartbeat_interval_us: int
    retry_policy: RetryPolicy

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or not 1 <= self.max_concurrency <= 64:
            _invalid("max_concurrency")
        if type(self.claim_lease_us) is not int or not 1_000_000 <= self.claim_lease_us <= 86_400_000_000:
            _invalid("claim_lease_us")
        if type(self.heartbeat_interval_us) is not int or not 1 <= self.heartbeat_interval_us < self.claim_lease_us:
            _invalid("heartbeat_interval_us")
        if self.heartbeat_interval_us * 2 >= self.claim_lease_us:
            _invalid("heartbeat_interval_us")
        if type(self.retry_policy) is not RetryPolicy:
            _invalid("retry_policy")


@dataclass(frozen=True, slots=True)
class RoundBatchReport:
    tasks: tuple[RoundTranslationTask, ...]
    completion_order: tuple[str, ...]
    cancelled: bool

    def __post_init__(self) -> None:
        if not isinstance(self.tasks, (tuple, list)):
            _invalid("tasks")
        if not isinstance(self.completion_order, (tuple, list)):
            _invalid("completion_order")
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(self, "completion_order", tuple(self.completion_order))
        if any(type(task) is not RoundTranslationTask for task in self.tasks):
            _invalid("tasks")
        if any(not isinstance(value, str) for value in self.completion_order):
            _invalid("completion_order")
        if len(set(self.completion_order)) != len(self.completion_order):
            _invalid("completion_order")
        if type(self.cancelled) is not bool:
            _invalid("cancelled")


def _safe_failure(code: str, message: str, impact: str, suggestion: str) -> RoundWorkFailure:
    return RoundWorkFailure(
        RoundTaskError(code, message, impact, suggestion, False, None)
    )


class RoundScheduler:
    def __init__(
        self, coordinator: JobRoundCoordinator, worker: RoundTranslationWorker
    ) -> None:
        if not isinstance(coordinator, JobRoundCoordinator):
            raise TypeError("coordinator 必须是 JobRoundCoordinator。")
        if not hasattr(worker, "translate") or not callable(worker.translate):
            raise TypeError("worker 必须实现 translate。")
        self.coordinator = coordinator
        self.worker = worker

    async def run(
        self,
        job_id: str,
        *,
        configuration_snapshot_id: str,
        settings: RoundSchedulerSettings,
        cancel_event: asyncio.Event | None = None,
        retry_round_ids: tuple[str, ...] = (),
    ) -> RoundBatchReport:
        if not isinstance(settings, RoundSchedulerSettings):
            _invalid("settings")
        if cancel_event is not None and not isinstance(cancel_event, asyncio.Event):
            _invalid("cancel_event")
        repository = self.coordinator.repository
        session = repository.acquire_write(job_id, lease_us=settings.claim_lease_us)
        completions: list[str] = []
        completion_lock = asyncio.Lock()
        cancelled = False
        try:
            prepared = self.coordinator.prepare_translation(
                job_id,
                configuration_snapshot_id=configuration_snapshot_id,
                claim=session.claim,
            )
            requests_by_id = {request.task_id: request for request in prepared.requests}
            task_by_id = {task.task_id: task for task in prepared.tasks}
            semaphore = asyncio.Semaphore(settings.max_concurrency)

            async def run_one(task_id: str) -> None:
                nonlocal cancelled
                request = requests_by_id[task_id]
                task = task_by_id[task_id]
                async with semaphore:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        return
                    running = self.coordinator.mark_running(
                        task, attempt_id=f"{task_id}-attempt-1", claim=session.claim
                    )
                    try:
                        result = await self.worker.translate(request)
                    except asyncio.CancelledError:
                        raise
                    except RoundWorkFailure as failure:
                        try:
                            validate_round_work_failure(request, failure)
                        except (DomainSchemaError, TypeError, ValueError):
                            failure = _safe_failure(
                                "round_task_output_mismatch",
                                "回合工作结果不符合约定。",
                                "本回合未保存。",
                                "请检查模型适配器后重试。",
                            )
                        self.coordinator.checkpoint_failure(
                            running,
                            failure,
                            policy=settings.retry_policy,
                            claim=session.claim,
                        )
                    except (DomainSchemaError, TypeError, ValueError):
                        failure = _safe_failure(
                            "round_task_output_mismatch",
                            "回合工作结果不符合约定。",
                            "本回合未保存。",
                            "请检查模型适配器后重试。",
                        )
                        self.coordinator.checkpoint_failure(
                            running,
                            failure,
                            policy=settings.retry_policy,
                            claim=session.claim,
                        )
                    except Exception:
                        failure = _safe_failure(
                            "round_task_worker_error",
                            "回合工作执行失败。",
                            "本回合未保存。",
                            "请检查模型适配器后重试。",
                        )
                        self.coordinator.checkpoint_failure(
                            running,
                            failure,
                            policy=settings.retry_policy,
                            claim=session.claim,
                        )
                    else:
                        try:
                            validate_round_work_result(request, result)
                        except (DomainSchemaError, TypeError, ValueError):
                            failure = _safe_failure(
                                "round_task_output_mismatch",
                                "回合工作结果不符合约定。",
                                "本回合未保存。",
                                "请检查模型适配器后重试。",
                            )
                            self.coordinator.checkpoint_failure(
                                running,
                                failure,
                                policy=settings.retry_policy,
                                claim=session.claim,
                            )
                        else:
                            self.coordinator.checkpoint_success(
                                running, result, claim=session.claim
                            )
                    finally:
                        if task_id not in completions:
                            async with completion_lock:
                                if task_id not in completions:
                                    completions.append(task_id)

            async with asyncio.TaskGroup() as group:
                for task_id in requests_by_id:
                    group.create_task(run_one(task_id))

            final_tasks = repository.load_round_tasks(job_id)
            return RoundBatchReport(final_tasks, tuple(completions), cancelled)
        finally:
            try:
                session.release()
            except JobRepositoryError:
                raise
