from __future__ import annotations

import json
from pathlib import Path

import pytest

from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.review import (
    ReviewAction,
    ReviewDecision,
    ReviewRevisionManifest,
    RoundReviewDocument,
    compose_reviewed_timeline,
)
from cs2pov.domain.timebase import TimeRange
from cs2pov.domain.timeline import (
    MatchPhase,
    Round,
    RoundBoundaryConfidence,
    RoundCollection,
)
from cs2pov.domain.understanding import RoundUnderstandingDocument
from cs2pov.domain.validation import compose_draft_timeline
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage import job_repository as job_repository_module
from test_job_repository_language_shards_v1 import (
    _persist_closed_language_graph,
    _snapshot_tree,
)


def _review_values(tmp_path: Path, *, two_rounds: bool = False):
    workspace, repository, claim, language_values = _persist_closed_language_graph(
        tmp_path
    )
    timeline = language_values[0]
    if two_rounds:
        second = Round(
            "round-002",
            2,
            TimeRange(12_000_000, 13_000_000),
            None,
            None,
            MatchPhase.REGULATION_FIRST_HALF,
            "round-parser-v1",
            RoundBoundaryConfidence.EXACT,
            0,
        )
        timeline = type(timeline)(
            timeline.descriptor,
            RoundCollection((*timeline.rounds.rounds, second)),
            timeline.anchors,
        )
        repository.save_demo_timeline("job-language", timeline, claim)
        empty_request = {"round_id": "round-002", "transcript_cues": []}
        repository.save_round_understanding(
            "job-language",
            RoundUnderstandingDocument(
                "round-002",
                content_fingerprint(empty_request),
                language_values[5].snapshot_id,
                None,
                (),
            ),
            claim,
        )
    language = repository.load_language_graph("job-language")
    draft = compose_draft_timeline(
        language.timeline,
        language.transcripts,
        language.understanding_documents,
        language.configurations,
        language.invocations,
    )
    repository.save_draft_timeline("job-language", draft, claim)
    decision = ReviewDecision(
        "decision-001",
        draft.cues[0].cue_id,
        draft.cues[0].understanding_result_fingerprint,
        ReviewAction.ACCEPT,
        "2026-09-01T08:00:00.000000Z",
        "local-user",
        None,
        None,
        None,
        None,
    )
    documents = [
        RoundReviewDocument(
            "review-001",
            "round-001",
            draft.content_fingerprint(),
            (decision,),
        )
    ]
    if two_rounds:
        documents.append(
            RoundReviewDocument(
                "review-001",
                "round-002",
                draft.content_fingerprint(),
                (),
            )
        )
    revision = ReviewRevisionManifest(
        "review-001",
        draft.content_fingerprint(),
        "2026-09-01T08:00:01.000000Z",
        tuple(document.round_id for document in documents),
    )
    reviewed = compose_reviewed_timeline(draft, (decision,))
    return (
        workspace,
        repository,
        claim,
        language,
        draft,
        revision,
        tuple(documents),
        reviewed,
    )


def _register(values, *, activate: bool):
    _, repository, claim, _, _, revision, documents, _ = values
    opened = repository.load_job("job-language")
    repository.clock.advance()
    return repository.register_review_revision(
        "job-language",
        revision,
        documents,
        opened.manifest.content_fingerprint(),
        activate,
        claim,
    )


def test_active_review_and_final_timelines_reopen_as_complete_domain_graph(tmp_path):
    values = _review_values(tmp_path)
    workspace, repository, claim, language, draft, revision, documents, reviewed = values
    registered = _register(values, activate=True)
    repository.save_reviewed_timeline("job-language", reviewed, claim)
    root = workspace.jobs_dir / "job-language"
    before = _snapshot_tree(root)

    assert registered.revision == revision
    assert registered.round_documents == documents
    assert repository.load_review_revision("job-language", revision.review_id) == registered
    assert repository.load_draft_timeline("job-language") == draft
    assert repository.load_reviewed_timeline("job-language") == reviewed
    graph = repository.load_complete_domain_graph("job-language")

    assert graph.language == language
    assert graph.draft == draft
    assert graph.active_review == registered
    assert graph.reviewed == reviewed
    assert repository.load_job("job-language").manifest.active_review_id == "review-001"
    assert _snapshot_tree(root) == before


