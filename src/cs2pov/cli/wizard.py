from __future__ import annotations

import argparse
import getpass
from pathlib import Path
from typing import Iterable

from cs2pov.cli.encoding import configure_utf8_stdio
from cs2pov.domain.models import PipelineConfig, StageName, Player, player_from_dict
from cs2pov.pipeline.engine import PipelineEngine
from cs2pov.cli.model_manager import TRANSCRIPTION_PROFILES, profile_to_config
from cs2pov.storage.config_store import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    load_config,
    save_config,
    llm_model_warning,
)
from cs2pov.storage.jsonl import read_json

TOTAL_STEPS = 8


class WizardAbort(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="CS2 POV Translator 强引导向导")
    parser.add_argument("--demo", help="可选：预填 demo 路径")
    parser.add_argument("--output", default="output", help="输出根目录，默认 output")
    parser.add_argument("--quick", action="store_true", help="快速测试模式：默认只跑前 3 个含语音回合")
    args = parser.parse_args(argv)

    print_banner()
    try:
        return run_wizard(args)
    except KeyboardInterrupt:
        print("\n\n已取消。你可以稍后重新运行 cs2pov-wizard。")
        return 130
    except WizardAbort as exc:
        print(f"\n已停止：{exc}")
        return 1
    except Exception as exc:
        print("\n处理失败。")
        print(f"错误类型：{type(exc).__name__}")
        print(f"错误信息：{exc}")
        print("\n请优先打包最近的 Job 反馈包：")
        print("  cs2pov feedback output")
        print("然后把生成的 zip 发给开发者。")
        raise


def run_wizard(args: argparse.Namespace) -> int:
    defaults = load_config()

    step(1, "选择 demo 文件", "支持 .dem 和 .dem.zst。你可以把文件拖进终端后按回车。")
    demo_path = Path(args.demo).expanduser() if args.demo else ask_path("请输入 demo 文件路径")
    output_root = ask_path_or_create("输出根目录", default=args.output)

    config = config_from_defaults(defaults, output_root)
    print("\n接下来会先做准备工作：解压、识别地图和玩家、提取语音。")
    print("这个阶段可能需要一些时间，但不会调用 Whisper 或 LLM。")
    if not ask_yes_no("开始准备 demo 吗？", default=True):
        raise WizardAbort("用户取消准备 demo")

    engine = PipelineEngine(config)
    engine.run(demo_path, to_stage=StageName.BUILD_VOICE_ACTIVITY)

    step(2, "确认地图", "地图会影响报点翻译和后续配置。自动识别失败时可以手动输入。")
    demo_info = read_json(engine.store.demo_info_path)
    detected_map = demo_info.get("map_name") or "unknown"
    print(f"检测到地图：{detected_map}")
    if detected_map != "unknown" and ask_yes_no("地图识别是否正确？", default=True):
        config.map_name = detected_map
    else:
        config.map_name = ask_text("请输入地图名，例如 de_mirage / de_dust2 / de_anubis", default=None if detected_map == "unknown" else detected_map)

    step(3, "选择 POV 主角", "默认会导出该玩家所在队伍的全部语音，最适合 POV 视频剪辑。")
    players = load_players(engine.store.voice_manifest_path)
    if not players:
        raise WizardAbort("没有检测到任何玩家语音，无法继续")
    print_player_table(players)
    default_idx = recommended_player_index(players)
    choice = ask_int("请选择 POV 主角编号", min_value=1, max_value=len(players), default=default_idx)
    pov = players[choice - 1]
    config.selected_pov_steamid = pov.steamid
    config.selected_team_number = pov.team_number
    print(f"已选择：{pov.name} / Team {pov.team_number}")
    if ask_yes_no(f"是否导出 {pov.name} 所在队伍 Team {pov.team_number} 的全部语音？", default=True):
        config.export_scope = "pov_team"
    else:
        config.export_scope = "pov_player"
    config.player_aliases = choose_player_aliases(players, pov, config.export_scope)

    step(4, "选择转录配置", "v0.8.6 新增质量档位。办公本剪视频推荐 quality/small；首次测试可用 fast/tiny。")
    profile_values = choose_transcription_profile(default=config.transcription_profile)
    config.transcription_profile = profile_values["transcription_profile"]
    config.whisper_model = profile_values["whisper_model"]
    config.whisper_device = profile_values["whisper_device"]
    config.whisper_compute_type = profile_values["whisper_compute_type"]
    config.asr_language = choose_asr_language(default="auto")
    config.transcription_mode = choose_transcription_mode(default=config.transcription_mode)
    print(f"Whisper：profile={config.transcription_profile} / model={config.whisper_model} / device={config.whisper_device} / compute_type={config.whisper_compute_type}")
    print(f"Whisper VAD：{'ON' if config.whisper_vad_filter else 'OFF'}；幻觉过滤：{'ON' if config.filter_hallucinations else 'OFF'}；长 cue 阈值：{config.max_subtitle_segment_seconds}s。")

    step(5, "选择运行范围", "首次测试建议只跑前 3 个含语音回合；确认效果后再完整处理。")
    config.max_rounds = choose_run_range(quick=args.quick)

    step(6, "配置翻译", "可以真实调用 LLM，也可以先 dry-run 生成演示翻译，或跳过翻译只导出原文字幕。")
    configure_translation(config, defaults)

    step(7, "确认任务", "请检查以下配置。开始后会进入转录、按回合翻译和导出阶段。")
    print_run_summary(config, demo_path, engine.store.job_dir)
    if not ask_yes_no("确认开始处理吗？", default=True):
        print(f"已暂停。Job 目录保留在：{engine.store.job_dir}")
        print("你之后可以用专家命令继续，例如从 parse_rounds 开始。")
        return 0

    engine.config = config
    engine.manifest.config = config
    engine.run(demo_path, from_stage=StageName.PARSE_ROUNDS)

    step(8, "完成", "字幕已经导出。最常用的成片字幕在 final/ 目录。")
    print_success_summary(engine.store.job_dir)
    return 0


