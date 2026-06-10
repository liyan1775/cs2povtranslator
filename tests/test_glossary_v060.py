from cs2pov.services.dictionary_service import (
    build_glossary_used_report,
    detect_terms,
    format_glossary_for_prompt,
    get_map_glossary,
    validate_translation_terms,
)


def test_mirage_glossary_has_english_russian_chinese_alignment():
    terms = get_map_glossary("de_mirage")
    connector = next(t for t in terms if t.term_id == "mirage_connector")
    assert "connector" in connector.english
    assert "коннектор" in connector.russian
    assert connector.preferred_zh == "拱门"


def test_detects_russian_and_english_terms():
    terms = get_map_glossary("de_mirage")
    matched = {t.term_id for t in detect_terms("one кон and one palace", terms)}
    assert "mirage_connector" in matched
    assert "mirage_palace" in matched


def test_prompt_prioritizes_matched_terms():
    payload = format_glossary_for_prompt("de_mirage", ["one bench and market"], limit=4)
    ids = [item["id"] for item in payload]
    assert "mirage_bench" in ids[:2]
    assert "mirage_market" in ids[:3]


def test_glossary_warning_for_missing_preferred_zh():
    warnings = validate_translation_terms("one connector", "一个在连接处", "de_mirage")
    assert warnings
    assert warnings[0]["preferred_zh"] == "拱门"


def test_glossary_report_marks_unsupported_map():
    report = build_glossary_used_report("de_dust2", ["one long"])
    assert report["supported"] is False
    assert report["term_count"] == 0