def test_complete_inactive_revision_is_healthy_history_not_an_orphan(tmp_path):
    values = _review_values(tmp_path)
    _, repository, _, _, _, revision, _, _ = values

    bundle = _register(values, activate=False)
    inspection = repository.inspect_job("job-language")

    assert repository.load_review_revision("job-language", revision.review_id) == bundle
    assert repository.load_job("job-language").manifest.active_review_id is None
    assert inspection.entry.healthy
    assert not any(
        issue.logical_path is not None and f"review_{revision.review_id}" in issue.logical_path
        for issue in inspection.entry.issues
    )


def test_review_registration_checks_manifest_cas_before_creating_staging(tmp_path):
    values = _review_values(tmp_path)
    workspace, repository, claim, _, _, revision, documents, _ = values

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.register_review_revision(
            "job-language", revision, documents, "0" * 64, True, claim
        )

    assert exc_info.value.code == "job_manifest_conflict"
    assert not any(
        (workspace.jobs_dir / "job-language/review/revisions").iterdir()
    )


def test_raced_revision_directory_is_never_replaced_or_activated(
    tmp_path, monkeypatch
):
    values = _review_values(tmp_path)
    workspace, repository, _, _, _, _, _, _ = values
    target = (
        workspace.jobs_dir / "job-language/review/revisions/review_review-001"
    )
    real_lstat_optional = job_repository_module._lstat_optional
    raced_identity: tuple[int, int] | None = None
    target_absence_checks = 0

    def create_target_after_absence_check(path, logical_path=None):
        nonlocal raced_identity, target_absence_checks
        result = real_lstat_optional(path, logical_path=logical_path)
        if Path(path) == target and result is None:
            target_absence_checks += 1
            if target_absence_checks == 2:
                target.mkdir()
                state = target.stat()
                raced_identity = (state.st_dev, state.st_ino)
        return result

    monkeypatch.setattr(
        job_repository_module,
        "_lstat_optional",
        create_target_after_absence_check,
    )

    with pytest.raises(JobRepositoryError) as exc_info:
        _register(values, activate=True)

    assert exc_info.value.code == "job_shard_invalid"
    assert raced_identity is not None
    surviving = target.stat()
    assert (surviving.st_dev, surviving.st_ino) == raced_identity
    assert not any(target.iterdir())
    assert repository.load_job("job-language").manifest.active_review_id is None


def test_review_round_ids_must_follow_authoritative_demo_order(tmp_path):
    values = _review_values(tmp_path, two_rounds=True)
    workspace, repository, claim, _, _, revision, documents, _ = values
    reversed_revision = ReviewRevisionManifest(
        revision.review_id,
        revision.source_draft_fingerprint,
        revision.created_at,
        tuple(reversed(revision.round_ids)),
    )
    opened = repository.load_job("job-language")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.register_review_revision(
            "job-language",
            reversed_revision,
            documents,
            opened.manifest.content_fingerprint(),
            False,
            claim,
        )

    assert exc_info.value.code == "job_shard_invalid"
    assert not any(
        (workspace.jobs_dir / "job-language/review/revisions").iterdir()
    )


@pytest.mark.parametrize("damage", ("missing", "extra", "identity"))
def test_review_revision_loader_rejects_incomplete_or_mismatched_closure(
    tmp_path, damage
):
    values = _review_values(tmp_path)
    workspace, repository, _, _, _, revision, _, _ = values
    _register(values, activate=False)
    directory = (
        workspace.jobs_dir / "job-language/review/revisions/review_review-001"
    )
    round_path = directory / "round_round-001.json"
    if damage == "missing":
        round_path.unlink()
    elif damage == "extra":
        payload = json.loads(round_path.read_text("utf-8"))
        payload["round_id"] = "round-002"
        (directory / "round_round-002.json").write_text(
            json.dumps(payload) + "\n", encoding="utf-8"
        )
    else:
        payload = json.loads(round_path.read_text("utf-8"))
        payload["review_id"] = "review-other"
        round_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_review_revision("job-language", revision.review_id)

    assert exc_info.value.code in {"job_shard_missing", "job_shard_invalid"}
    inspection = repository.inspect_job("job-language")
    assert any(
        issue.logical_path is not None and "review_review-001" in issue.logical_path
        for issue in inspection.entry.issues
    )


