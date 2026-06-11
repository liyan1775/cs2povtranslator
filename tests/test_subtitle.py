from cs2pov.domain.models import TranslationSegment
from cs2pov.domain.subtitle import bilingual_text, format_srt_time, render_srt


def test_format_srt_time():
    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(65.432) == "00:01:05,432"


def test_render_bilingual_srt_label_default():
    seg = TranslationSegment(
        id="a", steamid="1", player_name="donk", team_number=2,
        start_time=1.0, end_time=2.0, original_text="one jungle", translated_text="一个警家",
    )
    srt = render_srt([seg], bilingual_text)
    assert "[donk] one jungle" in srt
    assert "[中文] 一个警家" in srt
    assert "→" not in srt


def test_render_bilingual_srt_arrow_legacy():
    seg = TranslationSegment(
        id="a", steamid="1", player_name="donk", team_number=2,
        start_time=1.0, end_time=2.0, original_text="one jungle", translated_text="一个警家",
    )
    srt = render_srt([seg], lambda item: bilingual_text(item, style="arrow"))
    assert "→ 一个警家" in srt


def test_merge_policy_combines_overlapping_speakers_into_single_srt_cue():
    from cs2pov.domain.subtitle import SubtitlePolicy

    first = TranslationSegment(
        id="a", steamid="s1", player_name="donk", team_number=2,
        start_time=1.0, end_time=3.0, original_text="one cave", translated_text="山洞一个",
    )
    second = TranslationSegment(
        id="b", steamid="s2", player_name="zont1x", team_number=2,
        start_time=2.0, end_time=4.0, original_text="flash out", translated_text="给闪出去",
    )
    srt = render_srt([first, second], bilingual_text, policy=SubtitlePolicy(name="editing", overlap_policy="merge"))

    assert "1\n00:00:01,000 --> 00:00:04,000" in srt
    assert "\n2\n" not in srt
    assert "[donk] one cave" in srt
    assert "[中文] 山洞一个" in srt
    assert "[zont1x] flash out" in srt
    assert "[中文] 给闪出去" in srt


def test_merge_policy_keeps_non_overlapping_cues_separate():
    from cs2pov.domain.subtitle import SubtitlePolicy

    first = TranslationSegment("a", "s1", "donk", 2, 1.0, 2.0, "one", "一个")
    second = TranslationSegment("b", "s2", "zont1x", 2, 2.2, 3.0, "two", "两个")
    srt = render_srt([first, second], bilingual_text, policy=SubtitlePolicy(name="editing", overlap_policy="merge"))

    assert "1\n00:00:01,000 --> 00:00:02,000" in srt
    assert "2\n00:00:02,200 --> 00:00:03,000" in srt


def test_stack_policy_keeps_at_most_two_visible_speakers_and_replaces_oldest():
    from cs2pov.domain.subtitle import SubtitlePolicy

    first = TranslationSegment("a", "s1", "A", 2, 1.0, 5.0, "first", "第一条")
    second = TranslationSegment("b", "s2", "B", 2, 2.0, 6.0, "second", "第二条")
    third = TranslationSegment("c", "s3", "C", 2, 3.0, 4.0, "third", "第三条")
    srt = render_srt([first, second, third], bilingual_text, policy=SubtitlePolicy(name="editing", overlap_policy="stack"))

    assert "1\n00:00:01,000 --> 00:00:02,000" in srt
    assert "2\n00:00:02,000 --> 00:00:03,000" in srt
    assert "[A] first" in srt.split("3\n00:00:03,000 --> 00:00:04,000", 1)[0]
    third_window = srt.split("3\n00:00:03,000 --> 00:00:04,000", 1)[1].split("\n\n", 1)[0]
    assert "[A] first" not in third_window
    assert "[B] second" in third_window
    assert "[C] third" in third_window
    assert third_window.count("[中文]") == 2
    tail_window = srt.split("4\n00:00:04,000 --> 00:00:06,000", 1)[1]
    assert "[A] first" not in tail_window
    assert "[B] second" in tail_window


def test_editing_preset_defaults_to_stack_not_merge():
    from cs2pov.domain.subtitle import policy_from_preset

    policy = policy_from_preset("editing")
    assert policy.overlap_policy == "stack"
    assert policy.max_visible_cues == 2


def test_stack_policy_updates_same_speaker_slot_instead_of_showing_duplicate_player_blocks():
    from cs2pov.domain.subtitle import SubtitlePolicy

    first = TranslationSegment("a", "s1", "A", 2, 1.0, 4.0, "old call", "旧信息")
    update = TranslationSegment("b", "s1", "A", 2, 2.0, 5.0, "new call", "新信息")
    other = TranslationSegment("c", "s2", "B", 2, 2.5, 5.0, "other call", "其他信息")
    srt = render_srt([first, update, other], bilingual_text, policy=SubtitlePolicy(name="editing", overlap_policy="stack"))

    window = srt.split("00:00:02,500 -->", 1)[1].split("\n\n", 1)[0]
    assert "[A] old call" not in window
    assert "[A] new call" in window
    assert "[B] other call" in window
    assert window.count("[A]") == 1
