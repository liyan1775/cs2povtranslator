from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import (
    ModelCapability,
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.review import (
    DraftCommsCue,
    DraftCommsTimeline,
    ReviewAction,
    ReviewDecision,
    compose_reviewed_timeline,
)
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.timeline import (
    DemoDescriptor,
    DemoTimeline,
    MatchPhase,
    PlayerSnapshot,
    Round,
    RoundBoundaryConfidence,
    RoundCollection,
)
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import RoundUnderstandingDocument, UnderstandingResult
from cs2pov.domain.validation import (
    compose_draft_timeline,
    validate_draft_timeline_graph,
    validate_reviewed_timeline_graph,
    validate_transcript_against_timeline,
    validate_understanding_document_graph,
    validate_voice_activity_against_timeline,
)
from cs2pov.domain.voice import VoiceActivityCue


def _closed_graph():
    descriptor = DemoDescriptor(
        "a" * 64,
        "de_mirage",
        None,
        64,
        1,
        (PlayerSnapshot("player-alpha", "Alpha", 2),),
    )
    rounds = RoundCollection(
        (
            Round(
                "round-001",
                1,
                TimeRange(10_000_000, 11_000_000),
                None,
                None,
                MatchPhase.REGULATION_FIRST_HALF,
                "round-parser-v1",
                RoundBoundaryConfidence.EXACT,
                0,
            ),
        )
    )
    anchor = TimeAnchor(
        "anchor-alpha-001",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        0,
        24_000,
        TimeRange(10_000_000, 11_000_000),
        16_000,
        "voice-extractor-v1",
    )
    timeline = DemoTimeline(descriptor, rounds, (anchor,))
    activity = VoiceActivityCue(
        "activity-alpha-001",
        "player-alpha",
        TimeRange(10_000_000, 10_500_000),
        8,
        ("anchor-alpha-001",),
        16_000,
    )
    configuration = ModelConfigurationSnapshot(
        "asr-config-001",
        ModelCapability.ASR,
        "faster-whisper-local",
        None,
        "fixture-asr-model",
        None,
        {"language": "en"},
        (),
        "asr-adapter-v1",
    )
    invocation = ModelInvocationRecord.from_payloads(
        "asr-invoke-001",
        configuration.snapshot_id,
        "asr-batch-001",
        {"audio_content_fingerprint": "9" * 64},
        {"cue_ids": ["cue-alpha-001"]},
    )
    transcript = TranscriptCue.from_source_span(
        "cue-alpha-001",
        "player-alpha",
        "round-001",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        0,
        12_000,
        (anchor,),
        "one jungle",
        "en",
        0.9,
        (activity.activity_id,),
        invocation.invocation_id,
    )
    return timeline, activity, transcript, configuration, invocation


def _understanding_graph():
    timeline, activity, transcript, asr_configuration, asr_invocation = _closed_graph()
    configuration = ModelConfigurationSnapshot(
        "llm-config-001",
        ModelCapability.UNDERSTANDING_TRANSLATION,
        "openai-compatible",
        "provider-local-profile",
        "fixture-model",
        "understanding-v1",
        {"temperature": 0.2},
        (),
        "adapter-v1",
    )
    result = UnderstandingResult(
        transcript.cue_id,
        "round-001",
        transcript.asr_original,
        "one jungle",
        "警家一个",
        0.93,
        ("same-round-context",),
        (),
        "invoke-round-001",
    )
    request = {"round_id": "round-001", "transcript_cues": [transcript.to_dict()]}
    response = {"round_id": "round-001", "results": [result.to_dict()]}
    invocation = ModelInvocationRecord.from_payloads(
        "invoke-round-001", configuration.snapshot_id, "round-001", request, response
    )
    document = RoundUnderstandingDocument(
        "round-001",
        content_fingerprint(request),
        configuration.snapshot_id,
        invocation.invocation_id,
        (result,),
    )
    return (
        timeline,
        activity,
        transcript,
        asr_configuration,
        asr_invocation,
        configuration,
        invocation,
        document,
    )


def test_transcript_graph_validates_player_round_activity_anchor_and_asr_call() -> None:
    timeline, activity, transcript, configuration, invocation = _closed_graph()
    validate_transcript_against_timeline(
        transcript, timeline, (activity,), (configuration,), (invocation,)
    )


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    (
        ("player_id", "player-missing", "player_reference_invalid"),
        ("anchor_ids", ["anchor-missing"], "time_anchor_invalid"),
        ("start_us", 9_000_000, "cue_reference_invalid"),
    ),
)
def test_voice_activity_graph_rejects_unknown_or_unmapped_evidence(
    field: str, value: object, error_code: str
) -> None:
    timeline, activity, _, _, _ = _closed_graph()
    payload = activity.to_dict()
    payload[field] = value
    if field == "start_us":
        payload["end_us"] = 9_500_000
    with pytest.raises(DomainSchemaError) as caught:
        validate_voice_activity_against_timeline(
            VoiceActivityCue.from_dict(payload), timeline
        )
    assert caught.value.code == error_code


