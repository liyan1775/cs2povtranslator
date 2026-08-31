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
    parser = argparse.ArgumentParser(description="CS2 POV Translator 极简菜单式启动器")
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
                run_comms_overlay_menu()
            elif choice == "3":
                run_project_menu()
            elif choice == "4":
                job = ask_job_path()
                run_feedback(job)
            elif choice == "5":
                print_setup_report(build_setup_report(Path.cwd()))
            elif choice == "6":
                run_tools_menu()
            else:
                print("没有这个选项。请输入 0-6。")
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
            print("建议：先选择 3 查看工程状态，或选择 4 打包反馈包发给开发者。")
        if args.once:
            return 0
        input("\n按回车返回主菜单...")


def print_banner() -> None:
    print("=" * 64)
    print("CS2 POV Translator v0.9.8")
    print("主功能：POV 通讯流 Overlay（按回合校对，再放进剪映）")
    print("=" * 64)
    print("推荐流程：1 新建工程 → 校对 YAML → 2 渲染 overlay → 剪映叠加。")
    print("v0.9.8 默认不显示不可靠倒计时，只显示 Round + 选手 + 双语通讯流。")
    print("遇到问题：先选 3 看状态；要发给开发者就选 4 打包反馈包。")
    try:
        from cs2pov.application.workspace import WorkspaceApplicationService, WorkspaceUseCaseError
        from cs2pov.application.workspace import WorkspaceSelectionPortError
        from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore, default_state_file
        view = WorkspaceApplicationService(JsonWorkspaceSelectionStore(default_state_file())).show_current()
        status = "已选择" if view.diagnostic.ok else "需要修复"
    except (WorkspaceUseCaseError, WorkspaceSelectionPortError) as exc:
        status = "未选择" if exc.code == "selection_missing" else "需要修复"
    print(f"工作区状态：{status}")


def print_menu() -> None:
    print("\n" + "-" * 64)
    print("核心菜单")
    print("-" * 64)
    print("1. 新建 POV 通讯流工程（demo → 可校对 YAML + Comms Feed）")
    print("2. 渲染 Comms Overlay（YAML → 每回合剪映素材）")
    print("3. 查看工程 / 输出说明")
    print("4. 打包反馈包（发给开发者排查）")
    print("5. 启动前检查")
    print("6. 设置与高级工具（模型、玩家别名、词典、SRT、恢复等）")
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



def run_project_menu() -> None:
    print("\n查看工程 / 输出说明")
    print("=" * 64)
    print("1. 查看工程状态 inspect-job")
    print("2. 解释输出文件 explain-output")
    print("0. 返回主菜单")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    job = ask_job_path()
    if choice == "1":
        print_job_inspection(inspect_job(job))
        return
    if choice == "2":
        print_output_explanation(build_output_explanation(job))
        return
    print("没有这个选项。")


def run_tools_menu() -> None:
    print("\n设置与高级工具")
    print("=" * 64)
    print("常用工具被收进这里，避免主菜单吓到新用户。")
    print("1. Whisper 模型管理")
    print("2. 玩家识别 / 设置显示名")
    print("3. 地图词典试点")
    print("4. 重新导出 SRT 字幕（可选资产）")
    print("5. 重新翻译")
    print("6. 从失败阶段恢复")
    print("7. 技术环境诊断 doctor")
    print("8. 安装 / 首次使用教程")
    print("9. 命令帮助和常见场景")
    print("10. 工作区管理")
    print("0. 返回主菜单")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    if choice == "1":
        run_models_menu()
    elif choice == "2":
        run_players_menu()
    elif choice == "3":
        run_glossary_menu()
    elif choice == "4":
        run_export_menu()
    elif choice == "5":
        run_retranslate_menu()
    elif choice == "6":
        run_resume_menu()
    elif choice == "7":
        run_doctor()
    elif choice == "8":
        run_install_help_page()
    elif choice == "9":
        run_help_page()
    elif choice == "10":
        run_workspace_menu()
    else:
        print("没有这个选项。")


def run_workspace_menu() -> None:
    from cs2pov.cli.workspace_commands import run_workspace
    import argparse
    print("\n工作区管理")
    print("当前步骤只设置新版本数据目录；模型和任务接入将在下一阶段完成。")
    print("1. 初始化并设为当前工作区")
    print("2. 使用已有工作区")
    print("3. 查看当前工作区")
    print("4. 诊断工作区")
    print("5. 忘记当前选择")
    choice = _read_choice("请选择 [3]\n> ", default="3")
    if choice in {"1", "2"}:
        path = _read_choice("请输入工作区绝对路径\n> ").strip().strip('"')
        run_workspace(argparse.Namespace(workspace_cmd="init" if choice == "1" else "use", path=path, json=False))
    elif choice == "3":
        run_workspace(argparse.Namespace(workspace_cmd="show", path=None, json=False))
    elif choice == "4":
        path = _read_choice("指定路径，直接回车诊断当前选择\n> ", default=None)
        run_workspace(argparse.Namespace(workspace_cmd="doctor", path=path, json=False))
    elif choice == "5":
        print("忘记选择只删除路径指针，不会删除工作区文件。")
        run_workspace(argparse.Namespace(workspace_cmd="forget", path=None, json=False))

