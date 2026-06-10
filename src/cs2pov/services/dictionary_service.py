from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    """A conservative CS2 callout glossary entry.

    v0.6.0 intentionally ships only a Mirage pilot glossary.  The terms below
    are not meant to be a complete map annotation.  They are prompt constraints
    for common POV subtitle translation cases and are annotated with confidence
    so that low-certainty terms do not silently pretend to be authoritative.
    """

    term_id: str
    map_name: str
    zone: str
    category: str
    preferred_zh: str
    english: tuple[str, ...]
    russian: tuple[str, ...] = ()
    zh_aliases: tuple[str, ...] = ()
    note: str = ""
    confidence: str = "medium"  # high | medium | low
    sources: tuple[str, ...] = ()

    @property
    def source(self) -> str:
        """Backward-compatible primary English source term."""
        return self.english[0] if self.english else self.term_id

    @property
    def zh(self) -> str:
        """Backward-compatible preferred Chinese translation."""
        return self.preferred_zh

    def to_prompt_item(self) -> dict[str, Any]:
        return {
            "id": self.term_id,
            "zone": self.zone,
            "source": self.source,
            "en": list(self.english),
            "ru": list(self.russian),
            "zh": self.preferred_zh,
            "zh_aliases": list(self.zh_aliases),
            "confidence": self.confidence,
            "note": self.note,
        }


