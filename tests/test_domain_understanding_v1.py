from __future__ import annotations
import pytest
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.voice import VoiceActivityCue
from cs2pov.domain.understanding import (
    RoundUnderstandingDocument,
    UnderstandingResult,
    validate_understanding_against_transcript,
)


def _cue() -> TranscriptCue:
    return TranscriptCue(
        "cue-b-callout",
        "player-bravo",
        "round-002",
        TimeRange(20_500_000, 21_700_000),
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-bravo",
        0,
        28_800,
        "be be be",
        "en",
        0.62,
        ("anchor-bravo-001",),
        ("activity-bravo-001",),
        "asr-invoke-001",
    )


def _result() -> UnderstandingResult:
    return UnderstandingResult(
        "cue-b-callout",
        "round-002",
        "be be be",
        "B, B, B",
        "B点，B点，B点",
        0.86,
        ("same-round-context", "case-letter-b-v1"),
        (),
        "invoke-round-002",
    )


def test_transcript_jsonl_record_preserves_original_asr_and_integer_time():
    cue = _cue()
    payload = cue.to_dict()
    assert (
        payload["schema_version"] == 1
        and payload["asr_original"] == "be be be"
        and isinstance(payload["start_us"], int)
    )
    assert TranscriptCue.from_dict(payload) == cue


def test_unassigned_transcript_is_explicit_and_round_trips():
    payload = _cue().to_dict()
    payload["round_id"] = None
    assert TranscriptCue.from_dict(payload).round_id is None


def test_transcript_rejects_private_location_disguised_as_source_text():
    payload = _cue().to_dict()
    payload["asr_original"] = r"C:\Users\private\recording.wav"
    with pytest.raises(DomainSchemaError) as e:
        TranscriptCue.from_dict(payload)
    assert e.value.code == "domain_private_data_forbidden"


def test_transcript_factory_rejects_discontinuous_compact_audio_span():
    anchors = (
        TimeAnchor(
            "anchor-a",
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-bravo",
            0,
            24_000,
            TimeRange(10_000_000, 11_000_000),
            16_000,
            "voice-extractor-v1",
        ),
        TimeAnchor(
            "anchor-b",
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-bravo",
            24_000,
            48_000,
            TimeRange(20_000_000, 21_000_000),
            16_000,
            "voice-extractor-v1",
        ),
    )
    with pytest.raises(DomainSchemaError) as e:
        TranscriptCue.from_source_span(
            "cue-discontinuous",
            "player-bravo",
            None,
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-bravo",
            18_000,
            30_000,
            anchors,
            "crosses a silence gap",
            "en",
            0.5,
            ("activity-bravo-001",),
            "asr-invoke-001",
        )
    assert e.value.code == "cue_time_discontinuous"


def test_transcript_factory_uses_envelope_for_contiguous_double_anchor_span():
    anchors = (
        TimeAnchor(
            "anchor-a",
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-bravo",
            0,
            24_000,
            TimeRange(10_000_000, 11_000_000),
            16_000,
            "voice-extractor-v1",
        ),
        TimeAnchor(
            "anchor-b",
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-bravo",
            24_000,
            48_000,
            TimeRange(11_000_000, 12_000_000),
            16_000,
            "voice-extractor-v1",
        ),
    )
    cue = TranscriptCue.from_source_span(
        "cue-contiguous",
        "player-bravo",
        None,
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-bravo",
        12_000,
        36_000,
        anchors,
        "hello",
        "en",
        None,
        ("activity-bravo-001",),
        "asr-invoke-001",
    )
    assert cue.time_range == TimeRange(10_500_000, 11_500_000) and cue.anchor_ids == (
        "anchor-a",
        "anchor-b",
    )


def test_voice_activity_jsonl_record_preserves_anchor_evidence():
    a = VoiceActivityCue(
        "activity-bravo-001",
        "player-bravo",
        TimeRange(20_500_000, 21_700_000),
        12,
        ("anchor-bravo-001",),
        16_000,
    )
    assert (
        a.to_dict()["anchor_ids"] == ["anchor-bravo-001"]
        and VoiceActivityCue.from_dict(a.to_dict()) == a
    )


def test_understanding_keeps_asr_interpretation_and_translation_separate():
    r = _result()
    p = r.to_dict()
    assert (p["asr_original"], p["interpreted_source"], p["translated_zh"]) == (
        "be be be",
        "B, B, B",
        "B点，B点，B点",
    ) and UnderstandingResult.from_dict(p) == r
    validate_understanding_against_transcript(r, _cue())


def test_understanding_cannot_silently_change_source_cue():
    p = _result().to_dict()
    p["asr_original"] = "B B B"
    with pytest.raises(DomainSchemaError) as e:
        validate_understanding_against_transcript(
            UnderstandingResult.from_dict(p), _cue()
        )
    assert e.value.code == "cue_reference_invalid"


