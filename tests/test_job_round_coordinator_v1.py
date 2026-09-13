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
from cs2pov.domain.job_tasks import RoundTaskStatus
from test_job_repository_language_shards_v1 import (
    _persist_closed_language_graph,
    _language_values,
    _seed,
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
    workspace, repository, clock, claim, values, coordinator = _coordinator(tmp_path)
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