def test_transcript_graph_rejects_unknown_player_dangling_call_and_round_crossing() -> (
    None
):
    timeline, activity, transcript, configuration, invocation = _closed_graph()
    payload = transcript.to_dict()
    payload["player_id"] = "player-missing"
    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(
            TranscriptCue.from_dict(payload),
            timeline,
            (activity,),
            (configuration,),
            (invocation,),
        )
    assert caught.value.code == "player_reference_invalid"
    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(
            transcript, timeline, (activity,), (configuration,), ()
        )
    assert caught.value.code == "invocation_reference_invalid"
    payload = transcript.to_dict()
    payload["end_us"] = 11_000_001
    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(
            TranscriptCue.from_dict(payload),
            timeline,
            (activity,),
            (configuration,),
            (invocation,),
        )
    assert caught.value.code == "cue_reference_invalid"


def test_understanding_and_draft_graph_derive_all_source_fingerprints() -> None:
    (
        timeline,
        _,
        transcript,
        asr_configuration,
        _,
        configuration,
        invocation,
        document,
    ) = _understanding_graph()
    validate_understanding_document_graph(
        document, (transcript,), (configuration,), (invocation,)
    )
    draft = compose_draft_timeline(
        timeline, (transcript,), (document,), (configuration,), (invocation,)
    )
    validate_draft_timeline_graph(
        draft, timeline, (transcript,), (document,), (configuration,), (invocation,)
    )
    tampered_payload = draft.to_dict()
    tampered_payload["input_fingerprint"] = "0" * 64
    with pytest.raises(DomainSchemaError) as caught:
        validate_draft_timeline_graph(
            DraftCommsTimeline.from_dict(tampered_payload),
            timeline,
            (transcript,),
            (document,),
            (configuration,),
            (invocation,),
        )
    assert caught.value.code == "domain_fingerprint_mismatch"
    changed_payload = document.results[0].to_dict()
    changed_payload["asr_original"] = "B B B"
    changed_document = RoundUnderstandingDocument(
        "round-001",
        document.input_fingerprint,
        configuration.snapshot_id,
        invocation.invocation_id,
        (UnderstandingResult.from_dict(changed_payload),),
    )
    with pytest.raises(DomainSchemaError) as caught:
        validate_understanding_document_graph(
            changed_document, (transcript,), (configuration,), (invocation,)
        )
    assert caught.value.code == "cue_reference_invalid"
    with pytest.raises(DomainSchemaError) as caught:
        validate_understanding_document_graph(
            document, (transcript,), (asr_configuration,), (invocation,)
        )
    assert caught.value.code == "invocation_reference_invalid"


