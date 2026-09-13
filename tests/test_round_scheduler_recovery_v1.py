"""Deterministic retry, cancellation, and lease-heartbeat tests."""

import asyncio
from datetime import datetime, timezone

import pytest

from cs2pov.application.round_scheduler import (
    RoundScheduler,
    RoundSchedulerSettings,
)
from cs2pov.application.round_worker import RoundWorkFailure
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job_task_state import (
    cancel_task,
    fail_task,
    retry_task,
    start_task,
    succeed_task,
)
from cs2pov.domain.job_tasks import (
    RetryPolicy,
    RoundAttemptStatus,
    RoundTaskError,
    RoundTaskStatus,
    RoundTranslationTask,
)
from cs2pov.storage.job_errors import JobRepositoryError


BASE = "2026-09-06T00:00:00.000000Z"
RETRY_CLOCK = datetime(2026, 9, 6, 0, 0, 2, tzinfo=timezone.utc)


class Session:
    def __init__(self, *, heartbeat_error=None):
        self.claim = object()
        self.heartbeat_error = heartbeat_error
        self.heartbeat_count = 0
        self.released = False

    def heartbeat(self):
        self.heartbeat_count += 1
        if self.heartbeat_error is not None:
            raise self.heartbeat_error

    def release(self):
        self.released = True


class Request:
    def __init__(self, task_id):
        self.task_id = task_id


class Prepared:
    def __init__(self, tasks):
        self.tasks = tuple(tasks)
        self.requests = tuple(Request(task.task_id) for task in tasks)


class Repository:
    def __init__(self, tasks, *, session=None):
        self.tasks = {task.task_id: task for task in tasks}
        self.session = session or Session()

    def acquire_write(self, job_id, *, lease_us):
        return self.session

    def load_round_tasks(self, job_id):
        return tuple(self.tasks.values())


class Coordinator:
    def __init__(self, repository, tasks, *, failure=None, success_ids=()):
        self.repository = repository
        self.tasks = tuple(tasks)
        self.failure = failure
        self.success_ids = set(success_ids)
        self.mark_count = {}
        self.failure_count = 0
        self.success_count = 0
        self.cancelled_ids = []
        self.next_second = 0
        self.resume_count = 0

    def prepare_translation(self, job_id, *, configuration_snapshot_id, claim):
        return Prepared(self.tasks)

    def reconcile_for_resume(self, job_id, *, retry_round_ids=(), claim):
        self.resume_count += 1
        return Prepared(self.repository.load_round_tasks(job_id))

    def _at(self, task):
        if task.status is RoundTaskStatus.RETRY_WAIT and self.next_second < 5:
            self.next_second = 5
        self.next_second += 1
        self.mark_count[task.task_id] = self.mark_count.get(task.task_id, 0) + 1
        return f"2026-09-06T00:00:{self.next_second:02d}.000000Z"

    def mark_running(self, task, *, attempt_id, claim):
        at = self._at(task)
        updated = start_task(task, attempt_id=attempt_id, at=at)
        self.repository.tasks[task.task_id] = updated
        return updated

    def checkpoint_success(self, task, result, *, claim):
        self.success_count += 1
        self.next_second += 1
        at = f"2026-09-06T00:00:{self.next_second:02d}.000000Z"
        updated = succeed_task(
            task, at=at, result_fingerprint="b" * 64
        )
        self.repository.tasks[task.task_id] = updated
        return updated

    def checkpoint_failure(self, task, failure, *, policy, claim):
        self.failure_count += 1
        self.next_second += 1
        at = f"2026-09-06T00:00:{self.next_second:02d}.000000Z"
        if failure.error.retryable:
            updated = retry_task(task, at=at, error=failure.error, policy=policy)
        else:
            updated = fail_task(task, at=at, error=failure.error)
        self.repository.tasks[task.task_id] = updated
        return updated

    def checkpoint_cancellation(self, task, *, claim):
        self.next_second += 1
        updated = cancel_task(
            task, at=f"2026-09-06T00:00:{self.next_second:02d}.000000Z"
        )
        self.repository.tasks[task.task_id] = updated
        self.cancelled_ids.append(task.task_id)
        return updated


class Worker:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []

    async def translate(self, request):
        self.calls.append(request.task_id)
        return await self.behavior(request)


def make_task(task_id="round-001"):
    return RoundTranslationTask.pending(
        task_id=task_id,
        round_id=task_id,
        input_fingerprint="a" * 64,
        configuration_snapshot_id="snapshot",
        updated_at=BASE,
    )


