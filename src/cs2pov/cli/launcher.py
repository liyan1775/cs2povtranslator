from __future__ import annotations

import argparse
from pathlib import Path

from cs2pov.cli.encoding import configure_utf8_stdio
from cs2pov.cli.job_ops import export_job, inspect_job, print_job_inspection, retranslate_job, resume_job
from cs2pov.cli.commands import run_doctor, run_feedback, run_glossary, run_models, run_players
from cs2pov.cli.output_explainer import build_output_explanation, print_output_explanation
from cs2pov.cli.setup_check import build_setup_report, print_setup_report
from cs2pov.domain.models import StageName


class ReturnToMainMenu(Exception):
    """Raised when the launcher user asks to return to the main menu."""


_CANCEL_TOKENS = {"0", "q", "quit", "exit", "back", "b", "返回"}


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="CS2 POV Translator 菜单式启动器")
    parser.add_argument("--once", action="store_true", help="显示一次菜单后退出，主要用于测试")
    args = parser.parse_args(argv)
    print_banner()
    while True:
        print_menu()
        try:
            choice = input("请选择功能编号，然后按回车\n> ").strip()
        except EOFError:
            return 0 if args.once else 1
        try:
            if _is_cancel(choice):
                print("已退出。")
                return 0
            if choice == "1":
                from cs2pov.cli.wizard import main as wizard_main
                wizard_main([])
            elif choice == "2":
                print_setup_report(build_setup_report(Path.cwd()))
            elif choice == "3":
                job = ask_job_path()
                print_job_inspection(inspect_job(job))
            elif choice == "4":
                job = ask_job_path()
                print_output_explanation(build_output_explanation(job))
            elif choice == "5":
                run_export_menu()
            elif choice == "6":
                run_retranslate_menu()
            elif choice == "7":
                run_resume_menu()
            elif choice == "8":
                job = ask_job_path()
                run_feedback(job)
            elif choice == "9":
                run_doctor()
            elif choice == "10":
                run_glossary_menu()
            elif choice == "11":
                run_players_menu()
            elif choice == "12":
                run_models_menu()
            elif choice == "13":
                run_install_help_page()
            elif choice == "14":
                run_help_page()
            else:
                print("没有这个选项。请输入 0-14。")
        except ReturnToMainMenu:
            print("已返回主菜单。")
            if args.once:
                return 0
            continue
        except KeyboardInterrupt:
            print("\n已取消当前操作，返回主菜单。")
            if args.once:
                return 0
            continue
        except Exception as exc:
            print(f"\n操作失败：{type(exc).__name__}: {exc}")
            print("建议：先选择 3 查看 Job 状态，或选择 8 打包反馈包发给开发者。")
        if args.once:
            return 0
        input("\n按回车返回主菜单...")


def print_banner() -> None:
    print("=" * 72)
    print("CS2 POV Translator v0.8.6")
    print("玩家识别与别名映射：K-D-A 辅助确认，字幕显示名可改为 donk 等职业 ID")
    print("=" * 72)
    print("新用户建议：先选 2 启动前检查，再选 1 新建字幕工程。")
    print("已有 output 目录：可用 3/4/5/6/7 继续查看、解释、导出、重翻译和恢复；10 可查看词典；11 设置玩家字幕显示名；12 管理 Whisper 模型。")
    print("在子菜单中输入 0、q、back 或 返回，可随时回到主菜单。")


def print_menu() -> None:
    print("\n" + "-" * 72)
    print("主菜单")
    print("-" * 72)
    print("1. 新建字幕工程（完整向导，适合第一次处理 demo）")
    print("2. 启动前检查 setup-check（普通用户版：告诉你现在能不能开始）")
    print("3. 查看已有工程状态 inspect-job（看阶段、产物、推荐下一步）")
    print("4. 解释输出文件 explain-output（告诉你 final/review/debug/artifacts 分别干什么）")
    print("5. 重新导出字幕 export（剪辑/校对/调试预设，不重新转录/翻译）")
    print("6. 重新翻译 retranslate（不重新转录，只重跑 LLM 和导出）")
    print("7. 从某阶段恢复 resume（失败后从 translate/export_subtitles 等阶段继续）")
    print("8. 打包反馈包 feedback（排除大音频和原始 demo）")
    print("9. 技术环境诊断 doctor（更偏开发者的依赖检查）")
    print("10. 词典试点 glossary（查看 global 通用术语 + Mirage/Dust2/Anubis 报点 / 检查术语报告）")
    print("11. 玩家识别 players（查看 K-D-A/语音时长，设置 Ebule -> donk 这类别名）")
    print("12. Whisper 模型管理 models（缓存目录、已下载模型、质量档位、模型测试）")
    print("13. 查看安装/首次使用教程")
    print("14. 查看命令帮助和常见场景")
    print("0. 退出")