def test_understanding_graph_rejects_duplicate_results_and_speechless_fake_call() -> (
    None
):
    _, _, transcript, _, _, configuration, invocation, document = _understanding_graph()
    duplicate = object.__new__(RoundUnderstandingDocument)
    object.__setattr__(duplicate, "round_id", document.round_id)
    object.__setattr__(duplicate, "input_fingerprint", document.input_fingerprint)
    object.__setattr__(
        duplicate,
        "model_configuration_snapshot_id",
        document.model_configuration_snapshot_id,
    )
    object.__setattr__(duplicate, "invocation_record_id", document.invocation_record_id)
    object.__setattr__(duplicate, "results", (document.results[0], document.results[0]))
    with pytest.raises(DomainSchemaError):
        validate_understanding_document_graph(
            duplicate, (transcript,), (configuration,), (invocation,)
        )
    empty_request = {"round_id": "round-001", "transcript_cues": []}
    speechless = RoundUnderstandingDocument(
        "round-001",
        content_fingerprint(empty_request),
        configuration.snapshot_id,
        None,
        (),
    )
    with pytest.raises(DomainSchemaError):
        validate_understanding_document_graph(
            speechless, (transcript,), (configuration,), ()
        )


def test_reviewed_time_edit_must_remain_inside_declared_round() -> None:
    timeline, _, transcript, _, _, configuration, invocation, document = (
        _understanding_graph()
    )
    result = document.results[0]
    draft_cue = DraftCommsCue.from_transcript_and_understanding(transcript, result)
    draft = DraftCommsTimeline(
        "a" * 64,
        "demo-microseconds",
        content_fingerprint({"round_understanding": []}),
        (draft_cue,),
    )
    decision = ReviewDecision(
        "decision-001",
        draft_cue.cue_id,
        draft_cue.understanding_result_fingerprint,
        ReviewAction.EDIT,
        "2026-08-31T12:00:00.000000Z",
        "local-user",
        "调整显示时间",
        TimeRange(9_000_000, 9_500_000),
        None,
        None,
    )
    reviewed = compose_reviewed_timeline(draft, (decision,))
    with pytest.raises(DomainSchemaError) as caught:
        validate_reviewed_timeline_graph(reviewed, draft, timeline, (decision,))
    assert caught.value.code == "cue_reference_invalid"


def test_activity_and_validation_collections_bad_types_return_domain_error() -> None:
    timeline, activity, transcript, configuration, invocation = _closed_graph()
    with pytest.raises(DomainSchemaError):
        validate_voice_activity_against_timeline("bad", timeline)
    with pytest.raises(DomainSchemaError):
        validate_transcript_against_timeline(
            transcript, timeline, "bad", (configuration,), (invocation,)
        )


def test_draft_composition_rejects_missing_extra_round_documents_and_unassigned_transcript() -> (
    None
):
    timeline, _, transcript, _, _, configuration, invocation, document = (
        _understanding_graph()
    )
    with pytest.raises(DomainSchemaError):
        compose_draft_timeline(
            timeline, (transcript,), (), (configuration,), (invocation,)
        )
    extra = RoundUnderstandingDocument(
        "round-extra",
        document.input_fingerprint,
        document.model_configuration_snapshot_id,
        None,
        (),
    )
    with pytest.raises(DomainSchemaError):
        compose_draft_timeline(
            timeline, (transcript,), (document, extra), (configuration,), (invocation,)
        )
    unassigned = TranscriptCue.from_dict(
        {**transcript.to_dict(), "cue_id": "cue-unassigned", "round_id": None}
    )
    compose_draft_timeline(
        timeline, (transcript, unassigned), (document,), (configuration,), (invocation,)
    )