def config_from_defaults(defaults: dict, output_root: Path) -> PipelineConfig:
    return PipelineConfig(
        output_root=str(output_root),
        transcription_profile=defaults.get("transcription_profile") or "balanced",
        whisper_model=defaults.get("whisper_model") or "base",
        whisper_device=defaults.get("whisper_device") or "cpu",
        whisper_compute_type=defaults.get("whisper_compute_type") or "int8",
        whisper_cache_dir=defaults.get("whisper_cache_dir"),
        whisper_vad_filter=bool(defaults.get("whisper_vad_filter", True)),
        transcription_mode=defaults.get("transcription_mode") or "round",
        filter_hallucinations=bool(defaults.get("filter_hallucinations", True)),
        max_subtitle_segment_seconds=float(defaults.get("max_subtitle_segment_seconds", 10.0)),
        voice_cluster_gap_seconds=float(defaults.get("voice_cluster_gap_seconds", 1.0)),
        subtitle_bilingual_format=defaults.get("subtitle_bilingual_format") or "label",
        llm_base_url=defaults.get("llm_base_url"),
        llm_api_key=defaults.get("llm_api_key"),
        llm_model=defaults.get("llm_model"),
        glossary_enabled=bool(defaults.get("glossary_enabled", True)),
    )


def print_banner() -> None:
    print("=" * 72)
    print("CS2 POV Translator v0.8.6")
    print("强引导 CLI：新增玩家识别、K-D-A 辅助确认和字幕显示名映射")
    print("=" * 72)
    print("这个向导会带你完成 8 步：")
    print("1. 选择 demo 文件")
    print("2. 确认地图")
    print("3. 选择 POV 主角")
    print("4. 选择 Whisper 转录配置")
    print("5. 选择快速测试或完整处理")
    print("6. 配置翻译")
    print("7. 确认并运行")
    print("8. 查看输出和反馈包指引")
    print("\n提示：第一次建议先跑前 3 个回合。de_mirage / de_dust2 / de_anubis 会启用地图试点词典；其他地图仅使用 global 通用术语。生成后可回到 .bat 主菜单，用 inspect/export/retranslate/resume/glossary 继续处理。")