def settings(*, max_concurrency=1):
    return RoundSchedulerSettings(
        max_concurrency,
        10_000_000,
        1_000_000,
        RetryPolicy(2, 1_000_000, 8_000_000),
    )


def scheduler(repository, coordinator, worker, *, clock=None, sleep=None, ids=None):
    value = object.__new__(RoundScheduler)
    value.coordinator = coordinator
    value.worker = worker
    value.clock = clock or (lambda: RETRY_CLOCK)
    value.sleep = sleep or (lambda delay: asyncio.sleep(0))
    attempts = iter(ids or ("attempt-001", "attempt-002", "attempt-003"))
    value.attempt_id_factory = lambda: next(attempts)
    return value


def retry_failure(*, retry_after_us=3_000_000):
    return RoundWorkFailure(
        RoundTaskError(
            "provider_busy",
            "模型暂时繁忙。",
            "本回合尚未完成。",
            "稍后自动重试。",
            True,
            retry_after_us,
        )
    )


def test_retry_wait_honors_retry_after_and_starts_a_new_attempt(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_result",
        lambda request, result: None,
    )
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_failure",
        lambda request, failure: None,
    )
    repository = Repository([make_task()])
    coordinator = Coordinator(repository, tuple(repository.tasks.values()))
    failure = retry_failure()
    calls = 0

    async def behavior(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise failure
        return object()

    delays = []

    async def sleep(delay):
        delays.append(delay)

    worker = Worker(behavior)
    value = scheduler(
        repository,
        coordinator,
        worker,
        sleep=sleep,
        ids=("attempt-001", "attempt-002"),
    )
    report = asyncio.run(
        value.run("job", configuration_snapshot_id="snapshot", settings=settings())
    )

    task = report.tasks[0]
    assert calls == 2
    assert [delay for delay in delays if delay > 2] == [3.0]
    assert task.status is RoundTaskStatus.SUCCEEDED
    assert [attempt.status for attempt in task.attempts] == [
        RoundAttemptStatus.RETRYABLE_FAILED,
        RoundAttemptStatus.SUCCEEDED,
    ]
    assert [attempt.attempt_id for attempt in task.attempts] == [
        "attempt-001",
        "attempt-002",
    ]


def test_retry_exhaustion_does_not_invoke_worker_again(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_failure",
        lambda request, failure: None,
    )
    repository = Repository([make_task()])
    coordinator = Coordinator(repository, tuple(repository.tasks.values()))
    worker = Worker(lambda request: _raise(retry_failure()))
    value = scheduler(repository, coordinator, worker)
    exhausted_settings = RoundSchedulerSettings(
        1, 10_000_000, 1_000_000, RetryPolicy(1, 1_000_000, 8_000_000)
    )

    report = asyncio.run(
        value.run(
            "job",
            configuration_snapshot_id="snapshot",
            settings=exhausted_settings,
        )
    )

    task = report.tasks[0]
    assert len(worker.calls) == 1
    assert task.status is RoundTaskStatus.FAILED
    assert task.attempts[-1].status is RoundAttemptStatus.EXHAUSTED


def test_resume_waits_for_a_persisted_retry_window(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_result",
        lambda request, result: None,
    )
    pending = make_task()
    running = start_task(pending, attempt_id="attempt-001", at="2026-09-06T00:00:01.000000Z")
    retrying = retry_task(
        running,
        at="2026-09-06T00:00:02.000000Z",
        error=retry_failure().error,
        policy=RetryPolicy(2, 1_000_000, 8_000_000),
    )
    repository = Repository([retrying])
    coordinator = Coordinator(repository, [retrying])
    delays = []

    async def sleep(delay):
        delays.append(delay)

    worker = Worker(lambda request: _return(object()))
    value = scheduler(repository, coordinator, worker, sleep=sleep, ids=("attempt-002",))
    report = asyncio.run(
        value.run("job", configuration_snapshot_id="snapshot", settings=settings())
    )

    assert coordinator.resume_count == 1
    assert [delay for delay in delays if delay > 2] == [3.0]
    assert report.tasks[0].status is RoundTaskStatus.SUCCEEDED
    assert len(report.tasks[0].attempts) == 2


async def _return(value):
    return value


async def _raise(error):
    raise error


def test_cancellation_keeps_queued_tasks_pending_and_marks_active_task_cancelled(
    monkeypatch,
):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_result",
        lambda request, result: None,
    )
    tasks = [make_task("round-001"), make_task("round-002")]
    repository = Repository(tasks)
    coordinator = Coordinator(repository, tasks)
    started = asyncio.Event()
    release = asyncio.Event()

    async def behavior(request):
        started.set()
        await release.wait()
        return object()

    worker = Worker(behavior)
    value = scheduler(repository, coordinator, worker)
    cancel_event = asyncio.Event()

    async def run():
        pending = asyncio.create_task(
            value.run(
                "job",
                configuration_snapshot_id="snapshot",
                settings=settings(),
                cancel_event=cancel_event,
            )
        )
        await started.wait()
        cancel_event.set()
        return await pending

    report = asyncio.run(run())
    by_id = {task.task_id: task for task in report.tasks}
    assert report.cancelled
    assert by_id["round-001"].status is RoundTaskStatus.CANCELLED
    assert by_id["round-002"].status is RoundTaskStatus.PENDING
    assert worker.calls == ["round-001"]
    assert coordinator.cancelled_ids == ["round-001"]


