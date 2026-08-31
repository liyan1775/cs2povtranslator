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
