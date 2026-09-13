"""Behavioral tests for Task 3 durable round coordination."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from cs2pov.application.job_coordinator import (
    JobRoundCoordinator,
    PreparedRoundBatch,
    next_persisted_timestamp,
    parse_canonical_utc,
)
from cs2pov.domain.job import JobPhase, JobRunStatus
from cs2pov.domain.job_task_state import start_task, succeed_task
from cs2pov.domain.job_tasks import (
    RetryPolicy,
    RoundTaskError,
    RoundTaskSpec,
    RoundTaskStatus,
    RoundTranslationTask,
)
from cs2pov.storage.job_errors import JobRepositoryError
from test_job_repository_language_shards_v1 import (
    _persist_closed_language_graph,
    _language_values,
    _seed,
    _snapshot_tree,
)


NOW = datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc)


class FrozenClock:
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


def _coordinator(tmp_path, *, closed=True):
    if closed:
        workspace, repository, claim, values = _persist_closed_language_graph(tmp_path)
        clock = repository.clock
    else:
        workspace, repository, clock, claim, _ = _seed(tmp_path)
        values = _language_values(repository.load_job("job-language").source.asset_id)
    opened = repository.load_job("job-language")
    clock.advance()
    repository.replace_manifest(
        "job-language",
        opened.manifest.content_fingerprint(),
        replace(
            opened.manifest,
            phase=JobPhase.CONTEXT_READY,
            run_status=JobRunStatus.SUCCEEDED,
            updated_at=clock().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        ),
        claim,
    )
    return workspace, repository, clock, claim, values, JobRoundCoordinator(
        repository, clock=clock, event_id_factory=iter_event_ids().__next__
    )


def iter_event_ids():
    index = 0
    while True:
        index += 1
        yield f"event-coordinator-{index:03d}"


def _prepare_context(repository, claim, values):
    opened = repository.load_job("job-language")
    for configuration in values[5:6]:
        opened = repository.register_model_configuration(
            "job-language", configuration, opened.manifest.content_fingerprint(), claim
        )
    repository.save_demo_timeline("job-language", values[0], claim)
    repository.save_voice_activities("job-language", (values[1],), claim)
    repository.save_transcript_round("job-language", "round-001", (values[4],), claim)
    repository.save_unassigned_transcript("job-language", (), claim)


def test_prepare_builds_privacy_minimal_requests_and_reuses_success(tmp_path):
    workspace, repository, _, claim, values, coordinator = _coordinator(tmp_path)
    # The closed fixture already contains the source graph, but no task shard.
    batch = coordinator.prepare_translation(
        "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
    )

    assert isinstance(batch, PreparedRoundBatch)
    assert batch.configuration_snapshot_id == values[5].snapshot_id
    assert len(batch.tasks) == 1
    assert len(batch.requests) == 1
    assert batch.requests[0].task_input_fingerprint == batch.tasks[0].input_fingerprint
    assert repository.load_job("job-language").manifest.phase is JobPhase.CONTEXT_READY
    assert repository.load_job("job-language").manifest.run_status is JobRunStatus.SUCCEEDED

    # A second preparation is idempotent and reuses the persisted pending task.
    again = coordinator.prepare_translation(
        "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
    )
    assert again == batch
    assert workspace.jobs_dir.exists()


def test_checkpoint_success_publishes_in_order_and_advances_manifest(tmp_path):
    _, repository, clock, claim, values, coordinator = _coordinator(tmp_path)
    batch = coordinator.prepare_translation(
        "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
    )
    running = coordinator.mark_running(batch.tasks[0], attempt_id="attempt-001", claim=claim)
    from cs2pov.application.round_worker import RoundWorkResult

    outcome = RoundWorkResult(values[7], (values[6],))
    succeeded = coordinator.checkpoint_success(running, outcome, claim=claim)

    assert succeeded.status is RoundTaskStatus.SUCCEEDED
    assert repository.load_job("job-language").manifest.phase is JobPhase.UNDERSTOOD_TRANSLATED
    assert repository.load_job("job-language").manifest.run_status is JobRunStatus.SUCCEEDED
    assert repository.read_events("job-language").events[-1].event_type == "round_task_succeeded"
    assert parse_canonical_utc(succeeded.updated_at) < parse_canonical_utc(
        repository.load_job("job-language").manifest.updated_at
    )


def test_frozen_clock_allocates_strictly_increasing_task_and_manifest_times(tmp_path):
    _, repository, _, claim, values, coordinator = _coordinator(tmp_path)
    batch = coordinator.prepare_translation(
        "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
    )
    running = coordinator.mark_running(batch.tasks[0], attempt_id="attempt-001", claim=claim)
    succeeded = coordinator.checkpoint_success(
        running,
        __import__("cs2pov.application.round_worker", fromlist=["RoundWorkResult"]).RoundWorkResult(
            values[7], (values[6],)
        ),
        claim=claim,
    )
    manifest = repository.load_job("job-language").manifest
    assert len({batch.tasks[0].updated_at, running.updated_at, succeeded.updated_at, manifest.updated_at}) == 4
    assert next_persisted_timestamp(
        NOW, "2026-09-06T00:00:00.000000Z"
    ) == "2026-09-06T00:00:00.000001Z"


def test_timestamp_helpers_reject_naive_clock_and_bad_persisted_values():
    with pytest.raises(ValueError):
        next_persisted_timestamp(datetime(2026, 9, 6), "2026-09-06T00:00:00.000000Z")
    with pytest.raises(ValueError):
        parse_canonical_utc("2026-09-06T00:00:00Z")


def test_invalidation_preflights_running_task_before_any_write(tmp_path, monkeypatch):
    workspace, repository, clock, claim, values, coordinator = _coordinator(tmp_path)
    batch = coordinator.prepare_translation(
        "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
    )
    coordinator.mark_running(batch.tasks[0], attempt_id="attempt-001", claim=claim)
    changed = RoundTaskSpec(
        "round-001", "round-001", "f" * 64, values[5].snapshot_id
    )
    monkeypatch.setattr(coordinator, "_desired_specs", lambda *args: (changed,))
    before = _snapshot_tree(workspace.jobs_dir / "job-language")

    with pytest.raises(JobRepositoryError, match="运行中的任务"):
        coordinator.prepare_translation(
            "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
        )

    assert _snapshot_tree(workspace.jobs_dir / "job-language") == before


def test_resume_preflights_all_successes_before_rewriting_running_tasks(
    tmp_path, monkeypatch
):
    workspace, repository, clock, claim, values, coordinator = _coordinator(tmp_path)
    batch = coordinator.prepare_translation(
        "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
    )
    running = coordinator.mark_running(batch.tasks[0], attempt_id="attempt-001", claim=claim)
    missing_success = RoundTranslationTask.pending(
        task_id="round-002",
        round_id="round-002",
        input_fingerprint=running.input_fingerprint,
        configuration_snapshot_id=running.configuration_snapshot_id,
        updated_at="2026-09-06T00:00:00.000001Z",
    )
    missing_success = succeed_task(
        start_task(
            missing_success,
            attempt_id="attempt-002",
            at="2026-09-06T00:00:00.000002Z",
        ),
        at="2026-09-06T00:00:00.000003Z",
        result_fingerprint="e" * 64,
    )
    real_load_tasks = repository.load_round_tasks
    real_load_understanding = repository.load_round_understanding

    def load_two_tasks(job_id):
        return (*real_load_tasks(job_id), missing_success)

    def missing_result(job_id, round_id):
        if round_id == "round-002":
            raise JobRepositoryError(
                "job_shard_missing", "结果缺失。", "请恢复后重试。", "understanding"
            )
        return real_load_understanding(job_id, round_id)

    monkeypatch.setattr(repository, "load_round_tasks", load_two_tasks)
    monkeypatch.setattr(repository, "load_round_understanding", missing_result)
    before = _snapshot_tree(workspace.jobs_dir / "job-language")

    with pytest.raises(JobRepositoryError, match="结果缺失"):
        coordinator.reconcile_for_resume("job-language", claim=claim)

    assert _snapshot_tree(workspace.jobs_dir / "job-language") == before
    assert real_load_tasks("job-language")[0].status is RoundTaskStatus.RUNNING


@pytest.mark.parametrize("status", ("pending", "succeeded", "retry_wait"))
def test_resume_rejects_explicit_retry_for_non_retryable_status(tmp_path, status):
    workspace, repository, _, claim, values, coordinator = _coordinator(tmp_path)
    batch = coordinator.prepare_translation(
        "job-language", configuration_snapshot_id=values[5].snapshot_id, claim=claim
    )
    if status == "succeeded":
        running = coordinator.mark_running(
            batch.tasks[0], attempt_id="attempt-001", claim=claim
        )
        coordinator.checkpoint_success(
            running,
            __import__(
                "cs2pov.application.round_worker", fromlist=["RoundWorkResult"]
            ).RoundWorkResult(values[7], (values[6],)),
            claim=claim,
        )
    elif status == "retry_wait":
        running = coordinator.mark_running(
            batch.tasks[0], attempt_id="attempt-001", claim=claim
        )
        from cs2pov.application.round_worker import RoundWorkFailure

        coordinator.checkpoint_failure(
            running,
            RoundWorkFailure(
                RoundTaskError(
                    "provider_busy",
                    "服务繁忙。",
                    "本回合未完成。",
                    "请稍后重试。",
                    True,
                    1_000_000,
                )
            ),
            policy=RetryPolicy(2, 1_000_000, 8_000_000),
            claim=claim,
        )
    before = _snapshot_tree(workspace.jobs_dir / "job-language")

    with pytest.raises(JobRepositoryError, match="只有失败或取消"):
        coordinator.reconcile_for_resume(
            "job-language", claim=claim, retry_round_ids=("round-001",)
        )

    assert _snapshot_tree(workspace.jobs_dir / "job-language") == before