# Conservative Mirage pilot glossary.
# Source tags are documented in docs/GLOSSARY_MIRAGE_PILOT.zh.md.
MIRAGE_GLOSSARY: tuple[GlossaryTerm, ...] = (
    GlossaryTerm(
        "mirage_a_ramp", "de_mirage", "A", "callout", "A1/A门",
        english=("a ramp", "ramp", "t ramp", "pit"),
        russian=("яма", "пит", "рамп", "рампа"),
        zh_aliases=("A1", "A门", "斜坡", "匪斜坡"),
        note="T 方进攻 A 区的主入口。中文社区常把 Mirage A Ramp 叫 A1/A门；若上下文不明确，可保留 A1。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "17173_cn", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_palace", "de_mirage", "A", "callout", "A二楼",
        english=("palace", "a palace", "palace balcony"),
        russian=("палас", "ковры"),
        zh_aliases=("二楼", "A二楼", "二楼上", "二楼下"),
        note="A 区二楼/Palace。俄语语音里 ковры 也可能指 Palace。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "steam_ru", "profilerr_ru"),
    ),
    GlossaryTerm(
        "mirage_connector", "de_mirage", "mid", "callout", "拱门",
        english=("connector", "con", "conn", "up con", "under con"),
        russian=("коннектор", "кон", "коник", "перемычка"),
        zh_aliases=("VIP/拱门", "拱门上", "拱门下"),
        note="连接中路和 A 区的 Connector。中文社区常叫拱门；俄语也会简称 кон。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "17173_cn", "cybersport_ru", "respawn_ru", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_jungle", "de_mirage", "A/mid", "callout", "Jungle/警家连接",
        english=("jungle", "jungle side"),
        russian=("джангл", "джунгли", "хелпа"),
        zh_aliases=("Jungle", "警家", "VIP", "警家连接"),
        note="Jungle 中文叫法分歧较大：有资料保留 Jungle，也有人报 VIP/警家附近。v0.6.0 暂用『Jungle/警家连接』避免误导。",
        confidence="medium",
        sources=("dmarket", "cs2util_cn", "17173_cn", "cybersport_ru", "respawn_ru", "stavka_ru", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_stairs", "de_mirage", "A", "callout", "跳台/楼梯",
        english=("stairs", "a stairs"),
        russian=("стэйрс", "лестница"),
        zh_aliases=("跳台", "楼梯", "跳台楼梯"),
        note="A 点靠近拱门/Jungle 的楼梯高点。中文资料常见跳台/楼梯两种说法。",
        confidence="high",
        sources=("totalcsgo", "dmarket", "cs2util_cn", "17173_cn", "betteam_ru"),
    ),
    GlossaryTerm(
        "mirage_ticket", "de_mirage", "A", "callout", "售票亭",
        english=("ticket", "ticket booth", "ct ticket"),
        russian=("тикет", "билет"),
        zh_aliases=("警亭", "售票亭", "警家狙位"),
        note="A 点警家附近灰色柱/售票亭。不同中文社区也会叫警亭。",
        confidence="high",
        sources=("dmarket", "totalcsgo", "cs2util_cn", "5e_cn", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_tetris", "de_mirage", "A", "callout", "长箱/Tetris",
        english=("tetris",),
        russian=("тетрис",),
        zh_aliases=("长箱", "Tetris"),
        note="A1 出来靠近 A 点的箱位。中文资料有时叫长箱，国际交流中常保留 Tetris。",
        confidence="medium",
        sources=("totalcsgo", "cs2util_cn", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_sandwich", "de_mirage", "A", "callout", "三明治",
        english=("sandwich",),
        russian=("сендвич",),
        zh_aliases=("三明治",),
        note="A 点 Stairs 与 Tetris 之间的小凹位。",
        confidence="high",
        sources=("totalcsgo", "5e_cn", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_mid", "de_mirage", "mid", "callout", "中路",
        english=("mid", "middle"),
        russian=("мид", "мидл"),
        zh_aliases=("中路",),
        note="Mirage 中路区域。",
        confidence="high",
        sources=("skinrave", "profilerr", "17173_cn", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_top_mid", "de_mirage", "mid", "callout", "中远/匪口",
        english=("top mid", "mid boxes", "cart"),
        russian=("топ мид", "ящики", "коробка"),
        zh_aliases=("中远", "匪口", "沙袋", "草车"),
        note="T 方进入中路的上段；中文资料有中远、匪口、沙袋/草车等叫法。",
        confidence="medium",
        sources=("skinrave", "cs2util_cn", "17173_cn", "cybersport_ru"),
    ),
    GlossaryTerm(
        "mirage_window", "de_mirage", "mid", "callout", "VIP/窗口",
        english=("window", "sniper's nest", "sniper nest"),
        russian=("окно", "снайперское гнездо"),
        zh_aliases=("VIP", "窗户", "中路窗口"),
        note="CT 控中路的 Window/Sniper's Nest。中文常叫 VIP 或窗户。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "5e_cn", "respawn_ru"),
    ),
    GlossaryTerm(
        "mirage_underpass", "de_mirage", "mid", "callout", "下水道",
        english=("underpass", "under", "under window"),
        russian=("андер", "под окном"),
        zh_aliases=("下水道", "下水道楼梯"),
        note="连接 B 二楼/匪二楼与中路下方的地下通道。",
        confidence="high",
        sources=("hellcase", "cs2util_cn", "17173_cn", "cybersport_ru", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_catwalk_short", "de_mirage", "mid/B", "callout", "B小",
        english=("catwalk", "cat", "short", "b short"),
        russian=("шорт", "зига"),
        zh_aliases=("B小", "小道", "过点"),
        note="中路通往 B 点的 Catwalk/B Short。Mirage 中文 POV 更建议写 B小，避免和其他地图 short 混淆。",
        confidence="high",
        sources=("skinrave", "dmarket", "cs2util_cn", "17173_cn", "cybersport_ru", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_ladder_room", "de_mirage", "mid/B", "callout", "梯子房",
        english=("ladder", "ladder room"),
        russian=("лестница", "ладер рум"),
        zh_aliases=("梯子", "梯子房"),
        note="连接 B 小和 VIP/窗口附近的小房间。",
        confidence="high",
        sources=("skinrave", "cs2util_cn", "17173_cn", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_b_apps", "de_mirage", "B", "callout", "B二楼",
        english=("apps", "apartments", "b apps", "b apartments"),
        russian=("апартаменты", "апсы"),
        zh_aliases=("B二楼", "二楼", "匪二楼"),
        note="T 方通往 B 点的二楼/公寓。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "steam_ru", "cybersport_ru"),
    ),
    GlossaryTerm(
        "mirage_balcony", "de_mirage", "B", "callout", "阳台",
        english=("balcony", "b balcony", "plat", "platform"),
        russian=("балкон", "платформа"),
        zh_aliases=("阳台", "B二楼平台"),
        note="B 二楼出点的平台/阳台。",
        confidence="medium",
        sources=("cs2util_cn", "5e_cn", "cybersport_ru"),
    ),
    GlossaryTerm(
        "mirage_market", "de_mirage", "B", "callout", "超市",
        english=("market", "kitchen", "shop"),
        russian=("маркет", "кухня", "кичен"),
        zh_aliases=("超市", "厨房"),
        note="B 点 CT 侧回防房间。英文 Market/Kitchen 都可能出现；中文多数叫超市，也有人叫厨房。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "5e_cn", "cybersport_ru", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_market_window", "de_mirage", "B", "callout", "超市窗口",
        english=("market window", "window market"),
        russian=("окно маркета", "окно"),
        zh_aliases=("超市窗口", "窗口"),
        note="Market 内看向 B 点的窗口。",
        confidence="medium",
        sources=("skinrave", "cs2util_cn", "cybersport_ru"),
    ),
    GlossaryTerm(
        "mirage_market_door", "de_mirage", "B", "callout", "超市门",
        english=("market door", "door"),
        russian=("дверь",),
        zh_aliases=("超市门", "超市大门"),
        note="Market 通往 B 点的门。仅当上下文明确在 B 点时使用。",
        confidence="medium",
        sources=("skinrave", "cs2util_cn", "steam_ru"),
    ),
    GlossaryTerm(
        "mirage_bench", "de_mirage", "B", "callout", "长椅",
        english=("bench",),
        russian=("скамейка", "бенч", "форест", "f0rest"),
        zh_aliases=("长椅", "长凳", "板凳"),
        note="B 点靠近包点的 Bench。注意中路也可能有长椅，若上下文不明确保留更具体表述。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "17173_cn", "cybersport_ru", "betteam_ru"),
    ),
    GlossaryTerm(
        "mirage_van", "de_mirage", "B", "callout", "白车",
        english=("van", "car"),
        russian=("тачка", "ван"),
        zh_aliases=("白车", "车位"),
        note="B 点白车/Van。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "cybersport_ru"),
    ),
    GlossaryTerm(
        "mirage_b_default", "de_mirage", "B", "plant", "默认包位",
        english=("default", "default plant"),
        russian=("дефолт",),
        zh_aliases=("默认包", "包位", "B小包位", "二楼包位"),
        note="下包位置类词条，具体译法需要结合 A/B 点上下文。",
        confidence="medium",
        sources=("cs2util_cn", "cybersport_ru"),
    ),
)

MAP_GLOSSARIES: dict[str, tuple[GlossaryTerm, ...]] = {"de_mirage": MIRAGE_GLOSSARY}
SUPPORTED_MAPS = tuple(sorted(MAP_GLOSSARIES))
PILOT_MAP = "de_mirage"


def get_map_glossary(map_name: str | None) -> list[GlossaryTerm]:
    if not map_name:
        return []
    return list(MAP_GLOSSARIES.get(map_name.lower(), ()))


def is_glossary_supported(map_name: str | None) -> bool:
    return bool(map_name and map_name.lower() in MAP_GLOSSARIES)


def detect_terms(text: str, terms: Iterable[GlossaryTerm]) -> list[GlossaryTerm]:
    matched: list[GlossaryTerm] = []
    for term in terms:
        if _term_matches_text(text, term):
            matched.append(term)
    return matched


def detect_terms_in_texts(texts: Iterable[str], terms: Iterable[GlossaryTerm]) -> dict[str, int]:
    counts: dict[str, int] = {}
    terms_list = list(terms)
    for text in texts:
        for term in detect_terms(text, terms_list):
            counts[term.term_id] = counts.get(term.term_id, 0) + 1
    return counts


def format_glossary_for_prompt(map_name: str | None, texts: Iterable[str] | None = None, limit: int = 40) -> list[dict[str, Any]]:
    terms = get_map_glossary(map_name)
    if not terms:
        return []
    if texts is not None:
        counts = detect_terms_in_texts(texts, terms)
        terms = sorted(terms, key=lambda t: (-counts.get(t.term_id, 0), _confidence_rank(t.confidence), t.zone, t.term_id))
    else:
        terms = sorted(terms, key=lambda t: (_confidence_rank(t.confidence), t.zone, t.term_id))
    return [t.to_prompt_item() for t in terms[:limit]]


def build_glossary_used_report(map_name: str | None, texts: Iterable[str]) -> dict[str, Any]:
    terms = get_map_glossary(map_name)
    counts = detect_terms_in_texts(texts, terms)
    used = [
        {
            **term.to_prompt_item(),
            "matched_in_transcript": counts.get(term.term_id, 0),
        }
        for term in terms
    ]
    return {
        "schema_version": 1,
        "map_name": map_name,
        "supported": is_glossary_supported(map_name),
        "pilot_map": PILOT_MAP,
        "scope_note": "v0.6.0 仅试点 de_mirage，词条保守收录；其他地图暂不注入地图词典。",
        "term_count": len(terms),
        "matched_term_count": sum(1 for v in counts.values() if v > 0),
        "terms": used,
        "source_tags": sorted({tag for term in terms for tag in term.sources}),
    }


def validate_translation_terms(original_text: str, translated_text: str, map_name: str | None) -> list[dict[str, Any]]:
    terms = detect_terms(original_text, get_map_glossary(map_name))
    warnings: list[dict[str, Any]] = []
    for term in terms:
        acceptable = {term.preferred_zh, *term.zh_aliases}
        if translated_text and translated_text.startswith("["):
            continue
        if not any(alias and alias in translated_text for alias in acceptable):
            warnings.append({
                "term_id": term.term_id,
                "source": term.source,
                "preferred_zh": term.preferred_zh,
                "acceptable_zh": sorted(acceptable),
                "confidence": term.confidence,
                "original_text": original_text,
                "translated_text": translated_text,
                "message": "原文疑似出现该报点，但译文未包含推荐中文叫法；可能是 ASR 误识别、上下文不适用，或需要人工复核。",
            })
    return warnings


def build_glossary_warning_report(map_name: str | None, segment_warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "map_name": map_name,
        "supported": is_glossary_supported(map_name),
        "warning_count": len(segment_warnings),
        "warnings": segment_warnings,
        "note": "这些 warning 是保守校验，不代表翻译一定错误；用于发现术语不稳定和后续人工调词典。",
    }


def glossary_terms_as_dicts(map_name: str | None) -> list[dict[str, Any]]:
    return [term.to_prompt_item() | {"sources": list(term.sources)} for term in get_map_glossary(map_name)]


def _confidence_rank(value: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value, 9)


def _term_matches_text(text: str, term: GlossaryTerm) -> bool:
    if not text:
        return False
    candidates = [*term.english, *term.russian]
    lowered = text.casefold()
    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        if _contains_candidate(lowered, cand.casefold()):
            return True
    return False


def _contains_candidate(text: str, candidate: str) -> bool:
    # ASCII callouts should be matched as words to avoid overmatching "market" in unrelated text.
    if re.fullmatch(r"[a-z0-9_ /'\-]+", candidate):
        parts = [p for p in re.split(r"[/,]", candidate) if p.strip()]
        for part in parts:
            compact = part.strip().replace("'", "")
            if not compact:
                continue
            pattern = r"(?<![a-z0-9])" + re.escape(compact) + r"(?![a-z0-9])"
            if re.search(pattern, text):
                return True
        return False
    return candidate in text
