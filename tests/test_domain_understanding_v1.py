from cs2pov.domain.timebase import TimeRange
from cs2pov.domain.voice import VoiceActivityCue
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import UnderstandingResult, RoundUnderstandingDocument


def test_voice_and_understanding_round_trip():
    a = VoiceActivityCue("activity-1", "player-1", TimeRange(1, 2), 1, ("anchor-1",), 0)
    assert VoiceActivityCue.from_dict(a.to_dict()) == a
    c = TranscriptCue(
        "cue-1",
        "player-1",
        "round-1",
        TimeRange(1, 2),
        __import__(
            "cs2pov.domain.timebase", fromlist=["SourceClock"]
        ).SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-1",
        0,
        1,
        "hello",
        "en",
        None,
        ("anchor-1",),
        (),
        "asr-1",
    )
    r = UnderstandingResult(
        "cue-1", "round-1", "hello", "hello", "你好", 1, ("e",), (), "llm-1"
    )
    assert r.content_fingerprint()
    assert RoundUnderstandingDocument.from_dict(
        RoundUnderstandingDocument(
            "round-1", "a" * 64, "cfg-1", "llm-1", (r,)
        ).to_dict()
    ).results == (r,)


def test_bad_collections_are_domain_errors():
    import pytest
    from cs2pov.domain.errors import DomainSchemaError

    with pytest.raises(DomainSchemaError):
        VoiceActivityCue("a", "p", TimeRange(1, 2), 1, 123, 0)
    with pytest.raises(DomainSchemaError):
        RoundUnderstandingDocument.from_dict(
            {
                "schema_version": 1,
                "round_id": "r",
                "input_fingerprint": "a" * 64,
                "model_configuration_snapshot_id": "c",
                "invocation_record_id": None,
                "results": 123,
            }
        )


def test_transcript_rejects_reversed_source_and_bad_evidence_collections():
    import pytest
    from cs2pov.domain.errors import DomainSchemaError
    from cs2pov.domain.timebase import SourceClock

    with pytest.raises(DomainSchemaError):
        TranscriptCue(
            "c",
            "p",
            "r",
            TimeRange(1, 2),
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "p",
            2,
            1,
            "x",
            "en",
            None,
            ("a",),
            ("v",),
            "i",
        )
    with pytest.raises(DomainSchemaError):
        TranscriptCue(
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
            ("../x",),
            ("v",),
            "i",
        )
    with pytest.raises(DomainSchemaError):
        UnderstandingResult("c", "r", "x", "y", "z", 1, 123, (), "i")
    with pytest.raises(DomainSchemaError):
        UnderstandingResult("c", "r", "x", "y", "z", 1, ("e",), (123,), "i")


def test_transcript_jsonl_record_preserves_original_asr_and_integer_time():
    assert isinstance(
        TranscriptCue(
            "c",
            "p",
            None,
            TimeRange(1, 2),
            __import__(
                "cs2pov.domain.timebase", fromlist=["SourceClock"]
            ).SourceClock.COMPACT_AUDIO_SAMPLE,
            "p",
            0,
            1,
            "x",
            "en",
            None,
            ("a",),
            ("v",),
            "i",
        ).to_dict()["start_us"],
        int,
    )


def test_unassigned_transcript_is_explicit_and_round_trips():
    c = TranscriptCue(
        "c",
        "p",
        None,
        TimeRange(1, 2),
        __import__(
            "cs2pov.domain.timebase", fromlist=["SourceClock"]
        ).SourceClock.COMPACT_AUDIO_SAMPLE,
        "p",
        0,
        1,
        "x",
        "en",
        None,
        ("a",),
        ("v",),
        "i",
    )
    assert TranscriptCue.from_dict(c.to_dict()).round_id is None


def test_voice_activity_jsonl_record_preserves_anchor_evidence():
    assert VoiceActivityCue.from_dict(
        VoiceActivityCue("a", "p", TimeRange(1, 2), 1, ("anchor",), 0).to_dict()
    ).anchor_ids == ("anchor",)


def test_understanding_keeps_asr_interpretation_and_translation_separate():
    assert (
        UnderstandingResult(
            "c", "r", "asr", "source", "中文", 1, ("e",), (), "i"
        ).asr_original
        == "asr"
    )


def test_understanding_content_fingerprint_changes_with_meaning():
    a = UnderstandingResult("c", "r", "a", "b", "c", 1, ("e",), (), "i")
    b = UnderstandingResult("c", "r", "a", "b", "d", 1, ("e",), (), "i")
    assert a.content_fingerprint() != b.content_fingerprint()


def test_speechless_round_is_successful_without_fake_model_call():
    assert (
        RoundUnderstandingDocument("r", "a" * 64, "cfg", None, ()).invocation_record_id
        is None
    )
