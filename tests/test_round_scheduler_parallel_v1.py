"""Behavioral tests for bounded round scheduling."""

import asyncio

import pytest

from cs2pov.application.round_scheduler import RoundScheduler, RoundSchedulerSettings
from cs2pov.domain.job_task_state import start_task, succeed_task, fail_task
from cs2pov.domain.job_tasks import RetryPolicy, RoundTaskStatus, RoundTranslationTask


class Session:
    def __init__(self):
        self.claim = object()
        self.released = False

    def release(self):
        self.released = True


class Request:
    def __init__(self, task_id):
        self.task_id = task_id


class Prepared:
    def __init__(self, tasks):
        self.tasks = tuple(tasks)
        self.requests = tuple(Request(task.task_id) for task in tasks)


class FakeRepository:
    def __init__(self, tasks):
        self.tasks = {task.task_id: task for task in tasks}
        self.session = Session()

    def acquire_write(self, job_id, *, lease_us):
        return self.session

    def load_round_tasks(self, job_id):
        return tuple(self.tasks.values())


class FakeCoordinator:
    def __init__(self, repository, tasks):
        self.repository = repository
        self.tasks = tasks
        self.started = []
        self.finished = []

    def prepare_translation(self, job_id, *, configuration_snapshot_id, claim):
        return Prepared(self.tasks)

    def mark_running(self, task, *, attempt_id, claim):
        task = start_task(
            task,
            attempt_id=attempt_id,
            at="2026-09-06T00:00:01.000000Z",
        )
        self.repository.tasks[task.task_id] = task
        self.started.append(task.task_id)
        return task

    def checkpoint_success(self, task, result, *, claim):
        task = succeed_task(
            task,
            at="2026-09-06T00:00:02.000000Z",
            result_fingerprint="b" * 64,
        )
        self.repository.tasks[task.task_id] = task
        self.finished.append(task.task_id)

    def checkpoint_failure(self, task, failure, *, policy, claim):
        task = fail_task(
            task,
            at="2026-09-06T00:00:02.000000Z",
            error=failure.error,
        )
        self.repository.tasks[task.task_id] = task
        self.finished.append(task.task_id)


class FakeWorker:
    def __init__(self, gates=None, error_id=None):
        self.gates = gates or {}
        self.error_id = error_id
        self.inside = 0
        self.maximum = 0

    async def translate(self, request):
        self.inside += 1
        self.maximum = max(self.maximum, self.inside)
        try:
            gate = self.gates.get(request.task_id)
            if gate is not None:
                await gate.wait()
            if request.task_id == self.error_id:
                raise RuntimeError("raw adapter detail")
            return object()
        finally:
            self.inside -= 1


def settings(limit=2):
    return RoundSchedulerSettings(limit, 10_000_000, 1_000_000, RetryPolicy(1, 1, 8_000_000))


def make_tasks(*identities):
    return [
        RoundTranslationTask.pending(
            task_id=identity,
            round_id=identity,
            input_fingerprint="a" * 64,
            configuration_snapshot_id="snapshot",
            updated_at=f"2026-09-06T00:00:00.{index:06d}Z",
        )
        for index, identity in enumerate(identities, 1)
    ]


def test_scheduler_bounds_parallelism_and_returns_timeline_order(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_result",
        lambda request, result: None,
    )
    tasks = make_tasks("round-001", "round-002", "round-003")
    repository = FakeRepository(tasks)
    coordinator = FakeCoordinator(repository, tasks)
    gates = {task.task_id: asyncio.Event() for task in tasks}
    worker = FakeWorker(gates)
    scheduler = object.__new__(RoundScheduler)
    scheduler.coordinator = coordinator
    scheduler.worker = worker
    async def run():
        running = asyncio.create_task(
            scheduler.run("job", configuration_snapshot_id="snapshot", settings=settings())
        )
        while worker.maximum < 2:
            await asyncio.sleep(0)
        gates["round-002"].set()
        await asyncio.sleep(0)
        gates["round-001"].set()
        await asyncio.sleep(0)
        gates["round-003"].set()
        return await running

    report = asyncio.run(run())
    assert worker.maximum <= 2
    assert [task.task_id for task in report.tasks] == ["round-001", "round-002", "round-003"]
    assert set(report.completion_order) == {"round-001", "round-002", "round-003"}
    assert repository.session.released


def test_one_worker_exception_isolated_and_raw_detail_not_persisted(monkeypatch):
    monkeypatch.setattr(
        "cs2pov.application.round_scheduler.validate_round_work_result",
        lambda request, result: None,
    )
    tasks = make_tasks("round-001", "round-002")
    repository = FakeRepository(tasks)
    coordinator = FakeCoordinator(repository, tasks)
    worker = FakeWorker(error_id="round-001")
    scheduler = object.__new__(RoundScheduler)
    scheduler.coordinator = coordinator
    scheduler.worker = worker

    report = asyncio.run(
        scheduler.run("job", configuration_snapshot_id="snapshot", settings=settings())
    )
    assert [task.status for task in report.tasks] == [RoundTaskStatus.FAILED, RoundTaskStatus.SUCCEEDED]
    assert "raw adapter detail" not in repr(report)


def test_scheduler_settings_reject_invalid_limits():
    for values in [
        (True, 10_000_000, 1_000_000),
        (0, 10_000_000, 1_000_000),
        (65, 10_000_000, 1_000_000),
        (2, 1_000_000, 1_000_000),
        (2, 10_000_000, 5_000_000),
    ]:
        with pytest.raises(Exception):
            RoundSchedulerSettings(*values, RetryPolicy(1, 1, 8_000_000))