def step(index: int, title: str, body: str) -> None:
    print("\n" + "-" * 72)
    print(f"[{index}/{TOTAL_STEPS}] {title}")
    print("-" * 72)
    print(body)


def ask_path(prompt: str) -> Path:
    while True:
        value = input(f"{prompt}\n> ").strip().strip('"')
        path = Path(value).expanduser()
        if path.exists() and path.is_file():
            return path
        print(f"找不到文件：{path}")


def ask_path_or_create(prompt: str, default: str) -> Path:
    value = input(f"{prompt} [{default}]\n> ").strip().strip('"')
    path = Path(value or default).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ask_text(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}\n> ").strip()
        if value:
            return value
        if default is not None:
            return default
        print("不能为空。")


def ask_secret(prompt: str) -> str:
    try:
        return getpass.getpass(f"{prompt}\n> ").strip()
    except Exception:
        return input(f"{prompt}\n> ").strip()


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{hint}]\n> ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "是", "好", "1", "true", "t"}


def ask_int(prompt: str, min_value: int, max_value: int, default: int) -> int:
    while True:
        value = input(f"{prompt} [{default}]\n> ").strip()
        if not value:
            return default
        try:
            n = int(value)
        except ValueError:
            print("请输入数字。")
            continue
        if min_value <= n <= max_value:
            return n
        print(f"请输入 {min_value} 到 {max_value} 之间的数字。")


def load_players(voice_manifest_path: Path) -> list[Player]:
    data = read_json(voice_manifest_path)
    players = [player_from_dict(row) for row in data.get("players", [])]
    return sorted(players, key=lambda p: ((p.team_number or 999), -p.compact_wav_seconds, p.name.lower()))


def recommended_player_index(players: list[Player]) -> int:
    if not players:
        return 1
    best = max(range(len(players)), key=lambda i: (players[i].compact_wav_seconds, players[i].voice_packets))
    return best + 1


def print_player_table(players: list[Player]) -> None:
    print("\n检测到有语音的玩家：")
    print("编号  Team  玩家名                     K-D-A      语音时长   包数")
    print("----  ----  ------------------------  ---------  --------  ------")
    for idx, p in enumerate(players, 1):
        team = str(p.team_number) if p.team_number is not None else "?"
        print(f"{idx:>2}.   {team:>4}  {p.name[:24]:<24}  {p.kda_display:<9}  {p.compact_wav_seconds:>7.1f}s  {p.voice_packets:>6}")
    print("\n建议：先用 K-D-A 和语音时长确认职业选手小号/临时昵称；做 POV 时选主角，字幕显示名可改成 donk 等熟悉 ID。")