def test_reviewed_graph_rejects_stale_source_hash_and_preserves_round_order() -> None:
    timeline, _, transcript, _, _, configuration, invocation, document = (
        _understanding_graph()
    )
    draft = compose_draft_timeline(
        timeline, (transcript,), (document,), (configuration,), (invocation,)
    )
    decision = ReviewDecision(
        "decision-001",
        transcript.cue_id,
        draft.cues[0].understanding_result_fingerprint,
        ReviewAction.ACCEPT,
        "2026-08-31T12:00:00Z",
        "local-user",
        None,
        None,
        None,
        None,
    )
    reviewed = compose_reviewed_timeline(draft, (decision,))
    validate_reviewed_timeline_graph(reviewed, draft, timeline, (decision,))
    payload = reviewed.to_dict()
    payload["source_draft_fingerprint"] = "0" * 64
    with pytest.raises(DomainSchemaError) as caught:
        validate_reviewed_timeline_graph(
            type(reviewed).from_dict(payload), draft, timeline, (decision,)
        )
    assert caught.value.code == "domain_fingerprint_mismatch"


def test_unassigned_activity_and_transcript_validate_without_round_membership() -> None:
    timeline, activity, transcript, configuration, invocation = _closed_graph()
    extra_anchor = TimeAnchor(
        "anchor-alpha-002",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        24_000,
        48_000,
        TimeRange(12_000_000, 13_000_000),
        16_000,
        "voice-extractor-v1",
    )
    timeline = DemoTimeline(
        timeline.descriptor, timeline.rounds, (timeline.anchors[0], extra_anchor)
    )
    activity = VoiceActivityCue(
        "activity-unassigned",
        "player-alpha",
        TimeRange(12_000_000, 12_500_000),
        8,
        (extra_anchor.anchor_id,),
        16_000,
    )
    transcript = TranscriptCue.from_source_span(
        "cue-unassigned",
        "player-alpha",
        None,
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        24_000,
        36_000,
        (extra_anchor,),
        "unassigned",
        "en",
        0.9,
        (activity.activity_id,),
        invocation.invocation_id,
    )
    validate_voice_activity_against_timeline(activity, timeline)
    validate_transcript_against_timeline(
        transcript, timeline, (activity,), (configuration,), (invocation,)
    )


def test_multi_anchor_and_multi_activity_references_use_union_coverage() -> None:
    timeline, _, _, configuration, invocation = _closed_graph()
    first = TimeAnchor(
        "anchor-alpha-001",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        0,
        12_000,
        TimeRange(10_000_000, 10_500_000),
        16_000,
        "voice-extractor-v1",
    )
    second = TimeAnchor(
        "anchor-alpha-002",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        12_000,
        24_000,
        TimeRange(10_500_000, 11_000_000),
        16_000,
        "voice-extractor-v1",
    )
    timeline = DemoTimeline(timeline.descriptor, timeline.rounds, (first, second))
    first_activity = VoiceActivityCue(
        "activity-alpha-001",
        "player-alpha",
        TimeRange(10_000_000, 10_500_000),
        8,
        (first.anchor_id,),
        16_000,
    )
    second_activity = VoiceActivityCue(
        "activity-alpha-002",
        "player-alpha",
        TimeRange(10_500_000, 11_000_000),
        8,
        (second.anchor_id,),
        16_000,
    )
    transcript = TranscriptCue.from_source_span(
        "cue-multi",
        "player-alpha",
        "round-001",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        0,
        24_000,
        (first, second),
        "two spans",
        "en",
        0.9,
        (first_activity.activity_id, second_activity.activity_id),
        invocation.invocation_id,
    )
    validate_voice_activity_against_timeline(first_activity, timeline)
    validate_voice_activity_against_timeline(second_activity, timeline)
    validate_transcript_against_timeline(
        transcript,
        timeline,
        (first_activity, second_activity),
        (configuration,),
        (invocation,),
    )


