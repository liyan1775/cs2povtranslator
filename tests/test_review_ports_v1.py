from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from cs2pov.application.review_ports import CurrentJobReviewApplicationService
from cs2pov.domain.job import (
    JobManifest,
    JobPhase,
    JobRunStatus,
    RoundProgressSummary,
)
from cs2pov.domain.review import DraftCommsCue, DraftCommsTimeline


class _FakeRepository:
    def __init__(self) -> None:
        timestamp = "2026-09-01T08:00:00.000000Z"
        self.clock = lambda: datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
        manifest = JobManifest(
            "job-review",
            "Review Job",
            timestamp,
            timestamp,
            "a" * 64,
            "match.dem",
            None,
            None,
            JobPhase.DRAFT_TIMELINE_READY,
            JobRunStatus.SUCCEEDED,
            RoundProgressSummary(1, 1, 0, 0),
            (),
            None,
            (),
        )
        cue_one = DraftCommsCue(
            "cue-one",
            "round-001",
            "player-one",
            0,
            500_000,
            "one",
            "one",
            "一",
            0.9,
            ("fixture",),
            "b" * 64,
        )
        cue_two = DraftCommsCue(
            "cue-two",
            "round-001",
            "player-one",
            600_000,
            1_000_000,
            "two",
            "two",
            "二",
            0.9,
            ("fixture",),
            "c" * 64,
        )
        self.current = SimpleNamespace(
            manifest=manifest,
            source=None,
            paths=None,
            run_status=manifest.run_status,
        )
        self.draft = DraftCommsTimeline(
            "a" * 64,
            "demo-microseconds",
            "d" * 64,
            (cue_one, cue_two),
        )
        self.revisions = {}
        self.reviewed = None
        self._claim = object()

    def load_job(self, _job_id):
        return self.current

    def load_draft_timeline(self, _job_id):
        return self.draft

    def load_review_revision(self, _job_id, review_id):
        return self.revisions[review_id]

    def register_review_revision(
        self, _job_id, revision, documents, _expected, _activate, _claim
    ):
        bundle = SimpleNamespace(revision=revision, round_documents=documents)
        self.revisions[revision.review_id] = bundle
        return bundle

    def save_reviewed_timeline(self, _job_id, timeline, _claim):
        self.reviewed = timeline

    @contextmanager
    def acquire_write(self, _job_id, *, lease_us):
        assert lease_us > 0
        yield SimpleNamespace(claim=self._claim)

    def replace_manifest(self, _job_id, _expected, manifest, _claim):
        self.current = SimpleNamespace(
            manifest=manifest,
            source=None,
            paths=None,
            run_status=manifest.run_status,
        )
        return self.current


def test_review_service_supports_single_decision_then_full_confirmation():
    repository = _FakeRepository()
    review_ids = iter(("review-partial", "review-complete"))
    decision_ids = iter(("decision-one", "decision-two"))
    service = CurrentJobReviewApplicationService(
        repository,
        review_id_factory=lambda: next(review_ids),
        decision_id_factory=lambda _cue_id: next(decision_ids),
    )

    partial = service.submit_decision_values(
        "job-review", cue_id="cue-one", action="accept"
    )

    assert partial.complete is False
    assert partial.decision_count == 1
    assert partial.pending_count == 1
    assert partial.phase is JobPhase.REVIEW_PENDING
    assert repository.reviewed is None

    complete = service.confirm_round("job-review", "round-001")

    assert complete.complete is True
    assert complete.decision_count == 2
    assert complete.pending_count == 0
    assert complete.phase is JobPhase.FINAL_TIMELINE_READY
    assert repository.reviewed is not None
