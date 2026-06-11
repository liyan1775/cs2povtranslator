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


def test_glossary_report_marks_unsupported_map_but_keeps_global_terms():
    report = build_glossary_used_report("de_inferno", ["push awp trade"])
    assert report["map_supported"] is False
    assert report["global_supported"] is True
    assert report["global_term_count"] > 0
    assert report["map_term_count"] == 0
    assert report["matched_global_term_count"] >= 3


def test_global_glossary_warns_common_mistranslation():
    warnings = validate_translation_terms("please trade me", "请和我交易", "de_mirage")
    assert warnings
    assert warnings[0]["scope"] == "global"
    assert warnings[0]["preferred_zh"] == "补枪"


def test_global_nade_does_not_match_english_pronoun_he():
    warnings = validate_translation_terms("I kill if he push mid.", "他压中路的话我杀他", "de_mirage")
    ids = {item["term_id"] for item in warnings}
    assert "global_nade" not in ids


def test_global_nade_matches_explicit_he_grenade_phrase():
    warnings = validate_translation_terms("throw HE grenade mid", "往中路丢雷", "de_mirage")
    assert warnings == []


def test_global_boost_accepts_natural_jiawo_translation():
    warnings = validate_translation_terms("gimme boost up mid please", "请架我上中路", "de_mirage")
    ids = {item["term_id"] for item in warnings}
    assert "global_boost" not in ids


def test_global_push_accepts_short_ya_translation():
    warnings = validate_translation_terms("I kill if he push mid.", "他压中路的话我杀他", "de_mirage")
    ids = {item["term_id"] for item in warnings}
    assert "global_push" not in ids


def test_dust2_glossary_is_supported_and_contains_core_callouts():
    terms = get_map_glossary("de_dust2")
    ids = {t.term_id for t in terms}
    assert "dust2_a_long" in ids
    assert "dust2_short" in ids
    assert "dust2_b_tunnels" in ids
    assert "dust2_xbox" in ids


def test_dust2_prompt_prioritizes_matched_terms():
    payload = format_glossary_for_prompt("de_dust2", ["one long one short and one xbox"], limit=8)
    ids = [item["id"] for item in payload]
    assert "dust2_a_long" in ids
    assert "dust2_short" in ids
    assert "dust2_xbox" in ids


def test_dust2_warning_accepts_natural_chinese_callouts():
    warnings = validate_translation_terms("one long and one short", "一个A大一个小道", "de_dust2")
    ids = {item["term_id"] for item in warnings}
    assert "dust2_a_long" not in ids
    assert "dust2_short" not in ids


def test_dust2_warning_catches_machine_translation_style_errors():
    warnings = validate_translation_terms("one short and one xbox", "一个短的，一个Xbox游戏机", "de_dust2")
    ids = {item["term_id"] for item in warnings}
    assert "dust2_short" in ids
    assert "dust2_xbox" in ids


def test_dust2_report_marks_supported_map():
    report = build_glossary_used_report("de_dust2", ["push long then split short to b tunnels"])
    assert report["map_supported"] is True
    assert "de_dust2" in report["pilot_maps"]
    assert report["map_term_count"] > 20
    assert report["matched_map_term_count"] >= 3


def test_anubis_glossary_is_supported_and_contains_core_callouts():
    terms = get_map_glossary("de_anubis")
    ids = {t.term_id for t in terms}
    assert "anubis_canal" in ids
    assert "anubis_bridge" in ids
    assert "anubis_a_main" in ids
    assert "anubis_b_long" in ids
    assert "anubis_temple" in ids


def test_anubis_prompt_prioritizes_matched_terms():
    payload = format_glossary_for_prompt("de_anubis", ["one canal one bridge and one b long"], limit=8)
    ids = [item["id"] for item in payload]
    assert "anubis_canal" in ids
    assert "anubis_bridge" in ids
    assert "anubis_b_long" in ids


def test_anubis_warning_accepts_natural_chinese_callouts():
    warnings = validate_translation_terms("one canal and one bridge", "一个水道一个桥", "de_anubis")
    ids = {item["term_id"] for item in warnings}
    assert "anubis_canal" not in ids
    assert "anubis_bridge" not in ids


def test_anubis_warning_catches_machine_translation_style_errors():
    warnings = validate_translation_terms("one temple and one trade", "一个寺庙，一个交易", "de_anubis")
    ids = {item["term_id"] for item in warnings}
    assert "anubis_temple" in ids
    assert "global_trade" in ids


def test_anubis_report_marks_supported_map():
    report = build_glossary_used_report("de_anubis", ["push canal then split bridge to b long"])
    assert report["map_supported"] is True
    assert "de_anubis" in report["pilot_maps"]
    assert report["map_term_count"] > 20
    assert report["matched_map_term_count"] >= 3


def test_anubis_cave_prefers_black_house_but_accepts_old_literal_translation():
    terms = get_map_glossary("de_anubis")
    cave = next(t for t in terms if t.term_id == "anubis_cave")
    assert cave.preferred_zh == "Cave/黑屋"
    assert "黑屋" in cave.zh_aliases
    assert "洞穴" in cave.zh_aliases

    warnings = validate_translation_terms("care cave", "小心黑屋", "de_anubis")
    ids = {item["term_id"] for item in warnings}
    assert "anubis_cave" not in ids

    legacy_warnings = validate_translation_terms("care cave", "小心洞穴", "de_anubis")
    legacy_ids = {item["term_id"] for item in legacy_warnings}
    assert "anubis_cave" not in legacy_ids


def test_mirage_feedback_callouts_prefer_cn_community_terms():
    terms = get_map_glossary("de_mirage")
    by_id = {term.term_id: term for term in terms}

    assert by_id["mirage_bench"].preferred_zh == "沙发"
    assert "长椅" in by_id["mirage_bench"].avoid
    assert by_id["mirage_ladder_room"].preferred_zh == "黑屋"
    assert "梯子房" in by_id["mirage_ladder_room"].avoid
    assert by_id["mirage_ninja"].preferred_zh == "忍者位"

    ok = validate_translation_terms("one bench one ladder and one ninja", "一个沙发一个黑屋一个忍者位", "de_mirage")
    ids = {item["term_id"] for item in ok}
    assert "mirage_bench" not in ids
    assert "mirage_ladder_room" not in ids
    assert "mirage_ninja" not in ids


def test_mirage_feedback_callouts_warn_literal_or_wrong_translations():
    warnings = validate_translation_terms("one bench one ladder", "一个长椅一个梯子房", "de_mirage")
    ids = {item["term_id"] for item in warnings}
    assert "mirage_bench" in ids
    assert "mirage_ladder_room" in ids


def test_anubis_stairs_prefers_t_spawn_callout():
    terms = get_map_glossary("de_anubis")
    stairs = next(term for term in terms if term.term_id == "anubis_stairs")
    assert stairs.preferred_zh == "匪口"
    assert "楼梯" in stairs.avoid
    assert "警口" in stairs.avoid

    ok = validate_translation_terms("one stairs", "一个匪口", "de_anubis")
    ids = {item["term_id"] for item in ok}
    assert "anubis_stairs" not in ids

    warnings = validate_translation_terms("one stairs", "一个楼梯", "de_anubis")
    warning_ids = {item["term_id"] for item in warnings}
    assert "anubis_stairs" in warning_ids