def test_reviewed_graph_rejects_missing_cue_without_exclusion() -> None:
    from cs2pov.domain.review import ReviewedCommsTimeline

    timeline, _, transcript, _, _, configuration, invocation, document = (
        _understanding_graph()
    )
    draft = compose_draft_timeline(
        timeline, (transcript,), (document,), (configuration,), (invocation,)
    )
    reviewed = ReviewedCommsTimeline(
        draft.demo_asset_id, draft.timebase, draft.content_fingerprint(), (), ()
    )
    decision = ReviewDecision(
        "decision-001", draft.cues[0].cue_id,
        draft.cues[0].understanding_result_fingerprint,
        ReviewAction.ACCEPT, "2026-08-31T12:00:00Z", "local-user", None,
        None, None, None,
    )
    with pytest.raises(DomainSchemaError) as caught:
        validate_reviewed_timeline_graph(reviewed, draft, timeline, (decision,))
    assert caught.value.code == "domain_fingerprint_mismatch"
    assert caught.value.path == "reviewed_timeline"


def test_reviewed_graph_rejects_duplicate_review_decision_ids() -> None:
    from cs2pov.domain.review import ReviewedCommsCue, ReviewedCommsTimeline

    first = ReviewedCommsCue(
        "cue-a",
        "round-001",
        "player-alpha",
        10_000_000,
        10_100_000,
        "a",
        "a",
        "A",
        0.9,
        ("e",),
        "a",
        "A",
        "same-decision",
    )
    second = ReviewedCommsCue(
        "cue-b",
        "round-001",
        "player-alpha",
        10_200_000,
        10_300_000,
        "b",
        "b",
        "B",
        0.9,
        ("e",),
        "b",
        "B",
        "same-decision",
    )
    dummy = _dummy_draft_for_review_graph()
    with pytest.raises(DomainSchemaError):
        ReviewedCommsTimeline(
            "a" * 64,
            "demo-microseconds",
            dummy.content_fingerprint(),
            (first, second),
            (),
        )


def test_transcript_validation_rejects_fake_invocation_with_domain_error() -> None:
    timeline, activity, transcript, configuration, invocation = _closed_graph()

    class FakeInvocation:
        invocation_id = invocation.invocation_id

    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(
            transcript,
            timeline,
            (activity,),
            (configuration,),
            (FakeInvocation(),),
        )
    assert caught.value.code == "domain_field_invalid"


def test_understanding_validation_rejects_fake_configuration_with_domain_error() -> (
    None
):
    _, _, transcript, _, _, configuration, invocation, document = _understanding_graph()

    class FakeConfiguration:
        snapshot_id = configuration.snapshot_id

    with pytest.raises(DomainSchemaError) as caught:
        validate_understanding_document_graph(
            document,
            (transcript,),
            (FakeConfiguration(),),
            (invocation,),
        )
    assert caught.value.code == "domain_field_invalid"


def test_voice_activity_validation_rejects_uncertainty_below_anchor() -> None:
    timeline, activity, _, _, _ = _closed_graph()
    payload = activity.to_dict()
    payload["uncertainty_us"] = 0
    with pytest.raises(DomainSchemaError) as caught:
        validate_voice_activity_against_timeline(
            VoiceActivityCue.from_dict(payload), timeline
        )
    assert caught.value.code == "cue_reference_invalid"


def _reviewed_graph_fixture():
    timeline, _, transcript, _, _, configuration, invocation, document = _understanding_graph()
    draft = compose_draft_timeline(
        timeline, (transcript,), (document,), (configuration,), (invocation,)
    )
    decision = ReviewDecision(
        "decision-001", transcript.cue_id, draft.cues[0].understanding_result_fingerprint,
        ReviewAction.ACCEPT, "2026-08-31T12:00:00Z", "local-user", None, None, None, None,
    )
    return timeline, draft, decision, compose_reviewed_timeline(draft, (decision,))


