from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    """A conservative CS2 callout glossary entry.

    v0.6.0 intentionally shipped a Mirage pilot glossary; v0.8.2 adds
    a conservative Dust2 pilot; v0.8.3 adds a conservative
    Anubis pilot for POV showcase testing; v0.8.4/v0.8.5 refine Chinese community callouts from real POV feedback.  The terms below are not meant to be a
    complete map annotation.  They are prompt constraints
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
    avoid: tuple[str, ...] = ()
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
            "avoid": list(self.avoid),
            "scope": "global" if self.map_name == "global" else "map",
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
        "mirage_ladder_room", "de_mirage", "mid/B", "callout", "黑屋",
        english=("ladder", "ladder room"),
        russian=("лестница", "ладер рум"),
        zh_aliases=("黑屋", "小黑屋", "B小黑屋"),
        avoid=("梯子房", "梯子"),
        note="连接 B 小和 VIP/窗口附近的小房间。中文 CS2 POV 字幕优先写『黑屋』，不建议直译成『梯子房』。",
        confidence="high",
        sources=("skinrave", "cs2util_cn", "17173_cn", "steam_ru", "user_feedback_cn"),
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
        "mirage_bench", "de_mirage", "B", "callout", "沙发",
        english=("bench",),
        russian=("скамейка", "бенч", "форест", "f0rest"),
        zh_aliases=("沙发", "B沙发", "沙发位"),
        avoid=("长椅", "长凳", "板凳"),
        note="Mirage B 点靠近包点的 Bench。中文 CS2 POV 里更常写『沙发』；『长椅』容易和 A 区/其他地图的长椅混淆，不作为本词条推荐。",
        confidence="high",
        sources=("dmarket", "skinrave", "cs2util_cn", "17173_cn", "cybersport_ru", "betteam_ru", "user_feedback_cn"),
    ),
    GlossaryTerm(
        "mirage_ninja", "de_mirage", "A", "callout", "忍者位",
        english=("ninja", "ninja box"),
        russian=("ниндзя",),
        zh_aliases=("忍者", "忍者位", "ninja位"),
        note="Mirage A 点常见阴人位。平台机翻容易按普通名词处理，字幕里优先写『忍者位』。",
        confidence="high",
        sources=("totalcsgo", "cs2util_cn", "user_feedback_cn"),
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



# Conservative Dust2 pilot glossary.
# v0.8.2 adds Dust2 because it is one of the most common POV/demo maps and
# because platform machine translation often mishandles short callouts such as
# long, short, cat, pit, goose, tunnels and xbox.  This list is intentionally
# small: it targets high-frequency locations for subtitle translation and
# warning reports rather than pretending to be a complete map atlas.
DUST2_GLOSSARY: tuple[GlossaryTerm, ...] = (
    GlossaryTerm(
        "dust2_a_long", "de_dust2", "A/long", "callout", "A大",
        english=("a long", "long doors", "outside long", "long corner", "long"),
        russian=("длина", "лонг", "длинна"),
        zh_aliases=("A大", "大路", "大道", "大门外", "A大外"),
        note="Dust2 T 方从 A 大门进攻 A 点的长通道。字幕里优先写 A大；若语音只说 long，也通常指 A大。",
        confidence="high",
        sources=("totalcsgo", "dmarket", "daddyskins", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_long_doors", "de_dust2", "A/long", "callout", "A大门",
        english=("long doors", "double doors long", "outside long"),
        russian=("двери лонга", "дверь лонга"),
        zh_aliases=("大门", "A大门", "长门"),
        note="A Long 入口双门。注意 doors 在 Dust2 可能指中门/B门，只有上下文明确在 A Long 时才用 A大门。",
        confidence="high",
        sources=("dmarket", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_pit", "de_dust2", "A/long", "callout", "大坑",
        english=("pit", "long pit", "a pit"),
        russian=("яма", "пит"),
        zh_aliases=("坑", "坑里", "大坑位"),
        note="A 大尽头靠墙凹位。中文 POV 基本写大坑。",
        confidence="high",
        sources=("dmarket", "skinrave", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_side_pit", "de_dust2", "A/long", "callout", "大坑边",
        english=("side pit", "pit side"),
        russian=("сайд пит",),
        zh_aliases=("坑边", "大坑旁", "坑旁"),
        note="大坑旁边贴墙/平台边缘位置。",
        confidence="medium",
        sources=("totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_blue", "de_dust2", "A/long", "callout", "蓝箱",
        english=("blue", "blue box", "long blue"),
        russian=("синий", "синий ящик"),
        zh_aliases=("蓝车", "蓝箱子", "A大蓝箱"),
        note="A 大外/长门附近蓝色箱/车位，社区叫法会有差异。",
        confidence="medium",
        sources=("dmarket", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_a_car", "de_dust2", "A/long", "callout", "A车",
        english=("a car", "car", "long car"),
        russian=("машина", "кар"),
        zh_aliases=("车位", "长车", "A大车"),
        note="A 大靠近 A 点的车位。car 在 B 点也可能出现，warning 只作复核线索。",
        confidence="medium",
        sources=("daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_a_ramp", "de_dust2", "A", "callout", "A斜坡",
        english=("a ramp", "ramp"),
        russian=("рамп", "рампа"),
        zh_aliases=("斜坡", "A坡"),
        note="从 A 大/小道上 A 包点的斜坡区域。ramp 在其他地图含义不同，需结合 de_dust2 上下文。",
        confidence="high",
        sources=("daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_a_site", "de_dust2", "A", "callout", "A包点",
        english=("a site", "bombsite a", "a bombsite"),
        russian=("а плент", "а сайт"),
        zh_aliases=("A点", "A区", "A平台"),
        note="Dust2 A 包点。",
        confidence="high",
        sources=("dmarket", "daddyskins", "totalcsgo"),
    ),
    GlossaryTerm(
        "dust2_goose", "de_dust2", "A", "callout", "鹅位",
        english=("goose", "goose corner"),
        russian=("гусь", "гус"),
        zh_aliases=("鹅", "A鹅位"),
        note="A 点靠墙角落，名称来自墙上 goose 涂鸦。字幕里写鹅位更像 CS2 报点。",
        confidence="high",
        sources=("skinrave", "dmarket", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_short", "de_dust2", "mid/A", "callout", "A小/小道",
        english=("a short", "short", "cat", "catwalk"),
        russian=("шорт", "кот", "кэт"),
        zh_aliases=("A小", "小道", "猫道", "cat"),
        note="Dust2 中路上 A 的小道/Catwalk。中文视频里 A小/小道都自然。",
        confidence="high",
        sources=("dmarket", "daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_short_stairs", "de_dust2", "mid/A", "callout", "小道楼梯",
        english=("short stairs", "cat stairs", "stairs"),
        russian=("лестница шорта", "ступеньки"),
        zh_aliases=("A小楼梯", "楼梯", "小道台阶"),
        note="连接 Catwalk/A Short 与 A 点的楼梯/台阶。",
        confidence="medium",
        sources=("yallacompass", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_mid", "de_dust2", "mid", "callout", "中路",
        english=("mid", "middle"),
        russian=("мид", "мидл"),
        zh_aliases=("中", "中门附近", "压中"),
        note="Dust2 中路。短字幕中『压中』也可视为自然表达。",
        confidence="high",
        sources=("totalcsgo", "daddyskins", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_top_mid", "de_dust2", "mid", "callout", "中远/中路上",
        english=("top mid", "top middle", "upper mid"),
        russian=("топ мид", "верх мида"),
        zh_aliases=("中远", "中路上", "匪口中路", "中路上方"),
        note="靠近 T spawn 的中路上段。中文叫法会因社区不同而变化。",
        confidence="medium",
        sources=("daddyskins", "blog_cs2ad", "totalcsgo"),
    ),
    GlossaryTerm(
        "dust2_mid_doors", "de_dust2", "mid", "callout", "中门",
        english=("mid doors", "middle doors", "double doors", "doors"),
        russian=("мид двери", "двери мида", "дабл дорс"),
        zh_aliases=("中路门", "双门", "中双门"),
        note="Dust2 中路双门。doors 可能也指 A大门/B门，若上下文不明确需人工复核。",
        confidence="medium",
        sources=("totalcsgo", "dmarket", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_xbox", "de_dust2", "mid", "callout", "Xbox箱",
        english=("xbox", "x box"),
        russian=("иксбокс", "xbox"),
        zh_aliases=("中路箱", "Xbox", "X箱"),
        avoid=("游戏机",),
        note="中门附近可跳上小道的箱子。字幕可保留 Xbox，也可写 Xbox箱；不要解释成游戏机。",
        confidence="high",
        sources=("totalcsgo", "daddyskins", "skinrave", "blog_cs2ad"),
    ),
    GlossaryTerm(
        "dust2_suicide", "de_dust2", "mid", "callout", "自杀位",
        english=("suicide", "suicide mid"),
        russian=("суицид", "суисайд"),
        zh_aliases=("匪口中路", "自杀道", "自杀"),
        note="T spawn 直接通往中路的暴露通道。",
        confidence="high",
        sources=("daddyskins", "skinrave", "blog_cs2ad", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_ct_mid", "de_dust2", "mid", "callout", "警中/警家中路",
        english=("ct mid", "ct middle", "ct"),
        russian=("кт мид", "сити мид"),
        zh_aliases=("警中", "警家中", "CT中"),
        note="靠近 CT spawn 的中路区域。若只听到 CT，可能是警家或 CT 侧，需结合上下文。",
        confidence="medium",
        sources=("daddyskins", "blog_cs2ad", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_b_tunnels", "de_dust2", "B", "callout", "B洞",
        english=("b tunnels", "tunnels", "tunnel", "tuns"),
        russian=("тоннель", "туннель", "тонны"),
        zh_aliases=("洞", "B洞口", "B通道"),
        note="T spawn 通往 B 点的洞。上下文明确时 tunnels 基本就是 B洞。",
        confidence="high",
        sources=("dmarket", "daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_upper_tunnels", "de_dust2", "B", "callout", "上洞",
        english=("upper tunnels", "upper tunnel", "upper tuns", "upper"),
        russian=("верхний тоннель", "верх тоннеля"),
        zh_aliases=("B上洞", "上层洞"),
        note="靠近 B 点的上层 tunnels。upper 单独出现时可能需上下文确认。",
        confidence="medium",
        sources=("daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_lower_tunnels", "de_dust2", "B/mid", "callout", "下洞",
        english=("lower tunnels", "lower tunnel", "lower tuns", "lower"),
        russian=("нижний тоннель", "низ тоннеля"),
        zh_aliases=("B下洞", "下层洞"),
        note="连接 B tunnels 与中路的小通道。",
        confidence="high",
        sources=("daddyskins", "blog_cs2ad", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_dark", "de_dust2", "B", "callout", "暗位",
        english=("dark", "dark spot"),
        russian=("дарк", "темка"),
        zh_aliases=("黑屋", "暗处", "B暗位"),
        note="B 洞/近 B 点暗角。不同社区可能叫黑屋/暗位。",
        confidence="medium",
        sources=("totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_b_site", "de_dust2", "B", "callout", "B包点",
        english=("b site", "bombsite b", "b bombsite"),
        russian=("б плент", "б сайт"),
        zh_aliases=("B点", "B区"),
        note="Dust2 B 包点。",
        confidence="high",
        sources=("dmarket", "daddyskins", "totalcsgo"),
    ),
    GlossaryTerm(
        "dust2_b_doors", "de_dust2", "B", "callout", "B门",
        english=("b doors", "b door", "doors b"),
        russian=("б двери", "дверь б"),
        zh_aliases=("B双门", "B区门"),
        note="B 点通向 CT 的双门。",
        confidence="high",
        sources=("daddyskins", "profilerr", "totalcsgo"),
    ),
    GlossaryTerm(
        "dust2_b_window", "de_dust2", "B", "callout", "B窗",
        english=("b window", "window"),
        russian=("окно б", "окно"),
        zh_aliases=("窗户", "B窗口"),
        note="B 点墙上窗口。window 在其他地图也常见，de_dust2 上结合上下文判断。",
        confidence="medium",
        sources=("daddyskins", "profilerr", "totalcsgo"),
    ),
    GlossaryTerm(
        "dust2_b_car", "de_dust2", "B", "callout", "B车",
        english=("b car", "car b"),
        russian=("машина б",),
        zh_aliases=("B车位", "车旁"),
        note="B 点车位；与 A车区分。",
        confidence="medium",
        sources=("daddyskins", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_b_platform", "de_dust2", "B", "callout", "B平台",
        english=("b plat", "b platform", "platform", "plat"),
        russian=("платформа", "плат"),
        zh_aliases=("平台", "后平台", "B后平台"),
        note="B 点平台/高台区域，部分 callout 会细分 back plat。",
        confidence="medium",
        sources=("daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_back_plat", "de_dust2", "B", "callout", "后平台",
        english=("back plat", "back platform", "back site", "big box"),
        russian=("бэкплат", "бэк сайт"),
        zh_aliases=("B后点", "B后箱", "大箱后"),
        note="B 点后平台/大箱后位置。",
        confidence="medium",
        sources=("daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_fence", "de_dust2", "B", "callout", "铁网",
        english=("fence",),
        russian=("забор",),
        zh_aliases=("网", "B铁网"),
        note="B 点/后点附近 fence。属于中等置信度 callout，warning 仅供复核。",
        confidence="medium",
        sources=("csbumps", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_t_spawn", "de_dust2", "spawn", "callout", "匪家",
        english=("t spawn", "terrorist spawn"),
        russian=("т спавн", "террор спавн"),
        zh_aliases=("T家", "土匪家", "匪口"),
        note="T 方出生点。",
        confidence="high",
        sources=("dmarket", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_ct_spawn", "de_dust2", "spawn", "callout", "警家",
        english=("ct spawn", "counter-terrorist spawn"),
        russian=("кт спавн", "сити спавн"),
        zh_aliases=("CT家", "警察家", "警口"),
        note="CT 方出生点，也是 A/B 回防枢纽。",
        confidence="high",
        sources=("dmarket", "daddyskins", "totalcsgo", "cs2util"),
    ),
    GlossaryTerm(
        "dust2_default", "de_dust2", "plant", "plant", "默认包位",
        english=("default plant", "default"),
        russian=("дефолт",),
        zh_aliases=("默认包", "默认下包位", "包位"),
        note="下包默认位。需要结合 A/B 点上下文，不应机械替换所有 default。",
        confidence="medium",
        sources=("cs2_common", "cs2util"),
    ),
)


# Conservative Anubis pilot glossary.
# v0.8.3 adds Anubis because the immediate showcase target is a donk/LIM POV
# on Anubis.  Chinese Anubis callouts are less standardized than Dust2/Mirage,
# so many preferred translations intentionally keep the English callout plus a
# short Chinese explanation.  This avoids overconfident machine-translation style
# rewrites while still giving the LLM stable CS2 map semantics.
ANUBIS_GLOSSARY: tuple[GlossaryTerm, ...] = (
    GlossaryTerm(
        "anubis_t_spawn", "de_anubis", "spawn", "callout", "匪家",
        english=("t spawn", "terrorist spawn"),
        russian=("т спавн", "террор спавн"),
        zh_aliases=("T家", "土匪家", "匪口"),
        note="T 方出生点。Anubis T 方可快速转向 Alley/Top Mid/Canal。",
        confidence="high",
        sources=("totalcsgo", "skinport", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_ct_spawn", "de_anubis", "spawn", "callout", "警家",
        english=("ct spawn", "counter-terrorist spawn"),
        russian=("кт спавн", "сити спавн"),
        zh_aliases=("CT家", "警察家", "警口"),
        note="CT 方出生点，连接 Cave/黑屋、Street/A/B 回防路线。",
        confidence="high",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_alley", "de_anubis", "T/mid", "callout", "Alley/小巷",
        english=("alley", "t alley"),
        russian=("аллея",),
        zh_aliases=("小巷", "匪家小巷", "Alley"),
        note="T spawn 附近通往中路/B 区方向的小巷。中文社区不完全统一，字幕可保留 Alley。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_ruins", "de_anubis", "B/T", "callout", "Ruins/废墟",
        english=("ruins", "b ruins"),
        russian=("руины",),
        zh_aliases=("废墟", "Ruins", "B废墟"),
        note="B Long 与 T spawn 之间的区域，也可作为进入 B 区或 Top Mid 的路径。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_top_mid", "de_anubis", "mid", "callout", "中路上/Top Mid",
        english=("top mid", "top middle", "upper mid"),
        russian=("топ мид", "верх мида"),
        zh_aliases=("中远", "中路上", "Top Mid", "中路上方"),
        note="T 侧靠近 Bridge 的中路上段。",
        confidence="high",
        sources=("totalcsgo", "cs2pulse", "cs2ad"),
    ),
    GlossaryTerm(
        "anubis_middle", "de_anubis", "mid", "callout", "中路",
        english=("middle", "mid"),
        russian=("мид", "мидл"),
        zh_aliases=("中", "中门附近", "压中", "中路控制"),
        note="Anubis 中路控制区域。短字幕中『压中』也属于自然表达。",
        confidence="high",
        sources=("totalcsgo", "cs2pulse", "skinport", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_bridge", "de_anubis", "mid/canal", "callout", "Bridge/桥",
        english=("bridge",),
        russian=("бридж", "мост"),
        zh_aliases=("桥", "桥上", "Bridge"),
        note="位于 Canal/Water 上方、连接 Top Mid 与 Middle 的桥。",
        confidence="high",
        sources=("skinport", "cs2pulse", "dmarket", "profilerr"),
    ),
    GlossaryTerm(
        "anubis_canal", "de_anubis", "canal", "callout", "Canal/水道",
        english=("canal", "water", "waters"),
        russian=("канал", "вода"),
        zh_aliases=("水道", "水路", "水下", "水里", "Canal", "Water"),
        note="Anubis 标志性水路区域，可连接中路、A/B 轮转和 Connector。Water 在普通英语里也可能是噪声词，warning 仅供复核。",
        confidence="high",
        sources=("skinport", "profilerr", "cs2pulse", "dmarket", "cs2ad"),
    ),
    GlossaryTerm(
        "anubis_stairs", "de_anubis", "canal/T", "callout", "匪口",
        english=("stairs", "water stairs", "canal stairs"),
        russian=("лестница", "ступеньки"),
        zh_aliases=("匪口", "T口", "Stairs"),
        avoid=("楼梯", "水道楼梯", "台阶", "警口"),
        note="Anubis 连接 T 侧路径与 Canal/Water 的 Stairs。中文 POV 字幕按用户反馈优先写『匪口』，不使用『警口』或直译『楼梯』。",
        confidence="medium",
        sources=("profilerr", "totalcsgo", "cs2pulse", "user_feedback_cn"),
    ),
    GlossaryTerm(
        "anubis_arches", "de_anubis", "canal", "callout", "Arches/拱门",
        english=("arches", "arch"),
        russian=("арка", "арки"),
        zh_aliases=("拱门", "双拱", "Arches"),
        note="Canal/Bridge 附近拱门区域，可用于争夺 B Connector/Bridge。",
        confidence="medium",
        sources=("profilerr", "cs2pulse"),
    ),
    GlossaryTerm(
        "anubis_a_main", "de_anubis", "A", "callout", "A Main/A大",
        english=("a main", "main a", "a long"),
        russian=("а мейн", "а лонг"),
        zh_aliases=("A大", "A门", "A Main", "A主路", "A入口"),
        note="T 方进攻 A 区的主要入口。Anubis 中文叫法不如 Mirage/Dust2 固定，字幕可保留 A Main。",
        confidence="medium",
        sources=("dmarket", "cs2ad", "tradeit"),
    ),
    GlossaryTerm(
        "anubis_a_site", "de_anubis", "A", "callout", "A包点",
        english=("a site", "a bombsite", "bombsite a"),
        russian=("а плент", "а сайт"),
        zh_aliases=("A点", "A区", "A平台"),
        note="Anubis A 包点。",
        confidence="high",
        sources=("dmarket", "daddyskins", "cs2ad", "totalcsgo"),
    ),
    GlossaryTerm(
        "anubis_a_connector", "de_anubis", "A/mid", "callout", "A Connector/A连接",
        english=("a connector", "a con", "connector a"),
        russian=("а коннектор", "а кон"),
        zh_aliases=("A连接", "A连接口", "A Connector", "A con"),
        note="Middle 通往 A Site 的窄路，常由 CT 或回防方使用。",
        confidence="high",
        sources=("totalcsgo", "cs2pulse", "skinport"),
    ),
    GlossaryTerm(
        "anubis_plateau", "de_anubis", "A", "callout", "Plateau/平台",
        english=("plateau", "a plateau"),
        russian=("плато",),
        zh_aliases=("平台", "A平台", "Plateau"),
        note="从 A Connector 出来通往 A Site/A Heaven 的开阔平台。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse"),
    ),
    GlossaryTerm(
        "anubis_heaven", "de_anubis", "A/B", "callout", "Heaven/高台",
        english=("heaven", "a heaven"),
        russian=("хевен",),
        zh_aliases=("高台", "A高台", "Heaven", "天堂位"),
        note="Anubis 的高点/架枪位。不同资料可能在 A/B 或 Ruins 高位使用 Heaven，需要结合上下文。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_temple", "de_anubis", "A", "callout", "Temple/神庙",
        english=("temple", "a temple"),
        russian=("темпл", "храм"),
        zh_aliases=("神庙", "庙", "Temple", "A庙"),
        avoid=("寺庙",),
        note="A 区附近 Temple/神庙位置。中文字幕可保留 Temple 或写神庙；平台机翻常见寺庙可作为复核线索。",
        confidence="medium",
        sources=("dmarket", "cs2ad", "daddyskins"),
    ),
    GlossaryTerm(
        "anubis_boat", "de_anubis", "A/canal", "callout", "Boat/船位",
        english=("boat",),
        russian=("лодка",),
        zh_aliases=("船", "船位", "Boat"),
        note="靠近 Canal/A 路线的 Boat 区域。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_drop", "de_anubis", "A/canal", "callout", "Drop/下跳",
        english=("drop", "a drop"),
        russian=("дроп",),
        zh_aliases=("下跳", "跳下去", "Drop"),
        note="Boat 附近 T 方可从上层 drop 到 Canal 的位置。注意 drop 也可能是给枪，需要结合上下文。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse"),
    ),
    GlossaryTerm(
        "anubis_b_long", "de_anubis", "B", "callout", "B Long/B大",
        english=("b long", "long b", "b main", "b-main"),
        russian=("б лонг", "б мейн"),
        zh_aliases=("B大", "B长路", "B Main", "B主路", "B入口"),
        note="从 Ruins/Gate 通往 B 包点的长路，是进 B 的主要入口之一。",
        confidence="high",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_gate", "de_anubis", "B", "callout", "Gate/B门",
        english=("gate", "b gate"),
        russian=("гейт", "ворота"),
        zh_aliases=("B门", "门口", "Gate", "B门口"),
        note="B Long 进入 B Bombsite 的大拱门/入口。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_ivy", "de_anubis", "B", "callout", "Ivy/藤蔓位",
        english=("ivy",),
        russian=("айви",),
        zh_aliases=("藤蔓", "藤蔓位", "Ivy"),
        note="Gate 外侧靠近 B Long/Ruins 的小区域，名称来自植被。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse"),
    ),
    GlossaryTerm(
        "anubis_b_site", "de_anubis", "B", "callout", "B包点",
        english=("b site", "b bombsite", "bombsite b"),
        russian=("б плент", "б сайт"),
        zh_aliases=("B点", "B区"),
        note="Anubis B 包点。",
        confidence="high",
        sources=("dmarket", "daddyskins", "cs2ad", "totalcsgo"),
    ),
    GlossaryTerm(
        "anubis_pillar", "de_anubis", "B", "callout", "Pillar/柱子",
        english=("pillar", "b pillar"),
        russian=("пиллар", "колонна"),
        zh_aliases=("柱子", "B柱", "Pillar"),
        note="B 包点的柱子，近点柱和后点柱可能都被简称 pillar。",
        confidence="high",
        sources=("totalcsgo", "cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_default", "de_anubis", "plant", "plant", "默认包位",
        english=("default plant", "default"),
        russian=("дефолт",),
        zh_aliases=("默认包", "默认下包位", "包位"),
        note="默认下包位；需要结合 A/B 点上下文。",
        confidence="medium",
        sources=("totalcsgo", "cs2_common"),
    ),
    GlossaryTerm(
        "anubis_ebox", "de_anubis", "B/mid", "callout", "E Box/E箱",
        english=("e box", "ebox", "e-box"),
        russian=("ибокс", "е бокс"),
        zh_aliases=("E箱", "E Box", "E盒"),
        note="B 点附近连接 Middle 与 B Bombsite 的室内区域。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse"),
    ),
    GlossaryTerm(
        "anubis_sniper", "de_anubis", "B", "callout", "Sniper/狙位",
        english=("sniper", "sniper spot"),
        russian=("снайпер",),
        zh_aliases=("狙位", "狙击位", "Sniper"),
        note="B 区高点/架 B Long 过点的位置。不要把 AWP 玩家误译成这个点位，warning 仅供复核。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse"),
    ),
    GlossaryTerm(
        "anubis_cave", "de_anubis", "B/CT", "callout", "Cave/黑屋",
        english=("cave",),
        russian=("пещера",),
        zh_aliases=("黑屋", "B黑屋", "洞穴", "Cave", "B洞穴"),
        note="CT spawn 侧通往 B 区的 Cave。中文 CS2 POV 字幕优先写『黑屋』；『洞穴』可接受但不作为首选。",
        confidence="medium",
        sources=("totalcsgo", "cs2pulse", "dmarket", "user_feedback_cn"),
    ),
    GlossaryTerm(
        "anubis_street", "de_anubis", "CT/B", "callout", "Street/街道",
        english=("street", "b street"),
        russian=("стрит", "улица"),
        zh_aliases=("街道", "Street", "B街"),
        note="CT 侧靠近 B/Cave 的回防路线。",
        confidence="medium",
        sources=("cs2pulse", "dmarket"),
    ),
    GlossaryTerm(
        "anubis_b_connector", "de_anubis", "B/mid", "callout", "B Connector/B连接",
        english=("b connector", "connector", "b con"),
        russian=("б коннектор", "б кон"),
        zh_aliases=("B连接", "连接", "B Connector", "B con"),
        note="中路/Canal 与 B 区之间的连接区域。Anubis connector 有 A/B 语境，字幕最好保留 A/B 前缀。",
        confidence="medium",
        sources=("cs2pulse", "profilerr", "reddit_community"),
    ),
)


# Conservative global CS2 terminology pilot.
# This is intentionally small and high-value.  It is not a giant dictionary;
# it gives the LLM stable constraints for common CS2 verbs, economy terms and
# utility/weapon words that appear on every map.
GLOBAL_GLOSSARY: tuple[GlossaryTerm, ...] = (
    GlossaryTerm("global_awp", "global", "global", "weapon", "AWP/大狙", english=("awp", "op", "sniper"), russian=("авп", "авап", "снайпа"), zh_aliases=("AWP", "大狙", "狙"), avoid=("自动武器",), note="CS2 里 AWP 通常保留 AWP 或说大狙，不要翻成普通狙击手。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_flash", "global", "global", "utility", "闪", english=("flash", "flashbang", "blind"), russian=("флеш", "флешка", "слепа"), zh_aliases=("闪光", "闪光弹"), avoid=("闪电",), note="道具 flash/flashbang，字幕里常简写为闪。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_smoke", "global", "global", "utility", "烟", english=("smoke", "smoke grenade"), russian=("смок", "дым"), zh_aliases=("烟雾", "烟雾弹"), avoid=("抽烟",), note="道具 smoke，字幕里常简写为烟。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_molly", "global", "global", "utility", "火", english=("molly", "molotov", "incendiary", "fire"), russian=("молик", "молотов", "инсенд"), zh_aliases=("燃烧弹", "火瓶"), avoid=("莫莉",), note="燃烧弹/火，CS2 字幕优先写火。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_nade", "global", "global", "utility", "雷", english=("nade", "he grenade", "he nade", "grenade"), russian=("хаешка", "граната", "хе"), zh_aliases=("手雷", "高爆"), avoid=("手榴弹"), note="HE grenade，字幕里常写雷。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_kit", "global", "global", "equipment", "钳子/拆弹器", english=("kit", "defuse kit"), russian=("кит", "дифуза"), zh_aliases=("钳子", "拆弹器"), avoid=("工具包",), note="CT 拆弹器，语境明确时写钳子。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_push", "global", "global", "action", "前压/推进", english=("push", "pushing", "push up"), russian=("пуш", "пушат", "пропушить"), zh_aliases=("前压", "压出来", "推进", "冲", "压"), avoid=("推",), note="根据语境可译为前压、推进或冲；避免机械翻成推。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_peek", "global", "global", "action", "peek/拉出去看", english=("peek", "peeking", "repeek"), russian=("пик", "пикает", "репик"), zh_aliases=("拉出去", "peek", "再拉"), avoid=("偷看",), note="peek 在字幕中可保留英文或写拉出去看。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_hold", "global", "global", "action", "架住/守住", english=("hold", "holding"), russian=("держи", "держит"), zh_aliases=("架", "架住", "守住", "别动"), avoid=("拿着",), note="hold 在 CS2 语音中通常是架枪或守点。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_rotate", "global", "global", "action", "转点/回防", english=("rotate", "rotating", "rotation"), russian=("ротация", "ротейт", "перетяжка"), zh_aliases=("转", "转点", "回防", "补防"), avoid=("旋转",), note="根据阵营和场景译为转点/回防/补防。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_trade", "global", "global", "action", "补枪", english=("trade", "trade me", "trade him", "trade kill"), russian=("трейд", "размен", "разменяй"), zh_aliases=("补", "补掉", "换掉"), avoid=("交易",), note="队友被击杀后补掉对手，不要翻成交易。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_save", "global", "global", "action", "保枪", english=("save", "saving", "save gun"), russian=("сейв", "сохраняй"), zh_aliases=("保", "保枪", "保甲"), avoid=("保存",), note="回合无望时保枪/保装备。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_drop", "global", "global", "action", "给枪/掉枪", english=("drop", "drop me", "can you drop"), russian=("дроп", "дропни", "скинь"), zh_aliases=("发枪", "给枪", "掉"), avoid=("下降",), note="买枪阶段常为给枪；死亡语境可能是掉枪。", confidence="medium", sources=("cs2_common",)),
    GlossaryTerm("global_swing", "global", "global", "action", "拉出去/一起拉", english=("swing", "wide swing", "swing out"), russian=("свинг", "широко"), zh_aliases=("大拉", "一起拉"), avoid=("摇摆",), note="枪位动作，通常是拉出去对枪。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_clear", "global", "global", "action", "清点", english=("clear", "clearing", "check"), russian=("чек", "чекай", "прочистить"), zh_aliases=("搜", "检查", "清"), avoid=("清楚",), note="清理点位/检查角落。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_fake", "global", "global", "tactic", "假打/骗转", english=("fake", "faking"), russian=("фейк", "обманка"), zh_aliases=("假打", "假动作", "骗转"), avoid=("假的",), note="战术假打或骗对手转点。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_retake", "global", "global", "tactic", "回防/重夺", english=("retake", "retaking"), russian=("ретейк", "ретейкать"), zh_aliases=("回防", "重夺"), avoid=("重拿",), note="CT 包点失守后的回防。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_default", "global", "global", "tactic", "默认控图", english=("default", "play default"), russian=("дефолт",), zh_aliases=("默认", "默认控图"), avoid=("默认值",), note="战术 default，通常指默认控图。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_split", "global", "global", "tactic", "夹击/分路进攻", english=("split", "split them"), russian=("сплит",), zh_aliases=("夹", "夹击", "分路"), avoid=("分裂",), note="多路夹击进点。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_rush", "global", "global", "tactic", "rush/直接冲", english=("rush", "rushing"), russian=("раш", "рашить"), zh_aliases=("冲", "rush"), avoid=("匆忙",), note="快速集体进攻，字幕可保留 rush。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_contact", "global", "global", "tactic", "静音接触", english=("contact", "contact play"), russian=("контакт",), zh_aliases=("静音摸", "接触"), avoid=("联系",), note="不交道具、静音摸近点后爆发。", confidence="medium", sources=("cs2_common",)),
    GlossaryTerm("global_lurk", "global", "global", "role", "单摸/断后", english=("lurk", "lurker", "lurking"), russian=("люрк", "люркер"), zh_aliases=("单摸", "摸后", "断后"), avoid=("潜伏者",), note="单人控图/绕后角色。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_entry", "global", "global", "role", "突破", english=("entry", "entry frag", "entrying"), russian=("энтри",), zh_aliases=("突破手", "第一个进"), avoid=("入口",), note="进点第一个接敌/突破。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_crossfire", "global", "global", "tactic", "交叉火力", english=("crossfire",), russian=("кроссфаер", "перекрестный огонь"), zh_aliases=("交叉枪线",), avoid=("交叉射击"), note="两人以上形成交叉枪线。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_boost", "global", "global", "tactic", "架人/双架", english=("boost", "boost me"), russian=("буст", "подсадка"), zh_aliases=("双架", "架上去", "架我", "架他", "架人"), avoid=("提升",), note="队友蹲下把人架到高点。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_stack", "global", "global", "tactic", "重防/赌点", english=("stack", "stacked"), russian=("стак",), zh_aliases=("堆", "重防", "赌点"), avoid=("堆栈",), note="多人集中防某个点。", confidence="medium", sources=("cs2_common",)),
    GlossaryTerm("global_eco", "global", "global", "economy", "eco/经济局", english=("eco", "eco round"), russian=("эко",), zh_aliases=("经济局", "纯 eco"), avoid=("生态",), note="经济不足不强起的回合。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_force", "global", "global", "economy", "强起", english=("force", "force buy", "forced"), russian=("форс", "форсбай"), zh_aliases=("强起局", "硬起"), avoid=("强迫",), note="钱不够但仍强行买枪。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_full_buy", "global", "global", "economy", "全枪全弹", english=("full buy", "full buying"), russian=("фулл бай",), zh_aliases=("全起", "长枪局"), avoid=("全买",), note="完整购买长枪和道具。", confidence="high", sources=("cs2_common",)),
    GlossaryTerm("global_half_buy", "global", "global", "economy", "半起", english=("half buy",), russian=("полубай",), zh_aliases=("半甲半道具",), avoid=("买一半",), note="不完全投入经济的购买。", confidence="medium", sources=("cs2_common",)),
    GlossaryTerm("global_bonus", "global", "global", "economy", "bonus/奖励局", english=("bonus", "bonus round"), russian=("бонус",), zh_aliases=("奖励局", "保枪奖励局"), avoid=("奖金",), note="赢手枪后带旧枪打的经济优势回合。", confidence="medium", sources=("cs2_common",)),
)

MAP_GLOSSARIES: dict[str, tuple[GlossaryTerm, ...]] = {"de_mirage": MIRAGE_GLOSSARY, "de_dust2": DUST2_GLOSSARY, "de_anubis": ANUBIS_GLOSSARY}
SUPPORTED_MAPS = tuple(sorted(MAP_GLOSSARIES))
PILOT_MAP = "de_mirage"
PILOT_MAPS = SUPPORTED_MAPS


def get_global_glossary() -> list[GlossaryTerm]:
    return list(GLOBAL_GLOSSARY)


def get_map_glossary(map_name: str | None) -> list[GlossaryTerm]:
    if not map_name:
        return []
    return list(MAP_GLOSSARIES.get(map_name.lower(), ()))


def get_combined_glossary(map_name: str | None) -> list[GlossaryTerm]:
    return [*get_global_glossary(), *get_map_glossary(map_name)]


def is_glossary_supported(map_name: str | None) -> bool:
    # Global glossary is always available.  Map support indicates whether a map
    # glossary exists in addition to the global pilot.
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


def format_glossary_for_prompt(map_name: str | None, texts: Iterable[str] | None = None, limit: int = 56) -> list[dict[str, Any]]:
    terms = get_combined_glossary(map_name)
    if not terms:
        return []
    if texts is not None:
        counts = detect_terms_in_texts(texts, terms)
        # Matched terms first, then high-confidence global terms, then map terms.
        terms = sorted(terms, key=lambda t: (-counts.get(t.term_id, 0), _confidence_rank(t.confidence), 0 if t.map_name == "global" else 1, t.zone, t.term_id))
    else:
        terms = sorted(terms, key=lambda t: (_confidence_rank(t.confidence), 0 if t.map_name == "global" else 1, t.zone, t.term_id))
    return [t.to_prompt_item() for t in terms[:limit]]


def build_glossary_used_report(map_name: str | None, texts: Iterable[str]) -> dict[str, Any]:
    global_terms = get_global_glossary()
    map_terms = get_map_glossary(map_name)
    all_terms = [*global_terms, *map_terms]
    counts = detect_terms_in_texts(texts, all_terms)

    def used_items(terms: list[GlossaryTerm]) -> list[dict[str, Any]]:
        return [
            {
                **term.to_prompt_item(),
                "matched_in_transcript": counts.get(term.term_id, 0),
            }
            for term in terms
        ]

    return {
        "schema_version": 2,
        "map_name": map_name,
        "global_supported": True,
        "map_supported": is_glossary_supported(map_name),
        "pilot_map": PILOT_MAP,
        "pilot_maps": list(PILOT_MAPS),
        "scope_note": "v0.8.5 启用 global CS2 通用术语 pilot，并提供 de_mirage / de_dust2 / de_anubis 三张地图试点词典。词典用于 prompt 约束和 warning 报告，不做硬替换。",
        "global_term_count": len(global_terms),
        "map_term_count": len(map_terms),
        "term_count": len(all_terms),
        "matched_global_term_count": sum(1 for t in global_terms if counts.get(t.term_id, 0) > 0),
        "matched_map_term_count": sum(1 for t in map_terms if counts.get(t.term_id, 0) > 0),
        "matched_term_count": sum(1 for v in counts.values() if v > 0),
        "global_terms": used_items(global_terms),
        "map_terms": used_items(map_terms),
        "terms": used_items(all_terms),
        "source_tags": sorted({tag for term in all_terms for tag in term.sources}),
    }


def validate_translation_terms(original_text: str, translated_text: str, map_name: str | None) -> list[dict[str, Any]]:
    terms = detect_terms(original_text, get_combined_glossary(map_name))
    warnings: list[dict[str, Any]] = []
    for term in terms:
        acceptable = {term.preferred_zh, *term.zh_aliases}
        if translated_text and translated_text.startswith("["):
            continue
        has_acceptable = any(alias and alias in translated_text for alias in acceptable)
        has_avoid = any(bad and bad in translated_text for bad in term.avoid)
        if not has_acceptable or has_avoid:
            warnings.append({
                "term_id": term.term_id,
                "scope": "global" if term.map_name == "global" else "map",
                "source": term.source,
                "preferred_zh": term.preferred_zh,
                "acceptable_zh": sorted(acceptable),
                "avoid": list(term.avoid),
                "confidence": term.confidence,
                "original_text": original_text,
                "translated_text": translated_text,
                "message": "原文疑似出现术语，但译文未包含推荐中文叫法或出现禁忌误译；可能是 ASR 误识别、上下文不适用，或需要人工复核。",
            })
    return warnings


def build_glossary_warning_report(map_name: str | None, segment_warnings: list[dict[str, Any]]) -> dict[str, Any]:
    global_count = sum(1 for item in segment_warnings if item.get("scope") == "global")
    map_count = sum(1 for item in segment_warnings if item.get("scope") == "map")
    return {
        "schema_version": 2,
        "map_name": map_name,
        "global_supported": True,
        "map_supported": is_glossary_supported(map_name),
        "warning_count": len(segment_warnings),
        "global_warning_count": global_count,
        "map_warning_count": map_count,
        "warnings": segment_warnings,
        "note": "这些 warning 是保守校验，不代表翻译一定错误；用于发现通用术语/地图报点不稳定和后续人工调词典。",
    }


def glossary_terms_as_dicts(map_name: str | None, scope: str = "all") -> list[dict[str, Any]]:
    scope = (scope or "all").lower()
    if scope == "global":
        terms = get_global_glossary()
    elif scope == "map":
        terms = get_map_glossary(map_name)
    else:
        terms = get_combined_glossary(map_name)
    return [term.to_prompt_item() | {"sources": list(term.sources)} for term in terms]


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