def _is_cancel(value: str) -> bool:
    return value.strip().lower() in _CANCEL_TOKENS


def _read_choice(prompt: str = "> ", default: str = "") -> str:
    value = input(prompt).strip()
    if _is_cancel(value):
        raise ReturnToMainMenu()
    return value or default


def ask_job_path() -> Path:
    print("请输入 Job 目录或 output 根目录。")
    print("直接回车 = output，并自动选择最新 Job。")
    print("输入 0 / q / back = 返回主菜单。")
    value = _read_choice("> ", default="output").strip().strip('"')
    return Path(value or "output")


def run_export_menu() -> None:
    print("\n重新导出不会重新转录，也不会重新调用 LLM。")
    print("v0.5.1 推荐先选预设：editing=剪辑双语优先，review=校对，debug=排查问题。")
    print("输入 0 / q / back 可返回主菜单。")
    job = ask_job_path()
    print("请选择导出方式：")
    print("1. preset editing  推荐：双语 + 紧凑双语 + 中文兜底，尽量减少重叠")
    print("2. preset review   校对：双语 + 原文 + debug，保留更多真实时间线")
    print("3. preset debug    排查：debug + voice activity + 原文")
    print("4. format all      全部格式")
    print("5. format bilingual 双语（你最常用/最推荐先看）")
    print("6. format compact  紧凑双语（剪辑优先）")
    print("7. format zh       只中文，保留玩家名（可选）")
    print("8. format zh_clean 纯中文，无玩家名前缀（极简可选）")
    print("9. format original 只原文")
    print("10. format voice   语音活动 debug")
    print("0. 返回主菜单")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    preset_map = {"1": "editing", "2": "review", "3": "debug"}
    fmt_map = {"4": "all", "5": "bilingual", "6": "compact", "7": "zh", "8": "zh_clean", "9": "original", "10": "voice"}
    preset = preset_map.get(choice)
    fmt = fmt_map.get(choice, "all")
    print("双语格式：1=[中文] 标签，2=箭头。非双语格式可直接回车。")
    print("0. 返回主菜单")
    bfmt = {"1": "label", "2": "arrow"}.get(_read_choice("请选择 [1]\n> ", default="1"), "label")
    print("重叠策略：1=使用预设，2=allow 保留真实重叠，3=shift 轻微错开，4=compact 尽量压紧。")
    print("0. 返回主菜单")
    overlap_choice = _read_choice("请选择 [1]\n> ", default="1")
    overlap = {"2": "allow", "3": "shift", "4": "compact"}.get(overlap_choice)
    outputs = export_job(job, fmt=fmt, bilingual_format=bfmt, preset=preset, overlap_policy=overlap)
    print("\n导出完成：")
    for k, v in outputs.items():
        print(f"  {k}: {v}")
    print("\n提示：不确定该用哪个文件时，回主菜单选择 4『解释输出文件』。")


def run_retranslate_menu() -> None:
    print("\n重新翻译会读取已有 round_contexts，不会重新跑 Whisper。")
    print("适合：LLM 临时失败、换模型、或想把 dry-run 结果换成真实中文翻译。")
    print("输入 0 / q / back 可返回主菜单。")
    job = ask_job_path()
    print("请选择翻译方式：")
    print("1. 真实调用当前配置的 LLM")
    print("2. dry-run 演示翻译（不花钱，不调用网络）")
    print("3. 跳过翻译（生成未翻译占位）")
    print("0. 返回主菜单")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    dry = choice == "2"
    skip = choice == "3"
    print("临时指定模型名，可直接回车使用全局配置。")
    print("输入 0 / q / back 可返回主菜单。")
    model = _read_choice("> ", default="").strip() or None
    outputs = retranslate_job(job, dry_run=dry, skip_translation=skip, model=model, export_after=True)
    print("\n重新翻译完成：")
    for k, v in outputs.items():
        print(f"  {k}: {v}")