def test_reopened_reviewed_graph_rejects_accept_final_translation_tampering() -> None:
    timeline, draft, decision, reviewed = _reviewed_graph_fixture()
    payload = reviewed.to_dict()
    payload["cues"][0]["final_translated_zh"] = "被篡改的翻译"
    tampered = type(reviewed).from_dict(payload)
    with pytest.raises(DomainSchemaError) as caught:
        validate_reviewed_timeline_graph(tampered, draft, timeline, (decision,))
    assert caught.value.code == "domain_fingerprint_mismatch"
    assert caught.value.path == "reviewed_timeline"


def test_reopened_reviewed_graph_rejects_forged_excluded_decision_id() -> None:
    timeline, draft, decision, reviewed = _reviewed_graph_fixture()
    payload = reviewed.to_dict()
    payload["excluded_decision_ids"] = ["forged-exclusion"]
    tampered = type(reviewed).from_dict(payload)
    with pytest.raises(DomainSchemaError) as caught:
        validate_reviewed_timeline_graph(tampered, draft, timeline, (decision,))
    assert caught.value.code == "domain_fingerprint_mismatch"
    assert caught.value.path == "reviewed_timeline"


def test_reopened_reviewed_graph_rejects_omitted_cue() -> None:
    timeline, draft, decision, reviewed = _reviewed_graph_fixture()
    payload = reviewed.to_dict()
    payload["cues"] = []
    tampered = type(reviewed).from_dict(payload)
    with pytest.raises(DomainSchemaError) as caught:
        validate_reviewed_timeline_graph(tampered, draft, timeline, (decision,))
    assert caught.value.code == "domain_fingerprint_mismatch"
    assert caught.value.path == "reviewed_timeline"


def test_transcript_and_draft_composition_reject_demo_discontinuous_source_mapping() -> None:
    timeline, _, transcript, asr_configuration, asr_invocation, configuration, invocation, document = _understanding_graph()
    first = TimeAnchor(
        "anchor-gap-a", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 0, 12_000,
        TimeRange(10_000_000, 10_500_000), 16_000, "voice-extractor-v1",
    )
    second = TimeAnchor(
        "anchor-gap-b", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 12_000, 24_000,
        TimeRange(10_700_000, 11_200_000), 16_000, "voice-extractor-v1",
    )
    gap_timeline = DemoTimeline(
        timeline.descriptor,
        RoundCollection((Round("round-001", 1, TimeRange(10_000_000, 11_200_000), None, None,
                               MatchPhase.REGULATION_FIRST_HALF, "round-parser-v1", RoundBoundaryConfidence.EXACT, 0),)),
        (first, second),
    )
    payload = transcript.to_dict()
    payload.update({
        "start_us": 10_000_000, "end_us": 11_200_000,
        "source_start": 0, "source_end": 24_000,
        "anchor_ids": ["anchor-gap-a", "anchor-gap-b"],
    })
    discontinuous = TranscriptCue.from_dict(payload)
    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(
            discontinuous, gap_timeline, (), (asr_configuration,), (asr_invocation,)
        )
    assert caught.value.code == "cue_time_discontinuous"
    with pytest.raises(DomainSchemaError) as caught:
        compose_draft_timeline(
            gap_timeline, (discontinuous,), (document,), (configuration,), (invocation,)
        )
    assert caught.value.code == "cue_time_discontinuous"


def _dummy_draft_for_review_graph() -> DraftCommsTimeline:
    from cs2pov.domain.review import DraftCommsCue

    first = DraftCommsCue(
        "cue-a",
        "round-001",
        "player-alpha",
        10_000_000,
        10_100_000,
        "a",
        "a",
        "A",
        0.9,
        ("e",),
        "b" * 64,
    )
    second = DraftCommsCue(
        "cue-b",
        "round-001",
        "player-alpha",
        10_200_000,
        10_300_000,
        "b",
        "b",
        "B",
        0.9,
        ("e",),
        "c" * 64,
    )
    return DraftCommsTimeline("a" * 64, "demo-microseconds", "d" * 64, (first, second))