def test_heartbeat_failure_stops_batch_and_preserves_completed_sibling(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_result",
        lambda request, result: None,
    )
    tasks = [make_task("round-001"), make_task("round-002")]
    heartbeat_error = JobRepositoryError(
        "job_write_interrupted",
        "写入租约已经失效。",
        "本批次已停止。",
        "events/.writer_claim/claim.json",
    )
    session = Session(heartbeat_error=heartbeat_error)
    repository = Repository(tasks, session=session)
    coordinator = Coordinator(repository, tasks)
    started = asyncio.Event()
    heartbeat_gate = asyncio.Event()
    blocked = asyncio.Event()

    async def behavior(request):
        if request.task_id == "round-002":
            started.set()
            await blocked.wait()
        return object()

    async def sleep(delay):
        await heartbeat_gate.wait()

    worker = Worker(behavior)
    value = scheduler(
        repository,
        coordinator,
        worker,
        sleep=sleep,
        ids=("attempt-001", "attempt-002"),
    )

    async def run():
        pending = asyncio.create_task(
                value.run(
                    "job",
                    configuration_snapshot_id="snapshot",
                    settings=settings(max_concurrency=2),
                )
        )
        await started.wait()
        heartbeat_gate.set()
        return await pending

    with pytest.raises(JobRepositoryError) as caught:
        asyncio.run(run())

    assert caught.value.code == "job_write_interrupted"
    assert repository.tasks["round-001"].status is RoundTaskStatus.SUCCEEDED
    assert repository.tasks["round-002"].status is RoundTaskStatus.RUNNING
    assert session.heartbeat_count == 1
    assert session.released


def test_heartbeat_sleep_failure_is_reported_and_cancels_work(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_result",
        lambda request, result: None,
    )
    repository = Repository([make_task()])
    coordinator = Coordinator(repository, tuple(repository.tasks.values()))
    started = asyncio.Event()
    blocked = asyncio.Event()

    async def behavior(request):
        started.set()
        await blocked.wait()
        return object()

    async def sleep(delay):
        raise RuntimeError("heartbeat sleeper failed")

    worker = Worker(behavior)
    value = scheduler(repository, coordinator, worker, sleep=sleep)

    async def run():
        pending = asyncio.create_task(
            value.run("job", configuration_snapshot_id="snapshot", settings=settings())
        )
        await started.wait()
        return await pending

    with pytest.raises(RuntimeError, match="heartbeat sleeper failed"):
        asyncio.run(run())
    assert repository.session.released


def test_default_attempt_ids_are_unique_across_scheduler_instances():
    first = RoundScheduler._default_attempt_id()
    second = RoundScheduler._default_attempt_id()
    assert first != second


def test_invalid_scheduler_clock_is_rejected_before_retry_sleep(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_failure",
        lambda request, failure: None,
    )
    repository = Repository([make_task()])
    coordinator = Coordinator(repository, tuple(repository.tasks.values()))
    worker = Worker(lambda request: _raise(retry_failure()))
    value = scheduler(repository, coordinator, worker, clock=lambda: "invalid")

    with pytest.raises(ExceptionGroup) as caught:
        asyncio.run(
            value.run("job", configuration_snapshot_id="snapshot", settings=settings())
        )
    assert any(
        isinstance(error, DomainSchemaError)
        for error in caught.value.exceptions
    )