def run_resume_menu() -> None:
    print("\n恢复执行适合处理失败后的继续运行。")
    print("常用：translate = 重新翻译；export_subtitles = 只重新导出；transcribe = 重新转录。")
    print("输入 0 / q / back 可返回主菜单。")
    job = ask_job_path()
    print("可选阶段：")
    for idx, stage in enumerate(StageName, 1):
        print(f"{idx}. {stage.value}")
    print("0. 返回主菜单")
    raw = _read_choice("从哪个阶段继续？请输入编号或阶段名 [translate]\n> ", default="translate")
    if raw.isdigit():
        stages = list(StageName)
        from_stage = stages[max(1, min(len(stages), int(raw))) - 1]
    else:
        from_stage = StageName(raw)
    demo = None
    if from_stage not in {StageName.TRANSLATE, StageName.EXPORT_SUBTITLES}:
        print("如果 Job input/ 中没有 demo，需要手动指定 .dem/.dem.zst；直接回车则自动查找。")
        print("输入 0 / q / back 可返回主菜单。")
        val = _read_choice("> ", default="").strip().strip('"')
        demo = Path(val) if val else None
    out = resume_job(job, from_stage=from_stage, demo_path=demo)
    print(f"恢复完成：{out}")



def run_glossary_menu() -> None:
    print("\n地图词典试点")
    print("=" * 72)
    print("当前做 de_mirage / de_dust2 / de_anubis 三张地图试点，不追求全量词条。")
    print("词典用途：注入 LLM 翻译 prompt，并生成 glossary_used / glossary_warnings 供人工复核。")
    print("注意：词典不会硬替换字幕文本，避免把 ASR 误识别强行改错。")
    print("输入 0 / q / back 可返回主菜单。")
    print("1. 查看 de_mirage 词典")
    print("2. 查看 de_dust2 词典")
    print("3. 查看 de_anubis 词典")
    print("4. 检查已有 Job 的词典使用报告")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    import argparse
    if choice == "1":
        run_glossary(argparse.Namespace(glossary_cmd="list", map_name="de_mirage", scope="all", json=False), argparse.ArgumentParser())
        return
    if choice == "2":
        run_glossary(argparse.Namespace(glossary_cmd="list", map_name="de_dust2", scope="all", json=False), argparse.ArgumentParser())
        return
    if choice == "3":
        run_glossary(argparse.Namespace(glossary_cmd="list", map_name="de_anubis", scope="all", json=False), argparse.ArgumentParser())
        return
    if choice == "4":
        job = ask_job_path()
        run_glossary(argparse.Namespace(glossary_cmd="check", path=str(job), json=False), argparse.ArgumentParser())
        return
    print("没有这个选项。")


def run_players_menu() -> None:
    print("\n玩家识别与字幕显示名")
    print("=" * 72)
    print("用途：用 K-D-A、语音时长和队伍确认谁是谁，并把 demo 临时昵称改成最终字幕显示名。")
    print("例如确认 Ebule 是 donk 后，可以设置 Ebule -> donk；重新导出即可生效，不需要重跑 Whisper/LLM。")
    print("输入 0 / q / back 可返回主菜单。")
    print("1. 查看玩家列表 / K-D-A / 当前显示名")
    print("2. 设置字幕显示名")
    print("3. 清除字幕显示名")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    import argparse
    if choice == "1":
        job = ask_job_path()
        run_players(argparse.Namespace(players_cmd="list", path=str(job), json=False), argparse.ArgumentParser())
        return
    if choice == "2":
        job = ask_job_path()
        print("请输入 demo 中的玩家名，例如 Ebule。若重名，请改用专家命令 --steamid。")
        name = _read_choice("> ")
        print("请输入字幕显示名，例如 donk。")
        display = _read_choice("> ")
        run_players(argparse.Namespace(players_cmd="alias", path=str(job), name=name, steamid=None, display_name=display, json=False), argparse.ArgumentParser())
        return
    if choice == "3":
        job = ask_job_path()
        print("清除方式：1=按玩家名清除，2=清除全部。")
        mode = _read_choice("请选择 [1]\n> ", default="1")
        if mode == "2":
            run_players(argparse.Namespace(players_cmd="clear-alias", path=str(job), name=None, steamid=None, all=True, json=False), argparse.ArgumentParser())
        else:
            print("请输入 demo 中的玩家名。")
            name = _read_choice("> ")
            run_players(argparse.Namespace(players_cmd="clear-alias", path=str(job), name=name, steamid=None, all=False, json=False), argparse.ArgumentParser())
        return
    print("没有这个选项。")