def test_understanding_content_fingerprint_changes_with_meaning():
    p = _result().to_dict()
    p["translated_zh"] = "改写后的翻译"
    assert (
        _result().content_fingerprint()
        != UnderstandingResult.from_dict(p).content_fingerprint()
    )


def test_round_document_requires_one_result_per_cue_and_matching_round():
    d = RoundUnderstandingDocument(
        "round-002", "b" * 64, "llm-config-001", "invoke-round-002", (_result(),)
    )
    assert RoundUnderstandingDocument.from_dict(d.to_dict()) == d
    with pytest.raises(DomainSchemaError) as e:
        RoundUnderstandingDocument(
            "round-001", "b" * 64, "llm-config-001", "invoke-round-002", (_result(),)
        )
    assert e.value.code == "round_reference_invalid"


def test_round_document_content_fingerprint_matches_canonical_round_trip():
    from cs2pov.domain.fingerprint import content_fingerprint

    document = RoundUnderstandingDocument(
        "round-002", "b" * 64, "llm-config-001", "invoke-round-002", (_result(),)
    )
    assert document.content_fingerprint() == content_fingerprint(document.to_dict())
    assert (
        RoundUnderstandingDocument.from_dict(document.to_dict()).content_fingerprint()
        == document.content_fingerprint()
    )


def test_round_document_rejects_duplicate_cues_and_invocation_mismatch():
    with pytest.raises(DomainSchemaError):
        RoundUnderstandingDocument(
            "round-002", "b" * 64, "cfg", "invoke-round-002", (_result(), _result())
        )
    wrong = UnderstandingResult(
        "cue-other",
        "round-002",
        "be be be",
        "B",
        "B点",
        0.5,
        ("e",),
        (),
        "other-invoke",
    )
    with pytest.raises(DomainSchemaError):
        RoundUnderstandingDocument(
            "round-002", "b" * 64, "cfg", "invoke-round-002", (wrong,)
        )


def test_speechless_round_is_successful_without_fake_model_call():
    d = RoundUnderstandingDocument("round-003", "3" * 64, "llm-config-001", None, ())
    assert RoundUnderstandingDocument.from_dict(d.to_dict()) == d


def test_empty_interpretation_translation_or_evidence_is_invalid():
    for field in ("interpreted_source", "translated_zh"):
        p = _result().to_dict()
        p[field] = ""
        with pytest.raises(DomainSchemaError) as e:
            UnderstandingResult.from_dict(p)
        assert e.value.code == "domain_field_invalid"
    p = _result().to_dict()
    p["evidence"] = []
    with pytest.raises(DomainSchemaError) as e:
        UnderstandingResult.from_dict(p)
    assert e.value.code == "domain_field_invalid"


def test_voice_and_round_direct_constructors_reject_private_data():
    with pytest.raises(DomainSchemaError) as e:
        VoiceActivityCue(r"C:\private", "player", TimeRange(1, 2), 1, ("anchor",), 0)
    assert e.value.code == "domain_private_data_forbidden"
    with pytest.raises(DomainSchemaError):
        RoundUnderstandingDocument("round", "a" * 64, r"C:\cfg", None, ())


@pytest.mark.parametrize("field", ["evidence", "warnings"])
def test_understanding_direct_constructor_rejects_private_data_in_all_durable_text_fields(
    field,
):
    kwargs = {"evidence": ("e",), "warnings": ()}
    kwargs[field] = (
        (r"C:\private\evidence.txt",)
        if field == "evidence"
        else ("https://private.example/warn",)
    )
    with pytest.raises(DomainSchemaError) as caught:
        UnderstandingResult(
            "cue-b-callout",
            "round-002",
            "be be be",
            "B, B, B",
            "B点，B点，B点",
            0.86,
            kwargs["evidence"],
            kwargs["warnings"],
            "invoke-round-002",
        )
    assert caught.value.code == "domain_private_data_forbidden"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: VoiceActivityCue("a", "p", TimeRange(1, 2), 1, (), 0),
        lambda: TranscriptCue(
            "c",
            "p",
            "r",
            TimeRange(1, 2),
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "p",
            0,
            1,
            "x",
            "en",
            None,
            ("a",),
            (),
            "i",
        ),
    ],
)
def test_empty_reference_collections_are_invalid(factory):
    with pytest.raises(DomainSchemaError):
        factory()


def test_public_bad_types_are_domain_errors():
    with pytest.raises(DomainSchemaError):
        TranscriptCue(
            "c",
            "p",
            "r",
            TimeRange(1, 2),
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "p",
            "bad",
            1,
            "x",
            "en",
            None,
            ("a",),
            ("v",),
            "i",
        )
    p = _result().to_dict()
    p["evidence"] = "bad"
    p["warnings"] = {}
    with pytest.raises(DomainSchemaError):
        UnderstandingResult.from_dict(p)
    with pytest.raises(DomainSchemaError):
        validate_understanding_against_transcript(None, _cue())
