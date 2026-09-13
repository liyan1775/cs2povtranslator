"""Bounded asynchronous execution for prepared round work."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job_tasks import (
    RetryPolicy,
    RoundTaskError,
    RoundTaskStatus,
    RoundTranslationTask,
)
from cs2pov.domain.schema import require_path_identifier
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
        self,
        coordinator: JobRoundCoordinator,
        worker: RoundTranslationWorker,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        attempt_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(coordinator, JobRoundCoordinator):
            raise TypeError("coordinator 必须是 JobRoundCoordinator。")
        if not hasattr(worker, "translate") or not callable(worker.translate):
            raise TypeError("worker 必须实现 translate。")
        self.coordinator = coordinator
        self.worker = worker
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.attempt_id_factory = attempt_id_factory or self._default_attempt_id

    @classmethod
    def _default_attempt_id(cls) -> str:
        return f"attempt-scheduler-{uuid.uuid4().hex}"

    def _attempt_id(self) -> str:
        factory = getattr(self, "attempt_id_factory", self._default_attempt_id)
        value = factory()
        try:
            return require_path_identifier(value, "attempt_id")
        except Exception as exc:
            raise DomainSchemaError(
                "domain_field_invalid",
                "尝试标识无效。",
                "请检查调度器设置后重试。",
                "attempt_id",
            ) from exc

    async def _sleep_until(self, retry_at: str) -> None:
        from .job_coordinator import parse_canonical_utc

        clock = getattr(self, "clock", lambda: datetime.now(timezone.utc))
        sleep = getattr(self, "sleep", asyncio.sleep)
        now = clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise DomainSchemaError(
                "domain_field_invalid",
                "调度器时钟无效。",
                "请检查系统时间后重试。",
                "clock",
            )
        delay = (
            parse_canonical_utc(retry_at) - now.astimezone(timezone.utc)
        ).total_seconds()
        if delay > 0:
            await sleep(delay)

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
        mutation_lock = asyncio.Lock()
        worker_tasks: list[asyncio.Task] = []
        batch_done = asyncio.Event()
        cancelled = False
        heartbeat_error: Exception | None = None

        async def mutate(operation, *args, **kwargs):
            async with mutation_lock:
                return operation(*args, claim=session.claim, **kwargs)

        async def heartbeat_loop() -> None:
            nonlocal heartbeat_error
            while not batch_done.is_set():
                try:
                    sleeper = asyncio.create_task(
                        getattr(self, "sleep", asyncio.sleep)(
                            settings.heartbeat_interval_us / 1_000_000
                        )
                    )
                    done_wait = asyncio.create_task(batch_done.wait())
                    finished, pending = await asyncio.wait(
                        {sleeper, done_wait}, return_when=asyncio.FIRST_COMPLETED
                    )
                except Exception as exc:
                    heartbeat_error = exc
                    for task in worker_tasks:
                        if not task.done():
                            task.cancel()
                    return
                if sleeper in finished:
                    try:
                        sleeper.result()
                    except Exception as exc:
                        heartbeat_error = exc
                        for task in worker_tasks:
                            if not task.done():
                                task.cancel()
                        return
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if batch_done.is_set():
                    return
                try:
                    async with mutation_lock:
                        session.heartbeat()
                except Exception as exc:
                    heartbeat_error = exc
                    for task in worker_tasks:
                        if not task.done():
                            task.cancel()
                    return

        async def cancellation_loop() -> None:
            if cancel_event is None:
                await batch_done.wait()
                return
            cancel_wait = asyncio.create_task(cancel_event.wait())
            done_wait = asyncio.create_task(batch_done.wait())
            try:
                finished, _ = await asyncio.wait(
                    {cancel_wait, done_wait}, return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_wait in finished and not batch_done.is_set():
                    for task in worker_tasks:
                        if not task.done():
                            task.cancel()
            finally:
                for task in (cancel_wait, done_wait):
                    if not task.done():
                        task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        try:
            existing = repository.load_round_tasks(job_id)
            if retry_round_ids or existing and any(
                task.status in {RoundTaskStatus.RUNNING, RoundTaskStatus.RETRY_WAIT}
                for task in existing
            ):
                prepared = await mutate(
                    self.coordinator.reconcile_for_resume,
                    job_id,
                    retry_round_ids=retry_round_ids,
                )
            else:
                prepared = await mutate(
                    self.coordinator.prepare_translation,
                    job_id,
                    configuration_snapshot_id=configuration_snapshot_id,
                )
            requests_by_id = {request.task_id: request for request in prepared.requests}
            task_by_id = {task.task_id: task for task in prepared.tasks}
            semaphore = asyncio.Semaphore(settings.max_concurrency)

            async def checkpoint_failure(running, failure):
                updated = await mutate(
                    self.coordinator.checkpoint_failure,
                    running,
                    failure,
                    policy=settings.retry_policy,
                )
                return running if updated is None else updated

            async def run_one(task_id: str) -> None:
                nonlocal cancelled
                request = requests_by_id[task_id]
                task = task_by_id[task_id]
                running: RoundTranslationTask | None = (
                    task if task.status is RoundTaskStatus.RETRY_WAIT else None
                )
                entered = False
                try:
                    async with semaphore:
                        entered = True
                        if cancel_event is not None and cancel_event.is_set():
                            cancelled = True
                            if running is not None:
                                running = await mutate(
                                    self.coordinator.checkpoint_cancellation,
                                    running,
                                )
                            return
                        if running is not None:
                            await self._sleep_until(running.next_retry_at)
                            if cancel_event is not None and cancel_event.is_set():
                                cancelled = True
                                raise asyncio.CancelledError
                        running = await mutate(
                            self.coordinator.mark_running,
                            running or task,
                            attempt_id=self._attempt_id(),
                        )
                        while True:
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
                                running = await checkpoint_failure(running, failure)
                            except (DomainSchemaError, TypeError, ValueError):
                                running = await checkpoint_failure(
                                    running,
                                    _safe_failure(
                                        "round_task_output_mismatch",
                                        "回合工作结果不符合约定。",
                                        "本回合未保存。",
                                        "请检查模型适配器后重试。",
                                    ),
                                )
                            except Exception:
                                running = await checkpoint_failure(
                                    running,
                                    _safe_failure(
                                        "round_task_worker_error",
                                        "回合工作执行失败。",
                                        "本回合未保存。",
                                        "请检查模型适配器后重试。",
                                    ),
                                )
                            else:
                                try:
                                    validate_round_work_result(request, result)
                                except (DomainSchemaError, TypeError, ValueError):
                                    running = await checkpoint_failure(
                                        running,
                                        _safe_failure(
                                            "round_task_output_mismatch",
                                            "回合工作结果不符合约定。",
                                            "本回合未保存。",
                                            "请检查模型适配器后重试。",
                                        ),
                                    )
                                else:
                                    await mutate(
                                        self.coordinator.checkpoint_success,
                                        running,
                                        result,
                                    )
                                    break
                            if running.status is not RoundTaskStatus.RETRY_WAIT:
                                break
                            await self._sleep_until(running.next_retry_at)
                            if cancel_event is not None and cancel_event.is_set():
                                cancelled = True
                                raise asyncio.CancelledError
                            running = await mutate(
                                self.coordinator.mark_running,
                                running,
                                attempt_id=self._attempt_id(),
                            )
                except asyncio.CancelledError:
                    cancelled = True
                    if running is not None and heartbeat_error is None:
                        await mutate(
                            self.coordinator.checkpoint_cancellation,
                            running,
                        )
                    raise
                finally:
                    if entered:
                        async with completion_lock:
                            if task_id not in completions:
                                completions.append(task_id)

            heartbeat_task = asyncio.create_task(heartbeat_loop())
            cancellation_task = asyncio.create_task(cancellation_loop())
            try:
                async with asyncio.TaskGroup() as group:
                    for task_id in requests_by_id:
                        worker_tasks.append(group.create_task(run_one(task_id)))
            finally:
                batch_done.set()
                await asyncio.gather(
                    heartbeat_task, cancellation_task, return_exceptions=True
                )
            if heartbeat_error is not None:
                raise heartbeat_error
            final_tasks = repository.load_round_tasks(job_id)
            return RoundBatchReport(final_tasks, tuple(completions), cancelled)
        finally:
            session.release()
