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