def test_review_revision_is_immutable_and_idempotent(tmp_path):
    values = _review_values(tmp_path)
    workspace, repository, claim, _, draft, revision, documents, _ = values
    first = _register(values, activate=False)
    root = workspace.jobs_dir / "job-language/review/revisions/review_review-001"
    original = _snapshot_tree(root)
    opened = repository.load_job("job-language")

    same = repository.register_review_revision(
        "job-language",
        revision,
        documents,
        opened.manifest.content_fingerprint(),
        False,
        claim,
    )
    conflicting_decision = ReviewDecision(
        "decision-001",
        draft.cues[0].cue_id,
        draft.cues[0].understanding_result_fingerprint,
        ReviewAction.ACCEPT,
        "2026-09-01T08:00:00.000000Z",
        "different-reviewer",
        None,
        None,
        None,
        None,
    )
    conflicting = RoundReviewDocument(
        revision.review_id,
        "round-001",
        revision.source_draft_fingerprint,
        (conflicting_decision,),
    )
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.register_review_revision(
            "job-language",
            revision,
            (conflicting,),
            opened.manifest.content_fingerprint(),
            False,
            claim,
        )

    assert same == first
    assert exc_info.value.code == "job_shard_invalid"
    assert _snapshot_tree(root) == original


def test_revision_parent_fsync_failure_leaves_complete_revision_inactive(
    tmp_path, monkeypatch
):
    values = _review_values(tmp_path)
    workspace, repository, _, _, _, revision, _, _ = values
    manifest_before = repository.load_job("job-language").manifest

    def fail_parent_fsync(path, logical_path, **_kwargs):
        if logical_path == "review/revisions":
            raise JobRepositoryError(
                "job_write_durability_uncertain",
                "injected parent fsync failure",
                "inspect",
                logical_path,
            )

    monkeypatch.setattr(
        "cs2pov.storage.job_repository._fsync_metadata_directory",
        fail_parent_fsync,
    )
    with pytest.raises(JobRepositoryError) as exc_info:
        _register(values, activate=True)

    assert exc_info.value.code == "job_write_durability_uncertain"
    assert repository.load_review_revision("job-language", revision.review_id).revision == revision
    manifest_after = repository.load_job("job-language").manifest
    assert manifest_after == manifest_before
    assert manifest_after.active_review_id is None
    assert (
        workspace.jobs_dir / "job-language/review/revisions/review_review-001"
    ).is_dir()


def test_active_review_missing_declared_file_makes_job_damaged(tmp_path):
    values = _review_values(tmp_path)
    workspace, repository, _, _, _, _, _, _ = values
    _register(values, activate=True)
    (
        workspace.jobs_dir
        / "job-language/review/revisions/review_review-001/round_round-001.json"
    ).unlink()

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_job("job-language")

    assert exc_info.value.code == "job_shard_missing"


def test_reviewed_timeline_rejects_tampering_through_production_graph(tmp_path):
    values = _review_values(tmp_path)
    workspace, repository, claim, _, _, _, _, reviewed = values
    _register(values, activate=True)
    repository.save_reviewed_timeline("job-language", reviewed, claim)
    path = workspace.jobs_dir / "job-language/final/timelines/reviewed.json"
    payload = reviewed.to_dict()
    payload["cues"][0]["final_translated_zh"] = "被篡改"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_reviewed_timeline("job-language")

    assert exc_info.value.code == "job_shard_invalid"


def test_inspection_reports_hidden_review_staging_but_not_complete_inactive_history(
    tmp_path,
):
    values = _review_values(tmp_path)
    workspace, repository, _, _, _, _, _, _ = values
    _register(values, activate=False)
    assert repository.inspect_job("job-language").entry.healthy
    staging = (
        workspace.jobs_dir
        / "job-language/review/revisions/.review_review-broken.deadbeef.staging"
    )
    staging.mkdir()

    inspection = repository.inspect_job("job-language")

    assert any(
        issue.logical_path is not None and ".staging" in issue.logical_path
        for issue in inspection.entry.issues
    )


def test_unexpected_draft_validator_exception_propagates(tmp_path, monkeypatch):
    values = _review_values(tmp_path)
    _, repository, _, _, _, _, _, _ = values

    def explode(*_args, **_kwargs):
        raise RuntimeError("draft validator bug")

    monkeypatch.setattr(
        "cs2pov.storage.job_repository.validate_draft_timeline_graph",
        explode,
    )
    with pytest.raises(RuntimeError, match="draft validator bug"):
        repository.load_draft_timeline("job-language")