def choose_player_aliases(players: list[Player], pov: Player, export_scope: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    print("\n字幕显示名设置：")
    print("demo 里的昵称可能是 FACEIT/Steam 临时名，例如 Ebule。你可以让最终字幕显示为 donk。")
    pov_alias = input(f"字幕里把 {pov.name} 显示为什么？直接回车保留原名\n> ").strip()
    if pov_alias and pov_alias != pov.name:
        aliases[pov.steamid] = pov_alias
    if export_scope == "pov_team" and ask_yes_no("是否继续为同队其他有语音玩家设置显示名？", default=False):
        team_players = [p for p in players if p.team_number == pov.team_number and p.steamid != pov.steamid]
        for player in team_players:
            value = input(f"{player.name} 显示为？直接回车保留原名\n> ").strip()
            if value and value != player.name:
                aliases[player.steamid] = value
    if aliases:
        print("已设置字幕显示名：")
        name_by_sid = {p.steamid: p.name for p in players}
        for sid, alias in aliases.items():
            print(f"  {name_by_sid.get(sid, sid)} -> {alias}")
    else:
        print("未设置别名；字幕将使用 demo 原始昵称。之后也可用 cs2pov players alias 修改，不需要重跑 Whisper/LLM。")
    return aliases


def choose_transcription_profile(default: str) -> dict[str, str]:
    print("\n转录质量档位：")
    order = ["fast", "balanced", "quality", "medium_cpu", "cuda_quality"]
    for idx, key in enumerate(order, 1):
        p = TRANSCRIPTION_PROFILES[key]
        print(f"{idx}. {p.label:<12} model={p.model:<7} device={p.device:<4} compute={p.compute_type:<12} {p.description}")
    print("提示：你实测办公本 CPU 跑 small 完整 demo 约 18 分钟，因此认真剪视频可优先试 3=高质量 CPU。")
    default_idx = max(1, order.index(default) + 1) if default in order else 2
    choice = ask_int("请选择转录质量档位", 1, len(order), default_idx)
    return profile_to_config(order[choice - 1])


def choose_whisper_model(default: str) -> str:
    print("\nWhisper 模型建议：")
    print("1. tiny  - 最快，适合快速测试")
    print("2. base  - 推荐默认，速度和质量平衡")
    print("3. small - 更慢，质量通常更好")
    print("4. 自定义模型名或本地模型路径")
    default_map = {"tiny": 1, "base": 2, "small": 3}
    choice = ask_int("请选择模型", 1, 4, default_map.get(default, 2))
    if choice == 1:
        return "tiny"
    if choice == 2:
        return "base"
    if choice == 3:
        return "small"
    return ask_text("请输入模型名或本地模型路径", default=default)


def choose_asr_language(default: str = "auto") -> str:
    print("\nASR 语言：默认 auto，适合英语/俄语混合。")
    print("1. auto  - 自动识别，推荐")
    print("2. en    - 强制英文")
    print("3. ru    - 强制俄语")
    print("4. zh    - 强制中文")
    print("5. 自定义语言代码")
    default_idx = {"auto": 1, "en": 2, "ru": 3, "zh": 4}.get(default, 1)
    choice = ask_int("请选择 ASR 语言", 1, 5, default_idx)
    return {1: "auto", 2: "en", 3: "ru", 4: "zh"}.get(choice) or ask_text("请输入语言代码", default=default)


def choose_transcription_mode(default: str) -> str:
    print("\n转录切片模式：")
    print("1. round    - 按回合+玩家切片，推荐默认")
    print("2. activity - 按语音活动切片，更细但更碎")
    print("3. player   - 旧版整名玩家 WAV，仅用于对照")
    default_idx = {"round": 1, "activity": 2, "player": 3}.get(default, 1)
    choice = ask_int("请选择转录切片模式", 1, 3, default_idx)
    return {1: "round", 2: "activity", 3: "player"}[choice]


def choose_run_range(quick: bool = False) -> int | None:
    print("\n运行范围：")
    print("1. 快速测试：只跑前 3 个含语音回合，推荐第一次使用")
    print("2. 完整处理：处理整场 demo，耗时更久")
    print("3. 自定义回合数")
    choice = ask_int("请选择", 1, 3, 1 if quick else 1)
    if choice == 1:
        return 3
    if choice == 2:
        return None
    value = ask_int("请输入最多处理多少个含语音回合，0 表示完整处理", 0, 200, 3)
    return None if value == 0 else value


def configure_translation(config: PipelineConfig, defaults: dict) -> None:
    has_llm = bool(config.llm_base_url and config.llm_api_key and config.llm_model)
    if has_llm:
        print(f"当前 LLM：{config.llm_base_url} / {config.llm_model}")
        warning = llm_model_warning(config.llm_model)
        if warning:
            print(f"提示：{warning}")
    else:
        print("当前没有完整 LLM 配置。")

    print("\n翻译方式：")
    print("1. 真实翻译：调用已配置的 LLM")
    print("2. dry-run：不调用 LLM，用 [演示翻译] 占位，适合测试流程")
    print("3. 跳过翻译：只生成原文/未翻译占位")
    print("4. 配置或更新 LLM")
    default_choice = 1 if has_llm else 2
    choice = ask_int("请选择", 1, 4, default_choice)
    if choice == 4:
        config.llm_base_url = ask_text("base_url", default=config.llm_base_url or DEFAULT_DEEPSEEK_BASE_URL)
        print("请输入 API key。输入内容不会显示在屏幕上。")
        entered_key = ask_secret("api_key")
        if entered_key:
            config.llm_api_key = entered_key
        config.llm_model = ask_text("model", default=config.llm_model or DEFAULT_DEEPSEEK_MODEL)
        warning = llm_model_warning(config.llm_model)
        if warning:
            print(f"提示：{warning}")
        if ask_yes_no("保存为默认配置？", default=True):
            save_config({
                "llm_base_url": config.llm_base_url,
                "llm_api_key": config.llm_api_key,
                "llm_model": config.llm_model,
                "transcription_profile": config.transcription_profile,
                "whisper_model": config.whisper_model,
                "whisper_device": config.whisper_device,
                "whisper_compute_type": config.whisper_compute_type,
                "transcription_mode": config.transcription_mode,
            })
        choice = 1 if config.llm_base_url and config.llm_api_key and config.llm_model else 2

    if choice == 1:
        if not (config.llm_base_url and config.llm_api_key and config.llm_model):
            print("LLM 配置不完整，自动切换为 dry-run。")
            config.dry_run_translation = True
        else:
            config.skip_translation = False
            config.dry_run_translation = False
    elif choice == 2:
        config.dry_run_translation = True
        config.skip_translation = False
    else:
        config.skip_translation = True
        config.dry_run_translation = False


def print_run_summary(config: PipelineConfig, demo_path: Path, job_dir: Path) -> None:
    print("\n任务摘要：")
    print(f"demo:       {demo_path}")
    print(f"job:        {job_dir}")
    print(f"map:        {config.map_name}")
    print(f"team:       {config.selected_team_number}")
    print(f"scope:      {config.export_scope}")
    print(f"whisper:    profile={config.transcription_profile} / {config.whisper_model} / {config.whisper_device} / {config.whisper_compute_type} / language={config.asr_language} / mode={config.transcription_mode}")
    print(f"max_rounds: {'完整处理' if config.max_rounds is None else config.max_rounds}")
    if config.dry_run_translation:
        translation = "dry-run 演示翻译"
    elif config.skip_translation:
        translation = "跳过翻译"
    else:
        translation = f"真实翻译：{config.llm_model}"
    print(f"translation:{translation}")
    print("\n输出说明：")
    print(f"- final/*.bilingual.srt：最常用，导入剪辑软件（双语格式：{config.subtitle_bilingual_format}）")
    print("- review/*.original.srt：只含原文，方便检查 Whisper")
    print("- review/*.zh.srt：只含中文翻译")
    print("- debug/*.voice_activity.srt：语音活动时间轴")


def print_success_summary(job_dir: Path) -> None:
    final_dir = job_dir / "final"
    review_dir = job_dir / "review"
    print(f"Job 目录：{job_dir}")
    print(f"成片字幕：{final_dir}")
    if final_dir.exists():
        for path in sorted(final_dir.glob("*.srt")):
            print(f"  - {path}")
    print(f"校对文件：{review_dir}")
    print("\n如果需要反馈给开发者，可运行：")
    print(f"  cs2pov feedback \"{job_dir}\"")
    print("\n如果磁盘空间变大，可预览清理：")
    print(f"  cs2pov clean \"{job_dir}\"")


if __name__ == "__main__":
    raise SystemExit(main())
