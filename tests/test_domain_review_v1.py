from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.review import DraftCommsCue, DraftCommsTimeline, ReviewAction, ReviewDecision, ReviewedCommsTimeline, compose_reviewed_timeline
from cs2pov.domain.timebase import SourceClock, TimeRange
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import UnderstandingResult

PERSISTENCE_TEST_INPUT_FINGERPRINT = content_fingerprint({"round_understanding": []})

def _draft(cue_id: str = "cue-b-callout", start_us: int = 20_500_000) -> DraftCommsCue:
    transcript = TranscriptCue(cue_id, "player-bravo", "round-002", TimeRange(start_us, start_us + 1_200_000), SourceClock.COMPACT_AUDIO_SAMPLE, "player-bravo", 0, 28_800, "be be be", "en", 0.62, ("anchor-bravo-001",), ("activity-bravo-001",), "asr-invoke-001")
    result = UnderstandingResult(cue_id, "round-002", "be be be", "B, B, B", "B点，B点，B点", 0.86, ("same-round-context",), (), "invoke-round-002")
    return DraftCommsCue.from_transcript_and_understanding(transcript, result)

def _source(cues: tuple[DraftCommsCue, ...]) -> DraftCommsTimeline:
    return DraftCommsTimeline("a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, cues)

def _decision(draft: DraftCommsCue, action: ReviewAction = ReviewAction.ACCEPT, **kwargs: object) -> ReviewDecision:
    return ReviewDecision(kwargs.pop("decision_id", "decision-001"), draft.cue_id, draft.understanding_result_fingerprint, action, kwargs.pop("reviewed_at", "2026-08-31T12:00:00+00:00"), kwargs.pop("reviewer_label", "local-user"), kwargs.pop("reason", None), kwargs.pop("revised_time_range", None), kwargs.pop("revised_interpreted_source", None), kwargs.pop("revised_translated_zh", None))

def test_review_action_values_exist() -> None:
    assert tuple(x.value for x in ReviewAction) == ("accept", "edit", "exclude")

def test_accept_decision_cannot_smuggle_revised_content() -> None:
    draft = _draft()
    with pytest.raises(DomainSchemaError) as caught:
        ReviewDecision("decision-001", draft.cue_id, draft.understanding_result_fingerprint, ReviewAction.ACCEPT, "2026-08-31T12:00:00+00:00", "local-user", None, None, None, "被偷偷替换")
    assert caught.value.code == "review_decision_invalid"

def test_edit_requires_a_change_and_exclude_requires_reason() -> None:
    draft = _draft()
    with pytest.raises(DomainSchemaError) as caught: _decision(draft, ReviewAction.EDIT, reason="修正点位呼叫")
    assert caught.value.code == "review_decision_invalid"
    with pytest.raises(DomainSchemaError) as caught: _decision(draft, ReviewAction.EXCLUDE)
    assert caught.value.code == "review_decision_invalid"

def test_review_reason_rejects_private_location() -> None:
    draft = _draft()
    with pytest.raises(DomainSchemaError) as caught: _decision(draft, ReviewAction.EXCLUDE, reason="/home/private/evidence.txt", decision_id="decision-private")
    assert caught.value.code == "domain_private_data_forbidden"

def test_review_timestamp_is_aware_utc_and_fixed_precision() -> None:
    draft = _draft(); decision = _decision(draft, reviewed_at="2026-08-31T20:00:00.123456+08:00")
    assert decision.reviewed_at == "2026-08-31T12:00:00.123456Z"
    assert ReviewDecision.from_dict(decision.to_dict()) == decision
    with pytest.raises(DomainSchemaError): _decision(draft, reviewed_at="2026-08-31T12:00:00")

def test_review_decision_persists_revised_time_as_flat_microsecond_keys() -> None:
    draft = _draft(); decision = _decision(draft, ReviewAction.EDIT, revised_time_range=TimeRange(21_000_000, 22_000_000), revised_translated_zh="B点！")
    payload = decision.to_dict()
    assert "revised_time_range" not in payload and payload["revised_start_us"] == 21_000_000 and payload["revised_end_us"] == 22_000_000
    assert ReviewDecision.from_dict(payload) == decision

def test_composition_preserves_original_and_records_final_values() -> None:
    draft = _draft(); decision = _decision(draft, ReviewAction.EDIT, reason="将呼叫翻译调整为更自然的中文", revised_translated_zh="B点！B点！B点！")
    timeline = compose_reviewed_timeline(_source((draft,)), (decision,)); cue = timeline.cues[0]
    assert cue.asr_original == "be be be" and cue.interpreted_source == "B, B, B" and cue.model_translated_zh == "B点，B点，B点"
    assert cue.model_confidence == 0.86 and cue.evidence == ("same-round-context",) and cue.final_translated_zh == "B点！B点！B点！"
    assert cue.review_decision_id == "decision-001" and timeline.source_draft_fingerprint == _source((draft,)).content_fingerprint()

def test_valid_exclude_removes_cue_and_preserves_decision_id() -> None:
    draft = _draft(); reviewed = compose_reviewed_timeline(_source((draft,)), (_decision(draft, ReviewAction.EXCLUDE, reason="与目标队伍交流无关", decision_id="decision-exclude"),))
    assert reviewed.cues == () and reviewed.excluded_decision_ids == ("decision-exclude",)

def test_timeline_requires_explicit_demo_timebase_and_sorted_cues() -> None:
    first, second = _draft("cue-first", 20_500_000), _draft("cue-second", 22_000_000); timeline = _source((first, second))
    assert DraftCommsTimeline.from_dict(timeline.to_dict()) == timeline
    with pytest.raises(DomainSchemaError) as caught: DraftCommsTimeline("a" * 64, "round-local-milliseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (first, second))
    assert caught.value.code == "timeline_invalid"
    with pytest.raises(DomainSchemaError) as caught: DraftCommsTimeline("a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (second, first))
    assert caught.value.code == "timeline_invalid"

def test_reviewed_timeline_round_trips_from_verified_composition() -> None:
    draft = _draft(); timeline = compose_reviewed_timeline(_source((draft,)), (_decision(draft),))
    assert ReviewedCommsTimeline.from_dict(timeline.to_dict()) == timeline

def test_composition_rejects_missing_extra_stale_and_noop_decisions() -> None:
    draft = _draft(); source = _source((draft,))
    with pytest.raises(DomainSchemaError) as caught: compose_reviewed_timeline(source, ())
    assert caught.value.code == "review_decision_invalid"
    extra = ReviewDecision("decision-extra", "cue-extra", "0" * 64, ReviewAction.ACCEPT, "2026-08-31T12:00:00Z", "local-user", None, None, None, None)
    with pytest.raises(DomainSchemaError) as caught: compose_reviewed_timeline(source, (extra,))
    assert caught.value.code == "review_decision_invalid"
    stale = ReviewDecision("decision-stale", draft.cue_id, "0" * 64, ReviewAction.ACCEPT, "2026-08-31T12:00:00Z", "local-user", None, None, None, None)
    with pytest.raises(DomainSchemaError) as caught: compose_reviewed_timeline(source, (stale,))
    assert caught.value.code == "domain_fingerprint_mismatch"
    noop = _decision(draft, ReviewAction.EDIT, reason="重复原译文", revised_translated_zh=draft.translated_zh, decision_id="decision-noop")
    with pytest.raises(DomainSchemaError) as caught: compose_reviewed_timeline(source, (noop,))
    assert caught.value.code == "review_decision_invalid"

def test_tampered_draft_payload_cannot_keep_old_content_fingerprint() -> None:
    source = _source((_draft(),)); original = source.content_fingerprint(); payload = source.to_dict(); payload["cues"][0]["translated_zh"] = "被篡改"
    assert DraftCommsTimeline.from_dict(payload).content_fingerprint() != original

def test_direct_reviewed_document_rejects_duplicate_cues() -> None:
    draft = _draft(); composed = compose_reviewed_timeline(_source((draft,)), (_decision(draft),))
    with pytest.raises(DomainSchemaError) as caught: ReviewedCommsTimeline("a" * 64, "demo-microseconds", composed.source_draft_fingerprint, (composed.cues[0], composed.cues[0]), ())
    assert caught.value.code == "timeline_invalid"

def test_direct_and_factory_collections_reject_bad_sequence_types() -> None:
    draft = _draft()
    with pytest.raises(DomainSchemaError): DraftCommsTimeline("a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, "bad")
    payload = _source((draft,)).to_dict(); payload["cues"] = "bad"
    with pytest.raises(DomainSchemaError): DraftCommsTimeline.from_dict(payload)