def run_models_menu() -> None:
    print("\nWhisper 模型管理")
    print("=" * 72)
    print("用途：查看模型放在哪里、C 盘是否被占用、已有模型多大，以及 tiny/base/small/medium 哪个值得下载。")
    print("本工具采用项目级缓存配置，不会悄悄修改系统全局环境变量。")
    print("输入 0 / q / back 可返回主菜单。")
    print("1. 查看当前缓存目录和默认模型")
    print("2. 列出已下载模型")
    print("3. 查看模型大小与质量档位建议")
    print("4. 设置模型缓存目录到 D 盘/自定义目录")
    print("5. 测试当前/指定模型能否加载")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    import argparse
    if choice == "1":
        run_models(argparse.Namespace(models_cmd="info", json=False), argparse.ArgumentParser())
        return
    if choice == "2":
        run_models(argparse.Namespace(models_cmd="list", json=False), argparse.ArgumentParser())
        return
    if choice == "3":
        run_models(argparse.Namespace(models_cmd="recommend", json=False), argparse.ArgumentParser())
        return
    if choice == "4":
        print("请输入缓存根目录，例如 D:\\AIModels\\huggingface。")
        print("建议不要放在 output/ 或项目目录里；模型较大，推荐单独目录。")
        path = _read_choice("> ", default="D:\\AIModels\\huggingface")
        run_models(argparse.Namespace(models_cmd="set-cache", path=path), argparse.ArgumentParser())
        return
    if choice == "5":
        print("输入模型名，例如 small。直接回车使用当前默认模型。")
        model = _read_choice("> ", default="") or None
        print("是否只检查本地已有模型，不联网下载？1=是，2=否。")
        local = _read_choice("请选择 [1]\n> ", default="1") != "2"
        run_models(argparse.Namespace(models_cmd="test", model=model, profile=None, device=None, compute_type=None, cache_dir=None, local_only=local, json=False), argparse.ArgumentParser())
        return
    print("没有这个选项。")


def run_install_help_page() -> None:
    print("\n安装 / 首次使用教程")
    print("=" * 72)
    print("推荐方式：双击 Install_CS2_POV_Translator.bat。")
    print("它会按顺序执行：")
    print("  [1/4] 检查 Python")
    print("  [2/4] 创建 .venv 虚拟环境")
    print('  [3/4] 安装依赖 pip install -e ".[all]"')
    print("  [4/4] 运行 cs2pov setup-check")
    print("\n手动 PowerShell 方式：")
    print("  python -m venv .venv")
    print("  .\\.venv\\Scripts\\Activate.ps1")
    print('  pip install -e ".[all]"')
    print("  cs2pov setup-check")
    print("\n说明：首次 Whisper 模型下载可能需要时间，tiny/base/small 越大越慢。")
    print("处理 demo 前，建议先在主菜单选择 2 启动前检查。")


def run_help_page() -> None:
    print("\n常见场景：")
    print("1. 第一次处理 demo：选择主菜单 1，跟着 8 步向导走。")
    print("2. 不确定环境是否准备好：选择主菜单 2。")
    print("3. 不知道工程跑到哪：选择主菜单 3。")
    print("4. 不知道哪个文件该导入剪辑软件：选择主菜单 4。")
    print("5. 只想换剪辑/校对/调试字幕：选择主菜单 5，不会重新转录。")
    print("6. LLM 某回合失败：选择主菜单 6，不会重新转录。")
    print("7. 程序中途失败：选择主菜单 7，从失败阶段继续。")
    print("8. 要发给开发者分析：选择主菜单 8。")
    print("9. 想查看 Mirage/Dust2/Anubis 术语词典：选择主菜单 10。")
    print("10. 想把 Ebule 这类 demo 昵称显示成 donk：选择主菜单 11。")
    print("11. 子菜单中输 0、q、back 或 返回：不执行当前操作，回到主菜单。")
    print("\n对应专家命令：")
    print("  cs2pov setup-check")
    print("  cs2pov inspect-job output")
    print("  cs2pov explain-output output")
    print("  cs2pov export output --preset editing   # 推荐：剪辑双语优先")
    print("  cs2pov retranslate output")
    print("  cs2pov resume output --from-stage translate")
    print("  cs2pov feedback output")
    print("  cs2pov glossary list --map de_mirage")
    print("  cs2pov glossary check output")
    print("  cs2pov players list output")
    print("  cs2pov players alias output --name Ebule --as donk")


if __name__ == "__main__":
    raise SystemExit(main())