def run_export_menu() -> None:
    print("\n重新导出不会重新转录，也不会重新调用 LLM。")
    print("v0.9.8 推荐先选 preset editing：剪辑双语优先，并默认 stack（同屏最多2条，第三条替代最早条），适配剪映。")
    print("输入 0 / q / back 可返回主菜单。")
    job = ask_job_path()
    print("请选择导出方式：")
    print("1. preset editing  推荐：双语 + 紧凑双语 + 中文兜底，默认 stack 同屏最多2条，适配剪映")
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
    print("重叠策略：1=使用预设，2=allow 保留真实重叠，3=shift 轻微错开，4=compact 尽量压紧，5=stack 同屏最多2条，后来者替代最早者（推荐剪映），6=merge 合并整组（不推荐默认）")
    print("0. 返回主菜单")
    overlap_choice = _read_choice("请选择 [1]\n> ", default="1")
    overlap = {"2": "allow", "3": "shift", "4": "compact", "5": "stack", "6": "merge"}.get(overlap_choice)
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
    print("模型缓存跟随当前工作区；旧缓存只读显示，不会自动迁移或修改系统全局环境变量。")
    print("输入 0 / q / back 可返回主菜单。")
    print("1. 查看当前缓存目录和默认模型")
    print("2. 列出已下载模型")
    print("3. 查看模型大小与质量档位建议")
    print("4. 查看旧缓存迁移说明")
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
        run_models(argparse.Namespace(models_cmd="info", json=False), argparse.ArgumentParser())
        return
    if choice == "5":
        print("输入模型名，例如 small。直接回车使用当前默认模型。")
        model = _read_choice("> ", default="") or None
        print("是否只检查本地已有模型，不联网下载？1=是，2=否。")
        local = _read_choice("请选择 [1]\n> ", default="1") != "2"
        run_models(argparse.Namespace(models_cmd="test", model=model, profile=None, device=None, compute_type=None, cache_dir=None, local_only=local, json=False), argparse.ArgumentParser())
        return
    print("没有这个选项。")


def run_comms_overlay_menu() -> None:
    print("\nComms Overlay 通讯流素材")
    print("=" * 72)
    print("用途：把已有翻译结果做成每回合一个 overlay 素材，叠到 lim/POV 视频上。")
    print("推荐流程：先生成 YAML → 人工改翻译/禁用废话 → 再渲染 preview/green。")
    print("重要：POV 通常只需要某一队 5 个人。若本地 agent 没按 .bat 向导选择队伍，请在这里手动输入 team 2 或 3。")
    print("输入 0 / q / back 可返回主菜单。")
    job = ask_job_path()
    print("请选择操作：")
    print("1. 生成可人工校对的 YAML/HTML/Markdown（build-review）")
    print("2. 从已校对 YAML 渲染 overlay 视频（render）")
    print("3. 先 build-review 再 render（适合快速试 1-3 回合）")
    choice = _read_choice("请选择 [1]\n> ", default="1")
    print("只处理哪些回合？例如 1、1-3、1,3,5-7。直接回车 = 全部已有回合。")
    rounds_raw = _read_choice("> ", default="").strip()
    rounds = _parse_rounds_for_launcher(rounds_raw)

    do_build = choice in {"1", "3"}
    do_render = choice in {"2", "3"}
    if do_build:
        _launcher_build_comms_review(job, rounds)
    if do_render:
        _launcher_render_comms(job, rounds)


def _parse_rounds_for_launcher(value: str) -> set[int] | None:
    if not value:
        return None
    out: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
            if end < start:
                start, end = end, start
            out.update(range(start, end + 1))
        else:
            out.add(int(part))
    return out or None


