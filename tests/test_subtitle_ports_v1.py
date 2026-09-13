from dataclasses import replace

import pytest

from cs2pov.application.subtitle_ports import (
    CurrentVoiceActivity,
    adapt_draft_timeline,
    export_current_subtitle_preset,
    export_current_subtitle_scopes,
    format_demo_time_srt,
    microseconds_to_srt_milliseconds,
    render_current_srt,
)
from cs2pov.domain.review import DraftCommsCue, DraftCommsTimeline


HASH = "a" * 64


def _timeline():
    return DraftCommsTimeline(
        HASH,
        "demo-microseconds",
        HASH,
        (
            DraftCommsCue(
                "cue-1", "round-1", "player-1", 1_000_499, 2_000_501,
                "go", "go", "走", 0.9, ("evidence",), HASH,
            ),
        ),
    )


def test_microseconds_to_srt_milliseconds_uses_explicit_half_up_rule():
    assert microseconds_to_srt_milliseconds(1_000_499) == 1_000
    assert microseconds_to_srt_milliseconds(1_000_500) == 1_001
    assert format_demo_time_srt(3_661_001_500) == "01:01:01,002"


def test_draft_adapter_keeps_integer_source_clock_and_adds_display_metadata():
    cue = adapt_draft_timeline(
        _timeline(), player_names={"player-1": "Alpha"}, team_numbers={"player-1": 2}
    )[0]
    assert cue.start_us == 1_000_499
    assert cue.end_us == 2_000_501
    assert cue.player_name == "Alpha"
    assert cue.team_number == 2


def test_current_export_objects_support_existing_policy_replace_contract():
    cue = adapt_draft_timeline(_timeline())[0]
    adjusted = replace(cue, start_time=4.25, end_time=5.5)
    assert adjusted.start_time == 4.25
    assert adjusted.end_time == 5.5
    assert adjusted.start_us == cue.start_us
    assert adjusted.end_us == cue.end_us
    voice = CurrentVoiceActivity("activity-1", "player-1", "Alpha", 0, 1_000_000, 3)
    adjusted_voice = replace(voice, start_time=1.25, end_time=2.5)
    assert (adjusted_voice.start_time, adjusted_voice.end_time) == (1.25, 2.5)
    assert (adjusted_voice.start_us, adjusted_voice.end_us) == (0, 1_000_000)


def test_render_preserves_existing_format_semantics_and_uses_integer_clock():
    cues = adapt_draft_timeline(_timeline(), player_names={"player-1": "Alpha"})
    output = render_current_srt(cues, "bilingual", preset="review")
    assert "[Alpha] go\n[中文] 走" in output
    assert "00:00:01,000 --> 00:00:02,001" in output
    assert "00:00:01.000" not in output


def test_render_uses_half_up_rounding_for_exact_half_millisecond():
    timeline = DraftCommsTimeline(
        HASH,
        "demo-microseconds",
        HASH,
        (
            DraftCommsCue(
                "cue-half",
                "round-1",
                "player-1",
                1_000_500,
                2_000_500,
                "go",
                "go",
                "走",
                0.9,
                ("evidence",),
                HASH,
            ),
        ),
    )
    output = render_current_srt(
        adapt_draft_timeline(timeline), "bilingual", preset="review"
    )
    assert "00:00:01,001 --> 00:00:02,001" in output


def test_preset_exports_full_and_round_scoped_outputs():
    timeline = _timeline()
    full = export_current_subtitle_preset(timeline, "editing", player_names={"player-1": "Alpha"})
    round_one = export_current_subtitle_preset(
        timeline, "compact", player_names={"player-1": "Alpha"}, round_id="round-1"
    )
    assert set(full) == {"compact", "zh", "bilingual"}
    assert set(round_one) == {"compact"}
    assert "[Alpha] go\n走" in full["compact"]
    scopes = export_current_subtitle_scopes(timeline, "compact", player_names={"player-1": "Alpha"})
    assert set(scopes) == {"full", "rounds"}
    assert set(scopes["rounds"]) == {"round-1"}


def test_unknown_format_and_invalid_clock_are_rejected():
    with pytest.raises(ValueError, match="未知字幕格式"):
        render_current_srt(adapt_draft_timeline(_timeline()), "nope")
    with pytest.raises(ValueError):
        microseconds_to_srt_milliseconds(-1)
