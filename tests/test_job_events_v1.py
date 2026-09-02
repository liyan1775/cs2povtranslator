from __future__ import annotations

import pytest

from cs2pov.domain.job import JobEvent
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from test_job_repository_language_shards_v1 import _seed, _snapshot_tree


def _event(event_id: str, job_id: str, run_id: str) -> JobEvent:
    return JobEvent(
        event_id,
        job_id,
        run_id,
        "2026-09-01T08:00:00.000000Z",
        "round_completed",
        {"round_id": "round-001"},
    )


def test_events_append_as_canonical_fsynced_records_and_reopen_in_order(tmp_path):
    workspace, repository, _, claim, _ = _seed(tmp_path)
    first = _event("event-001", "job-language", claim.run_id)
    second = _event("event-002", "job-language", claim.run_id)

    repository.append_event("job-language", first, claim)
    repository.append_event("job-language", second, claim)

    path = workspace.jobs_dir / "job-language/events/job_events.jsonl"
    assert path.read_bytes() == (
        b'{"event_id":"event-001","event_type":"round_completed",'
        b'"job_id":"job-language","occurred_at":"2026-09-01T08:00:00.000000Z",'
        b'"payload":{"round_id":"round-001"},'
        b'"run_id":"run-44444444444444448444444444444444","schema_version":1}\n'
        b'{"event_id":"event-002","event_type":"round_completed",'
        b'"job_id":"job-language","occurred_at":"2026-09-01T08:00:00.000000Z",'
        b'"payload":{"round_id":"round-001"},'
        b'"run_id":"run-44444444444444448444444444444444","schema_version":1}\n'
    )
    fresh = FileSystemJobRepository(workspace, repository.demo_assets)
    before = _snapshot_tree(workspace.jobs_dir / "job-language")
    reopened = fresh.read_events("job-language")

    assert reopened.events == (first, second)
    assert not reopened.incomplete_tail
    assert reopened.issues == ()
    assert _snapshot_tree(workspace.jobs_dir / "job-language") == before


def test_event_append_requires_owner_identity_and_unique_event_id(tmp_path):
    workspace, repository, _, claim, _ = _seed(tmp_path)
    first = _event("event-001", "job-language", claim.run_id)
    repository.append_event("job-language", first, claim)
    path = workspace.jobs_dir / "job-language/events/job_events.jsonl"
    original = path.read_bytes()
    fake_claim = claim.__class__(
        claim.job_id,
        "run-not-owner",
        claim.process_id,
        claim.acquired_at,
        claim.heartbeat_at,
        claim.lease_expires_at,
    )

    cases = (
        (_event("event-002", "job-language", claim.run_id), fake_claim, "job_write_interrupted"),
        (_event("event-002", "job-other", claim.run_id), claim, "job_shard_invalid"),
        (_event("event-002", "job-language", "run-other"), claim, "job_shard_invalid"),
        (first, claim, "job_shard_invalid"),
    )
    for event, candidate_claim, expected_code in cases:
        with pytest.raises(JobRepositoryError) as exc_info:
            repository.append_event(
                "job-language", event, candidate_claim
            )
        assert exc_info.value.code == expected_code
        assert path.read_bytes() == original


def test_incomplete_tail_isolated_in_read_and_inspection_without_mutation(tmp_path):
    workspace, repository, _, claim, _ = _seed(tmp_path)
    first = _event("event-001", "job-language", claim.run_id)
    repository.append_event("job-language", first, claim)
    path = workspace.jobs_dir / "job-language/events/job_events.jsonl"
    complete_prefix = path.read_bytes()
    valid_without_newline = (
        b'{"event_id":"event-002","event_type":"round_completed",'
        b'"job_id":"job-language","occurred_at":"2026-09-01T08:00:00.000000Z",'
        b'"payload":{},"run_id":"run-44444444444444448444444444444444",'
        b'"schema_version":1}'
    )
    path.write_bytes(complete_prefix + valid_without_newline)
    before = _snapshot_tree(workspace.jobs_dir / "job-language")

    result = repository.read_events("job-language")
    inspection = repository.inspect_job("job-language")

    assert result.events == (first,)
    assert result.incomplete_tail
    assert tuple(issue.code for issue in result.issues) == (
        "job_event_tail_incomplete",
    )
    assert inspection.events == (first,)
    assert inspection.event_tail_incomplete
    assert inspection.entry.healthy
    assert any(
        issue.code == "job_event_tail_incomplete"
        and issue.severity == "warning"
        and issue.logical_path == "events/job_events.jsonl"
        for issue in inspection.entry.issues
    )
    assert _snapshot_tree(workspace.jobs_dir / "job-language") == before

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.append_event(
            "job-language",
            _event("event-003", "job-language", claim.run_id),
            claim,
        )
    assert exc_info.value.code == "job_shard_invalid"
    assert path.read_bytes() == complete_prefix + valid_without_newline


@pytest.mark.parametrize(
    ("payload", "expected_code", "record_number"),
    (
        (b"\xff\n", "job_shard_invalid", "#1"),
        (b'{"schema_version":1\n', "job_shard_invalid", "#1"),
        (b'{"schema_version":2}\n', "job_schema_unsupported", "#1"),
        (
            b'{"schema_version":1\n'
            b'{"schema_version":1}\n',
            "job_shard_invalid",
            "#1",
        ),
    ),
)
def test_complete_malformed_event_lines_are_fatal(
    tmp_path, payload, expected_code, record_number
):
    workspace, repository, _, _, _ = _seed(tmp_path)
    path = workspace.jobs_dir / "job-language/events/job_events.jsonl"
    path.write_bytes(payload)
    before = path.read_bytes()

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.read_events("job-language")

    assert exc_info.value.code == expected_code
    assert record_number in (exc_info.value.logical_path or "")
    assert path.read_bytes() == before


def test_event_reader_rejects_duplicate_ids_and_foreign_job_identity(tmp_path):
    workspace, repository, _, claim, _ = _seed(tmp_path)
    path = workspace.jobs_dir / "job-language/events/job_events.jsonl"
    first = _event("event-001", "job-language", claim.run_id)
    foreign = _event("event-002", "job-other", claim.run_id)
    for values in ((first, first), (first, foreign)):
        path.write_bytes(
            b"".join(
                (
                    (
                        '{"event_id":"%s","event_type":"round_completed",'
                        '"job_id":"%s","occurred_at":"2026-09-01T08:00:00.000000Z",'
                        '"payload":{"round_id":"round-001"},"run_id":"%s",'
                        '"schema_version":1}\n'
                    )
                    % (value.event_id, value.job_id, value.run_id)
                ).encode("utf-8")
                for value in values
            )
        )
        with pytest.raises(JobRepositoryError) as exc_info:
            repository.read_events("job-language")
        assert exc_info.value.code == "job_shard_invalid"