def _launcher_build_comms_review(job: Path, rounds: set[int] | None) -> None:
    from cs2pov.cli.job_ops import _load_job_config_with_runtime_secrets, _require_job, _update_manifest_config_and_artifacts
    from cs2pov.services.comms_service import CommsService
    from cs2pov.storage.artifact_store import ArtifactStore

    job_dir = _require_job(job)
    store = ArtifactStore(job_dir)
    cfg = _load_job_config_with_runtime_secrets(job_dir)
    print("\n当前 Job 保存的选择：")
    print(f"  export_scope={cfg.export_scope}")
    print(f"  selected_team_number={cfg.selected_team_number}")
    print(f"  selected_pov_steamid={cfg.selected_pov_steamid}")
    print("POV 只需要某一队时，建议 export_scope=pov_team 且 selected_team_number 为 2 或 3。")
    print("要覆盖队伍编号吗？输入 2/3；直接回车 = 使用当前 Job 配置。")
    team_raw = _read_choice("> ", default="").strip()
    if team_raw:
        cfg.selected_team_number = int(team_raw)
        cfg.export_scope = "pov_team"
    print("导出范围：1=当前队伍 pov_team（推荐），2=仅 POV 玩家 pov_player，3=全部 all。")
    scope_choice = _read_choice("请选择 [1]\n> ", default="1")
    cfg.export_scope = {"1": "pov_team", "2": "pov_player", "3": "all"}.get(scope_choice, cfg.export_scope or "pov_team")
    outputs = CommsService().build_review(
        store,
        selected_team_number=cfg.selected_team_number,
        selected_pov_steamid=cfg.selected_pov_steamid,
        export_scope=cfg.export_scope,
        rounds=rounds,
    )
    _update_manifest_config_and_artifacts(store, cfg, outputs)
    print("\nComms Feed 校对产物已生成：")
    print(f"  导出范围: export_scope={cfg.export_scope}, selected_team_number={cfg.selected_team_number}, selected_pov_steamid={cfg.selected_pov_steamid}")
    for k, v in outputs.items():
        print(f"  {k}: {v}")
    print("下一步：打开 review/comms_rounds/round_XX.yaml，人工改 zh/source/speaker/enabled，然后回到本菜单选择 render。")


def _launcher_render_comms(job: Path, rounds: set[int] | None) -> None:
    from cs2pov.cli.job_ops import _load_job_config_with_runtime_secrets, _require_job, _update_manifest_config_and_artifacts
    from cs2pov.services.comms_service import CommsRenderOptions, CommsService
    from cs2pov.storage.artifact_store import ArtifactStore

    job_dir = _require_job(job)
    store = ArtifactStore(job_dir)
    cfg = _load_job_config_with_runtime_secrets(job_dir)
    print("\n输出格式：")
    print("1. preview,green（推荐先测：预览 + 剪映绿幕兜底）")
    print("2. png（只出单帧，最快检查排版）")
    print("3. preview,green,alpha（额外尝试透明 mov，文件较大）")
    fmt_choice = _read_choice("请选择 [1]\n> ", default="1")
    formats = {"1": "preview,green", "2": "png", "3": "preview,green,alpha"}.get(fmt_choice, "preview,green")
    outputs = CommsService().render(store, rounds=rounds, formats=formats.split(","), options=CommsRenderOptions())
    _update_manifest_config_and_artifacts(store, cfg, outputs)
    print("\nComms Overlay 已渲染：")
    for k, v in outputs.items():
        print(f"  {k}: {v}")
    print("剪映建议：v0.9.8 默认右侧贴边、无大面板、无倒计时；preview 检查排版，green 用色度抠图，alpha.mov 只做兼容性测试。")


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
    print("处理 demo 前，建议先在主菜单选择 5 启动前检查。")


def run_help_page() -> None:
    print("\n常见场景：")
    print("1. 第一次处理 demo：主菜单 1，新建 POV 通讯流工程。")
    print("2. 工程跑完后想生成剪映素材：主菜单 2，渲染 Comms Overlay。")
    print("3. 不知道工程跑到哪、哪个文件该看：主菜单 3。")
    print("4. 要发给开发者分析：主菜单 4，打包反馈包。")
    print("5. 不确定环境是否准备好：主菜单 5，启动前检查。")
    print("6. 模型、玩家别名、词典、SRT、重翻译、恢复：主菜单 6，设置与高级工具。")
    print("7. 子菜单中输 0、q、back 或 返回：不执行当前操作，回到主菜单。")
    print("\n对应专家命令：")
    print("  cs2pov setup-check")
    print("  cs2pov inspect-job output")
    print("  cs2pov explain-output output")
    print("  cs2pov comms build-review output --rounds 1-3  # 主功能：生成通讯流校对文件")
    print("  cs2pov comms render output --rounds 1-3 --formats preview,green")
    print("  cs2pov export output --preset editing   # 可选：重新导出 SRT 字幕")
    print("  cs2pov retranslate output")
    print("  cs2pov resume output --from-stage translate")
    print("  cs2pov feedback output")
    print("  cs2pov glossary list --map de_mirage")
    print("  cs2pov glossary check output")
    print("  cs2pov players list output")
    print("  cs2pov players alias output --name Ebule --as donk")


if __name__ == "__main__":
    raise SystemExit(main())
