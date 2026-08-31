from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from cs2pov.cli.encoding import configure_utf8_stdio
from cs2pov.cli.job_ops import (
    export_job,
    inspect_job,
    print_job_inspection,
    resolve_job_dir,
    resume_job,
    retranslate_job,
    warn_external_job,
    resolve_write_runtime,
    require_write_job,
)
from cs2pov.domain.models import PipelineConfig, StageName
from cs2pov.pipeline.engine import PipelineEngine
from cs2pov.pipeline.progress import ProgressSink, redact_text
from cs2pov.storage.config_store import load_config, save_config, mask_config_for_display, llm_model_warning
from cs2pov.cli.setup_check import build_setup_report, print_setup_report
from cs2pov.cli.output_explainer import build_output_explanation, print_output_explanation
from cs2pov.services.dictionary_service import glossary_terms_as_dicts, build_glossary_used_report, SUPPORTED_MAPS
from cs2pov.cli.model_manager import (
    TRANSCRIPTION_PROFILES,
    apply_profile_to_values,
    print_models_info,
    print_models_list,
    print_models_recommend,
    test_model_load,
)
from cs2pov.cli.player_ops import (
    build_players_report,
    clear_player_alias,
    print_players_report,
    set_player_alias,
)
from cs2pov.application.job_runtime import JobRuntime, JobRuntimeError
from cs2pov.application.demo_assets import DemoAssetUseCaseError
from cs2pov.application.workspace_runtime import WorkspaceRuntimeError, WorkspaceRuntimeResolver
from cs2pov.application.workspace_runtime import WorkspaceRuntime
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore, default_state_file
from cs2pov.cli.pipeline_demo import prepare_demo_asset


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(prog="cs2pov", description="CS2 POV bilingual subtitle pipeline")
    sub = parser.add_subparsers(dest="cmd")
    from cs2pov.cli.workspace_commands import add_workspace_parser
    add_workspace_parser(sub)
    from cs2pov.cli.demo_commands import add_demos_parser
    add_demos_parser(sub)

    run = sub.add_parser("run", help="专家模式：直接运行 pipeline")
    run.add_argument("demo")
    run.add_argument("--output", default=None)
    run.add_argument("--map", dest="map_name")
    run.add_argument("--pov-steamid")
    run.add_argument("--team", type=int, dest="team_number")
    run.add_argument("--export-scope", choices=["pov_team", "pov_player", "all"], default="pov_team")
    run.add_argument("--player-alias", action="append", default=[], help="字幕显示名映射，格式 steamid=显示名。适合 Ebule=donk 这类职业选手小号/临时昵称。")
    run.add_argument("--transcription-profile", choices=list(TRANSCRIPTION_PROFILES), default=None, help="转录质量档位：fast/balanced/quality/medium_cpu/cuda_quality。会自动设置模型、设备和 compute_type。")
    run.add_argument("--whisper-model", default=None)
    run.add_argument("--whisper-device", choices=["cpu", "cuda", "auto"], default=None, help="faster-whisper 设备：cpu/cuda/auto。普通用户建议用 profile。")
    run.add_argument("--whisper-compute-type", default=None, help="faster-whisper compute_type，如 int8/float16/int8_float16。普通用户建议用 profile。")
    run.add_argument("--whisper-cache-dir", default=None, help="项目级 Whisper/Hugging Face 模型缓存根目录，可放到 D 盘。")
    run.add_argument("--language", "--asr-language", dest="language", default="auto", help="ASR 语言：auto/en/ru/zh 等。默认 auto；遇到多语言混入时可用 --asr-language en 强制英文。")
    run.add_argument("--from-stage", choices=[s.value for s in StageName])
    run.add_argument("--to-stage", choices=[s.value for s in StageName])
    run.add_argument("--skip-translation", action="store_true")
    run.add_argument("--dry-run-translation", action="store_true")
    run.add_argument("--max-rounds", type=int)
    run.add_argument("--min-round-duration", type=float, default=10.0, help="过滤疑似暂停/重开产生的短回合，默认 10 秒")
    run.add_argument("--whisper-vad", action=argparse.BooleanOptionalAction, default=None, help="是否启用 faster-whisper VAD。默认开启；可用 --no-whisper-vad 关闭。")
    run.add_argument("--transcription-mode", choices=["round", "activity", "player"], default=None, help="转录切片模式：round=按回合+玩家切片，activity=按语音活动切片，player=旧版整名玩家 compact WAV。默认 round。")
    run.add_argument("--activity-padding", type=float, default=0.06, help="activity/round 切片时前后额外保留的秒数，默认 0.06。")
    run.add_argument("--keep-temp-audio", action="store_true", help="保留转录切片临时 WAV，便于调试；默认转录后删除。")
    run.add_argument("--include-unrecognized-voice", action="store_true", help="为未匹配到转录文本的语音活动补 [未识别语音] 占位，便于检查漏识别。")
    run.add_argument("--unrecognized-min-duration", type=float, default=0.35, help="补位/覆盖率统计的最短语音活动时长，默认 0.35 秒。")
    run.add_argument("--filter-hallucinations", action=argparse.BooleanOptionalAction, default=None, help="过滤 Whisper 纯标点/空白幻觉片段，默认开启；可用 --no-filter-hallucinations 关闭。")
    run.add_argument("--max-subtitle-segment-seconds", type=float, default=None, help="超过该时长的 ASR cue 会重贴到 voice activity 簇，默认 10 秒；设为 0 可关闭。")
    run.add_argument("--voice-cluster-gap", type=float, default=None, help="重贴长 cue 时，间隔小于该秒数的 voice activity 会合并为一簇，默认 1.0 秒。")
    run.add_argument("--bilingual-format", choices=["label", "arrow"], default=None, help="双语字幕格式：label=[中文] 标签，arrow=旧版箭头。默认 label。")
    run.add_argument("--subtitle-preset", choices=["editing", "review", "compact", "debug"], default=None, help="字幕导出预设：editing=推荐剪辑双语，review=校对，compact=紧凑双语，debug=诊断。")
    run.add_argument("--overlap-policy", choices=["allow", "shift", "compact", "merge", "stack"], default=None, help="字幕重叠策略：allow=保留真实重叠，shift=轻微错开，compact=尽量压紧，stack=同屏最多2条，后来者替代最早者（推荐剪映）；merge=合并整组。")
    run.add_argument("--min-subtitle-duration", type=float, default=None, help="导出 SRT 的最短显示时间，默认随预设。")
    run.add_argument("--glossary", action=argparse.BooleanOptionalAction, default=None, help="是否启用 global 通用术语 + 地图词典。当前地图词典试点 de_mirage/de_dust2/de_anubis，默认开启；可用 --no-glossary 关闭。")

    sub.add_parser("doctor", help="检查本机运行环境和可选依赖")
    setup = sub.add_parser("setup-check", help="启动前检查：用普通用户语言说明是否可以开始处理 demo")
    setup.add_argument("--json", action="store_true", help="输出 JSON，便于本地 agent 读取")

    cfg = sub.add_parser("config", help="配置 LLM / Whisper 默认值")
    cfg_sub = cfg.add_subparsers(dest="config_cmd")
    cfg_show = cfg_sub.add_parser("show")
    cfg_show.add_argument("--show-secrets", action="store_true", help="显示真实 API key。默认隐藏，避免误打包到反馈包。")
    cfg_set = cfg_sub.add_parser("set")
    cfg_set.add_argument("--base-url")
    cfg_set.add_argument("--api-key")
    cfg_set.add_argument("--model")
    cfg_set.add_argument("--transcription-profile", choices=list(TRANSCRIPTION_PROFILES), help="保存转录质量档位，并同步更新模型/设备/compute_type。")
    cfg_set.add_argument("--whisper-model")
    cfg_set.add_argument("--whisper-device", choices=["cpu", "cuda", "auto"])
    cfg_set.add_argument("--whisper-compute-type")
    cfg_set.add_argument("--whisper-cache-dir", help="已弃用：模型缓存跟随当前工作区；该选项只返回迁移说明。")
    cfg_set.add_argument("--whisper-vad", action=argparse.BooleanOptionalAction, default=None)
    cfg_set.add_argument("--transcription-mode", choices=["round", "activity", "player"])
    cfg_set.add_argument("--filter-hallucinations", action=argparse.BooleanOptionalAction, default=None)
    cfg_set.add_argument("--max-subtitle-segment-seconds", type=float)
    cfg_set.add_argument("--voice-cluster-gap", type=float)
    cfg_set.add_argument("--bilingual-format", choices=["label", "arrow"])
    cfg_set.add_argument("--subtitle-preset", choices=["editing", "review", "compact", "debug"])
    cfg_set.add_argument("--overlap-policy", choices=["allow", "shift", "compact", "merge", "stack"])
    cfg_set.add_argument("--min-subtitle-duration", type=float)
    cfg_set.add_argument("--glossary", action=argparse.BooleanOptionalAction, default=None, help="是否默认启用 global 通用术语 + 地图词典。")

    glossary = sub.add_parser("glossary", help="查看/检查 global 通用术语与 Mirage/Dust2/Anubis 地图词典。")
    glossary_sub = glossary.add_subparsers(dest="glossary_cmd")
    glossary_list = glossary_sub.add_parser("list", help="列出某张地图的术语词典")
    glossary_list.add_argument("--map", dest="map_name", default="de_mirage", help="地图名，默认 de_mirage。当前地图词典试点 de_mirage/de_dust2/de_anubis；global 通用术语始终可用。")
    glossary_list.add_argument("--scope", choices=["all", "global", "map"], default="all", help="词典范围：all=通用+地图，global=通用术语，map=当前地图报点。")
    glossary_list.add_argument("--json", action="store_true", help="输出 JSON")
    glossary_check = glossary_sub.add_parser("check", help="查看已有 Job 的 glossary_used / glossary_warnings")
    glossary_check.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    glossary_check.add_argument("--json", action="store_true", help="输出 JSON")


    players = sub.add_parser("players", help="玩家识别与字幕显示名：查看 K-D-A/语音时长，并设置 Ebule -> donk 这类别名")
    players_sub = players.add_subparsers(dest="players_cmd")
    players_list = players_sub.add_parser("list", help="列出 Job 中有语音的玩家、K-D-A 和字幕显示名")
    players_list.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    players_list.add_argument("--json", action="store_true")
    players_alias = players_sub.add_parser("alias", help="设置字幕显示名。设置后重新 export 即可生效，不需要重跑 Whisper/LLM")
    players_alias.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    players_alias.add_argument("--steamid", help="推荐：用 SteamID 精确指定玩家")
    players_alias.add_argument("--name", help="用 demo 昵称匹配玩家；若重名请改用 --steamid")
    players_alias.add_argument("--as", dest="display_name", required=True, help="字幕中显示的名字，例如 donk")
    players_alias.add_argument("--json", action="store_true")
    players_clear = players_sub.add_parser("clear-alias", help="清除字幕显示名映射")
    players_clear.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    players_clear.add_argument("--steamid")
    players_clear.add_argument("--name")
    players_clear.add_argument("--all", action="store_true", help="清除全部别名")
    players_clear.add_argument("--json", action="store_true")

    models = sub.add_parser("models", help="Whisper 模型管理：缓存位置、已下载模型、质量档位、模型可用性测试")
    models_sub = models.add_subparsers(dest="models_cmd")
    models_info = models_sub.add_parser("info", help="查看当前工作区模型缓存、旧缓存迁移信息和转录默认值")
    models_info.add_argument("--json", action="store_true")
    models_list = models_sub.add_parser("list", help="扫描当前工作区模型，并单独只读显示旧缓存模型")
    models_list.add_argument("--json", action="store_true")
    models_rec = models_sub.add_parser("recommend", help="查看 tiny/base/small/medium/CUDA 档位建议和近似大小")
    models_rec.add_argument("--json", action="store_true")
    cache_migration_help = "已弃用：模型缓存跟随当前工作区；仅显示迁移说明"
    models_cache = models_sub.add_parser(
        "set-cache",
        help=cache_migration_help,
        description=cache_migration_help,
    )
    models_cache.add_argument("path", help="旧缓存路径（只用于返回迁移说明，不会创建或保存）")
    models_test = models_sub.add_parser("test", help="测试某个 Whisper 模型能否加载；可能触发下载")
    models_test.add_argument("--model", default=None, help="默认使用当前配置模型")
    models_test.add_argument("--profile", choices=list(TRANSCRIPTION_PROFILES), default=None, help="用质量档位自动选择模型/设备/compute_type")
    models_test.add_argument("--device", choices=["cpu", "cuda", "auto"], default=None)
    models_test.add_argument("--compute-type", default=None)
    models_test.add_argument("--cache-dir", default=None, help="已弃用：不能覆盖当前工作区模型缓存")
    models_test.add_argument("--local-only", action="store_true", help="只检查本地已有模型，不联网下载")
    models_test.add_argument("--json", action="store_true")

    bench = sub.add_parser("benchmark-asr", help="对同一 demo 的前 N 个回合跑多个 Whisper 模型，生成耗时/片段数对比")
    bench.add_argument("demo")
    bench.add_argument("--output", default=None, help="旧版外部输出根目录（显式提供时启用兼容警告）")
    bench.add_argument("--models", default="tiny,base,small", help="逗号分隔，例如 base,small,medium")
    bench.add_argument("--team", type=int, dest="team_number")
    bench.add_argument("--max-rounds", type=int, default=3)
    bench.add_argument("--device", default=None, choices=["cpu", "cuda", "auto"])
    bench.add_argument("--compute-type", default=None)
    bench.add_argument("--language", "--asr-language", dest="language", default="auto")
    bench.add_argument("--cache-dir", default=None)
    bench.add_argument("--json", action="store_true")

    clean = sub.add_parser("clean", help="清理 job 中体积较大的中间产物，默认只预览不删除")
    clean.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    clean.add_argument("--yes", action="store_true", help="确认删除。没有 --yes 时只显示可释放空间。")
    clean.add_argument("--voice", action=argparse.BooleanOptionalAction, default=True, help="删除 artifacts/voice 中的 compact WAV/packet 缓存，默认 true。")
    clean.add_argument("--temp", action=argparse.BooleanOptionalAction, default=True, help="删除 artifacts/temp_audio 临时切片，默认 true。")

    feedback = sub.add_parser("feedback", help="打包一个不含大音频/密钥的反馈包，便于发给开发者")
    feedback.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    feedback.add_argument("--out", help="输出 zip 路径；默认放在目标 Job 的 debug/feedback 目录")

    inspect = sub.add_parser("inspect-job", help="查看 Job 状态、阶段、产物和推荐下一步")
    inspect.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则自动选择最新 Job")
    inspect.add_argument("--json", action="store_true", help="输出 JSON，便于本地 agent 或脚本读取")

    explain = sub.add_parser("explain-output", help="解释已有 Job 的 final/review/debug/artifacts 文件分别做什么")
    explain.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    explain.add_argument("--json", action="store_true", help="输出 JSON，便于本地 agent 读取")

    export = sub.add_parser("export", help="基于已有 Job 重新导出字幕，不重新转录/翻译")
    export.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    export.add_argument("--format", choices=["all", "bilingual", "compact", "zh", "zh_clean", "original", "debug", "voice"], default="all", help="导出格式。all 会同时生成双语/中文/紧凑/调试/语音活动。")
    export.add_argument("--team", type=int, dest="team_number", help="覆盖 Job 中保存的队伍编号")
    export.add_argument("--pov-steamid", help="覆盖 Job 中保存的 POV 玩家 SteamID")
    export.add_argument("--export-scope", choices=["pov_team", "pov_player", "all"], help="覆盖导出范围")
    export.add_argument("--bilingual-format", choices=["label", "arrow"], help="双语格式：label=[中文]，arrow=箭头")
    export.add_argument("--preset", choices=["editing", "review", "compact", "debug"], help="导出预设。editing=推荐剪辑双语；review=校对；compact=紧凑双语；debug=诊断。")
    export.add_argument("--overlap-policy", choices=["allow", "shift", "compact", "merge", "stack"], help="覆盖重叠策略：allow/shift/compact/merge/stack；stack 推荐剪映：同屏最多2条，后来者替代最早者；merge=合并整组重叠字幕")
    export.add_argument("--max-duration", type=float, help="覆盖最长显示时间，单位秒；0 表示不限制")
    export.add_argument("--min-duration", type=float, help="覆盖最短显示时间，单位秒")

    retranslate = sub.add_parser("retranslate", help="基于已有 round_contexts 重新翻译，并重新导出字幕")
    retranslate.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    retranslate.add_argument("--dry-run", action="store_true", help="不调用 LLM，用 [演示翻译] 生成字幕")
    retranslate.add_argument("--skip-translation", action="store_true", help="跳过翻译，生成未翻译占位")
    retranslate.add_argument("--model", help="临时指定 LLM model，不写入全局配置")
    retranslate.add_argument("--base-url", help="临时指定 LLM base_url，不写入全局配置")
    retranslate.add_argument("--no-export", action="store_true", help="只生成 translated_segments.jsonl，不重新导出 SRT")

    resume = sub.add_parser("resume", help="从已有 Job 的某个阶段恢复执行")
    resume.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    resume.add_argument("--from-stage", required=True, choices=[s.value for s in StageName], help="从哪个阶段继续，例如 translate/export_subtitles")
    resume.add_argument("--to-stage", choices=[s.value for s in StageName], help="可选：跑到哪个阶段停止")
    resume.add_argument("--demo", help="如果 Job input/ 里没有 demo，可手动指定原始 .dem/.dem.zst")

    comms = sub.add_parser("comms", help="v0.9.8：按回合生成可人工校对的双语通讯流和剪映 overlay 素材；默认画面不显示不可靠倒计时")
    comms_sub = comms.add_subparsers(dest="comms_cmd")
    comms_build = comms_sub.add_parser("build-review", help="从已有翻译结果生成 final/comms_feed 与 review/comms_rounds/round_XX.yaml")
    comms_build.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    comms_build.add_argument("--team", type=int, dest="team_number", help="覆盖 Job 中保存的队伍编号")
    comms_build.add_argument("--pov-steamid", help="覆盖 Job 中保存的 POV 玩家 SteamID")
    comms_build.add_argument("--export-scope", choices=["pov_team", "pov_player", "all"], help="覆盖导出范围")
    comms_build.add_argument("--rounds", help="只生成指定回合，例如 1、1-3、1,3,5-7")
    comms_build.add_argument("--time-display", choices=["none", "elapsed", "round-clock"], default="none", help="overlay 是否显示时间：none 默认不显示；elapsed 显示 +00:07；round-clock 为实验倒计时")
    comms_build.add_argument("--round-clock-start", default="1:55", help="仅 --time-display round-clock 实验使用：每回合默认起始回合时间，默认 1:55")
    comms_build.add_argument("--round-clock-end", default="0:00", help="仅 --time-display round-clock 实验使用：每回合默认结束回合时间，默认 0:00")
    comms_build.add_argument("--freeze-seconds", type=float, default=0.0, help="仅 --time-display round-clock 实验使用：准备/冻结时间，默认 0；不同平台/回合不稳定，不建议默认展示")
    comms_build.add_argument("--json", action="store_true", help="输出 JSON，便于本地 agent 读取")

    comms_render = comms_sub.add_parser("render", help="从 review/comms_rounds/round_XX.yaml 渲染每回合半透明/绿幕/预览 overlay")
    comms_render.add_argument("path", nargs="?", default=None, help="job 目录或工作区 jobs 根目录，省略则使用当前工作区")
    comms_render.add_argument("--rounds", help="只渲染指定回合，例如 1、1-3、1,3,5-7")
    comms_render.add_argument("--formats", default="preview,green", help="输出格式：preview,green,alpha,png，可逗号分隔。默认 preview,green")
    comms_render.add_argument("--width", type=int, default=1920)
    comms_render.add_argument("--height", type=int, default=1080)
    comms_render.add_argument("--panel-width", type=int, default=460)
    comms_render.add_argument("--panel-height", type=int, default=720)
    comms_render.add_argument("--right-margin", type=int, default=16)
    comms_render.add_argument("--y", type=int, default=None, help="面板顶部 y 坐标；不填则右侧中部略偏上")
    comms_render.add_argument("--max-messages", type=int, default=6, help="同屏最多显示最近几条通讯，默认 6")
    comms_render.add_argument("--fps", type=int, default=15)
    comms_render.add_argument("--fade-seconds", type=float, default=0.35, help="新消息淡入时间，默认 0.35 秒；设为 0 可关闭")
    comms_render.add_argument("--time-display", choices=["none", "elapsed", "round-clock"], default="none", help="overlay 是否显示时间：none 默认不显示；elapsed 显示 +00:07；round-clock 为实验倒计时")
    comms_render.add_argument("--freeze-seconds", type=float, default=0.0, help="仅 --time-display round-clock 且旧 YAML 缺少 freeze_seconds 时使用，默认 0")
    comms_render.add_argument("--classic-panel", action="store_true", help="使用 v0.9.0 的大面板背景；默认 v0.9.8 为无大面板浮动卡片")
    comms_render.add_argument("--font", dest="font_path", help=r"可选：指定字体文件，中文显示异常时可指定 C:\Windows\Fonts\msyh.ttc")
    comms_render.add_argument("--json", action="store_true", help="输出 JSON，便于本地 agent 读取")

    args = parser.parse_args(argv)
    if args.cmd is None:
        from cs2pov.cli.launcher import main as launcher_main
        return launcher_main([])

    try:
        return dispatch(args, parser)
    except (WorkspaceRuntimeError, JobRuntimeError, DemoAssetUseCaseError) as exc:
        payload = {"ok": False, "error": {"code": exc.code, "message_zh": exc.message_zh, "suggestion_zh": exc.suggestion_zh}}
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"错误[{exc.code}]：{exc.message_zh}")
            print(f"建议：{exc.suggestion_zh}")
        return 1
    except FileNotFoundError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": {"code": "job_not_found", "message_zh": str(exc), "suggestion_zh": "请检查 Job 路径，或先创建一个工作区 Job。"}}, ensure_ascii=False))
        else:
            print(f"错误：{exc}")
            print("提示：可以先运行 cs2pov inspect-job 查看当前工作区 jobs，或用 cs2pov-wizard 新建任务。")
        return 1
    except Exception as exc:
        print(f"处理失败：{type(exc).__name__}: {exc}")
        print("建议运行：cs2pov feedback，把生成的 zip 发给开发者。")
        raise


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.cmd == "workspace":
        from cs2pov.cli.workspace_commands import run_workspace
        return run_workspace(args)
    if args.cmd == "demos":
        from cs2pov.cli.demo_commands import run_demos
        return run_demos(args)
    if args.cmd == "doctor":
        return run_doctor()

    if args.cmd == "setup-check":
        report = build_setup_report(Path.cwd())
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if (report.get("ready_for_dry_run") or report.get("ready_for_translation")) else 1
        return print_setup_report(report)

    if args.cmd == "config":
        return run_config(args, parser)

    if args.cmd == "glossary":
        if args.glossary_cmd == "check":
            args.path = _resolve_job_argument(args.path, write=False)
        return run_glossary(args, parser)

    if args.cmd == "players":
        writing = args.players_cmd in {"alias", "clear-alias"}
        runtime = _resolve_write_runtime() if writing else (_resolve_read_runtime() if args.path is None else None)
        args.path = _resolve_job_argument(args.path, write=writing, runtime=runtime)
        return run_players(args, parser, runtime=runtime)

    if args.cmd == "models":
        return run_models(args, parser)

    if args.cmd == "benchmark-asr":
        return run_asr_benchmark(args, runtime=_resolve_write_runtime())

    if args.cmd == "clean":
        runtime = _resolve_write_runtime() if args.yes else (_resolve_read_runtime() if args.path is None else None)
        args.path = _resolve_job_argument(args.path, write=args.yes, runtime=runtime)
        return run_clean(args.path, delete=args.yes, clean_voice=args.voice, clean_temp=args.temp, runtime=runtime)

    if args.cmd == "feedback":
        runtime = _resolve_write_runtime()
        args.path = _resolve_job_argument(args.path, write=True, runtime=runtime)
        return run_feedback(args.path, out=Path(args.out) if args.out else None, runtime=runtime)

    if args.cmd == "inspect-job":
        summary = inspect_job(_resolve_job_argument(args.path, write=False))
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print_job_inspection(summary)
        return 0

    if args.cmd == "explain-output":
        report = build_output_explanation(_resolve_job_argument(args.path, write=False))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_output_explanation(report)
        return 0

    if args.cmd == "export":
        runtime = _resolve_write_runtime()
        args.path = _resolve_job_argument(args.path, write=True, runtime=runtime)
        outputs = export_job(
            args.path, fmt=args.format, team_number=args.team_number, pov_steamid=args.pov_steamid,
            export_scope=args.export_scope, bilingual_format=args.bilingual_format, preset=args.preset,
            overlap_policy=args.overlap_policy, max_duration_seconds=args.max_duration, min_duration_seconds=args.min_duration,
            runtime=runtime,
        )
        print("导出完成：")
        for key, value in outputs.items():
            print(f"  {key}: {value}")
        print("\n提示：如果字幕内容不是你想要的队伍/格式，可重新运行 cs2pov export 并加 --team / --format。")
        return 0

    if args.cmd == "retranslate":
        runtime = _resolve_write_runtime()
        args.path = _resolve_job_argument(args.path, write=True, runtime=runtime)
        outputs = retranslate_job(args.path, dry_run=args.dry_run, skip_translation=args.skip_translation, model=args.model, base_url=args.base_url, export_after=not args.no_export, runtime=runtime)
        print("重新翻译完成：")
        for key, value in outputs.items():
            print(f"  {key}: {value}")
        print("\n提示：如果 LLM 调用失败，可稍后再次运行同一命令；不会重新转录音频。")
        return 0

    if args.cmd == "resume":
        runtime = _resolve_write_runtime()
        args.path = _resolve_job_argument(args.path, write=True, runtime=runtime)
        job = resume_job(args.path, from_stage=StageName(args.from_stage), to_stage=StageName(args.to_stage) if args.to_stage else None, demo_path=Path(args.demo) if args.demo else None, runtime=runtime)
        print(f"恢复执行完成：{job}")
        print("你可以运行 cs2pov inspect-job 查看最新状态，或 cs2pov export 重新导出字幕。")
        return 0

    if args.cmd == "comms":
        return run_comms(args, parser)

    if args.cmd == "run":
        return run_pipeline(args)

    parser.error(f"未知命令：{args.cmd}")
    return 2


def _resolve_read_runtime() -> WorkspaceRuntime:
    return WorkspaceRuntimeResolver(JsonWorkspaceSelectionStore(default_state_file())).resolve_selected()


def _resolve_write_runtime() -> WorkspaceRuntime:
    return WorkspaceRuntimeResolver(JsonWorkspaceSelectionStore(default_state_file())).resolve_for_write()


def _resolve_job_argument(path: str | Path | None, *, write: bool, runtime: WorkspaceRuntime | None = None) -> Path:
    if path is not None:
        return Path(path)
    runtime = runtime or (_resolve_write_runtime() if write else _resolve_read_runtime())
    return runtime.paths.jobs_dir


def run_comms(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from cs2pov.cli.job_ops import _load_job_config_with_runtime_secrets, _require_job, _update_manifest_config_and_artifacts
    from cs2pov.services.comms_service import CommsRenderOptions, CommsService
    from cs2pov.storage.artifact_store import ArtifactStore

    if args.comms_cmd is None:
        parser.error("comms 需要 build-review 或 render")
        return 2
    runtime = _resolve_write_runtime()
    path = _resolve_job_argument(args.path, write=True, runtime=runtime)
    job_dir = _require_job(path)
    store = ArtifactStore(job_dir)
    cfg = _load_job_config_with_runtime_secrets(job_dir)
    rounds = _parse_rounds_arg(getattr(args, "rounds", None))

    if args.comms_cmd == "build-review":
        if args.team_number is not None:
            cfg.selected_team_number = args.team_number
        if args.pov_steamid is not None:
            cfg.selected_pov_steamid = args.pov_steamid
        if args.export_scope is not None:
            cfg.export_scope = args.export_scope
        outputs = CommsService().build_review(
            store,
            selected_team_number=cfg.selected_team_number,
            selected_pov_steamid=cfg.selected_pov_steamid,
            export_scope=cfg.export_scope,
            rounds=rounds,
            round_clock_start=args.round_clock_start,
            round_clock_end=args.round_clock_end,
            freeze_seconds=args.freeze_seconds,
            time_display=args.time_display.replace("-", "_"),
            runtime=runtime,
            warning_stream=sys.stderr if getattr(args, "json", False) else None,
        )
        _update_manifest_config_and_artifacts(store, cfg, outputs)
        if args.json:
            print(json.dumps(outputs, ensure_ascii=False, indent=2))
        else:
            print("Comms Feed 校对产物已生成：")
            print(f"  导出范围: export_scope={cfg.export_scope}, selected_team_number={cfg.selected_team_number}, selected_pov_steamid={cfg.selected_pov_steamid}")
            for key, value in outputs.items():
                print(f"  {key}: {value}")
            print("\n下一步：先人工检查 review/comms_rounds/round_XX.yaml；改完后运行 cs2pov comms render。")
        return 0

    if args.comms_cmd == "render":
        options = CommsRenderOptions(
            width=args.width,
            height=args.height,
            panel_width=args.panel_width,
            panel_height=args.panel_height,
            right_margin=args.right_margin,
            y=args.y,
            max_messages=args.max_messages,
            fps=args.fps,
            fade_seconds=args.fade_seconds,
            show_outer_panel=args.classic_panel,
            font_path=args.font_path,
            freeze_seconds=args.freeze_seconds,
            time_display=args.time_display.replace("-", "_"),
        )
        outputs = CommsService().render(
            store, rounds=rounds, formats=args.formats.split(","), options=options,
            temp_root=runtime.paths.temp_dir, runtime=runtime,
            subprocess_env=runtime.subprocess_environment(),
            warning_stream=sys.stderr if getattr(args, "json", False) else None,
        )
        _update_manifest_config_and_artifacts(store, cfg, outputs)
        if args.json:
            print(json.dumps(outputs, ensure_ascii=False, indent=2))
        else:
            print("Comms Overlay 已渲染：")
            for key, value in outputs.items():
                print(f"  {key}: {value}")
            print("\n剪映建议：v0.9.8 默认不显示不可靠倒计时，只显示 Round + 选手 + 双语通讯流；优先测试 alpha.mov；如果透明通道不兼容，用 green.mp4 加色度抠图。")
        return 0

    parser.error("comms 需要 build-review 或 render")
    return 2


def _parse_rounds_arg(value: str | None) -> set[int] | None:
    if not value:
        return None
    out: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if end < start:
                start, end = end, start
            out.update(range(start, end + 1))
        else:
            out.add(int(part))
    return out or None


def run_players(args: argparse.Namespace, parser: argparse.ArgumentParser, *, runtime: WorkspaceRuntime | None = None) -> int:
    if args.players_cmd == "list":
        report = build_players_report(Path(args.path))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_players_report(report)
            print("\n常用：确认 Ebule 是 donk 后，可运行：")
            print(f"  cs2pov players alias \"{args.path}\" --name Ebule --as donk")
            print("再运行：")
            print(f"  cs2pov export \"{args.path}\" --preset editing")
        return 0
    if args.players_cmd == "alias":
        runtime = runtime or _resolve_write_runtime()
        report = set_player_alias(Path(args.path), steamid=args.steamid, name=args.name, display_name=args.display_name,
                                  runtime=runtime, warning_stream=sys.stderr if getattr(args, "json", False) else None)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("字幕显示名已保存。重新导出字幕即可生效：")
            print(f"  cs2pov export \"{args.path}\" --preset editing")
            print_players_report(report)
        return 0
    if args.players_cmd == "clear-alias":
        runtime = runtime or _resolve_write_runtime()
        report = clear_player_alias(Path(args.path), steamid=args.steamid, name=args.name, all_aliases=args.all,
                                    runtime=runtime, warning_stream=sys.stderr if getattr(args, "json", False) else None)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("字幕显示名映射已清除。重新导出字幕即可生效。")
            print_players_report(report)
        return 0
    parser.error("players 需要 list/alias/clear-alias")
    return 2


def run_models(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from cs2pov.application.workspace_runtime import WorkspaceRuntimeError, WorkspaceRuntimeResolver
    from cs2pov.application.workspace import WorkspaceSelectionPortError
    from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore, default_state_file
    runtime = None
    try:
        if args.models_cmd in {"info", "list", "test"}:
            runtime = WorkspaceRuntimeResolver(JsonWorkspaceSelectionStore(default_state_file())).resolve_for_write() if args.models_cmd == "test" else WorkspaceRuntimeResolver(JsonWorkspaceSelectionStore(default_state_file())).resolve_selected()
    except (WorkspaceRuntimeError, WorkspaceSelectionPortError) as exc:
        code = getattr(exc, "code", "workspace_selection_required")
        message = getattr(exc, "message_zh", str(exc))
        suggestion = getattr(exc, "suggestion_zh", "请先选择工作区后重试。")
        payload = {"ok": False, "command": f"models.{args.models_cmd}", "error": {"code": code, "message_zh": message, "suggestion_zh": suggestion}}
        if getattr(exc, "diagnostic", None):
            payload["diagnostic"] = exc.diagnostic.to_dict()
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"无法执行 models {args.models_cmd}：{exc.message_zh}\n建议：{exc.suggestion_zh}")
        return 1
    if args.models_cmd == "info":
        return print_models_info(runtime, json_mode=args.json)
    if args.models_cmd == "list":
        return print_models_list(runtime, json_mode=args.json)
    if args.models_cmd == "recommend":
        return print_models_recommend(json_mode=args.json)
    if args.models_cmd == "set-cache":
        payload = {"ok": False, "command": "models.set-cache", "error": {"code": "legacy_model_cache_override_rejected", "message_zh": "该入口已弃用，模型缓存跟随当前工作区。", "suggestion_zh": "请先运行 workspace init/use；如需迁移请查看 models info。"}}
        if getattr(args, "json", False): print(json.dumps(payload, ensure_ascii=False))
        else: print(payload["error"]["message_zh"] + "\n" + payload["error"]["suggestion_zh"])
        return 1
    if args.models_cmd == "test":
        cfg = load_config()
        profile_id = args.profile or cfg.get("transcription_profile")
        if profile_id not in TRANSCRIPTION_PROFILES:
            profile_id = None
        profile_values = apply_profile_to_values(
            profile_id,
            whisper_model=args.model,
            whisper_device=args.device,
            whisper_compute_type=args.compute_type,
        )
        model = str(profile_values.get("whisper_model") or cfg.get("whisper_model") or "base")
        device = str(profile_values.get("whisper_device") or cfg.get("whisper_device") or "cpu")
        compute_type = str(profile_values.get("whisper_compute_type") or cfg.get("whisper_compute_type") or "int8")
        if args.cache_dir is not None:
            result = {"ok": False, "command": "models.test", "error": {"code": "legacy_model_cache_override_rejected", "message_zh": "--cache-dir 已弃用，请使用当前工作区缓存。", "suggestion_zh": "请移除该参数并使用当前工作区缓存。"}}
        else:
            result = test_model_load(
                model,
                device,
                compute_type,
                cache_dir=str(runtime.paths.whisper_cache_dir),
                local_only=args.local_only,
                workspace_root=str(runtime.root),
            )
        if not result.get("ok") and not isinstance(result.get("error"), dict):
            result = {"ok": False, "command": "models.test", "error": {"code": result.get("code", "model_load_failed"), "message_zh": str(result.get("error", "模型加载失败。")), "suggestion_zh": "请检查当前工作区缓存并重试。"}}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("Whisper 模型加载测试")
            print("=" * 72)
            print(f"model={model} device={device} compute_type={compute_type}")
            if result.get("cache_dir"):
                print(f"cache_dir={result.get('cache_dir')}")
            if result.get("ok"):
                print("OK：模型可以加载。")
            else:
                print("FAILED：模型无法加载。")
                error = result.get("error")
                if isinstance(error, dict):
                    print(error.get("message_zh", "模型加载失败。"))
                    print(f"建议：{error.get('suggestion_zh', '请检查当前工作区缓存并重试。')}")
                else:
                    print(f"{result.get('error_type', '错误')}: {error}")
                if args.local_only:
                    print("提示：当前是 --local-only，只检查本地已有模型；去掉该参数可能会触发下载。")
        return 0 if result.get("ok") else 1
    parser.error("models 需要 info/list/recommend/set-cache/test")
    return 2


def run_asr_benchmark(args: argparse.Namespace, *, runtime: WorkspaceRuntime | None = None) -> int:
    import time
    import sys
    from datetime import datetime
    from cs2pov.storage.jsonl import read_json, write_json

    runtime = runtime or _resolve_write_runtime()
    cfg = load_config()
    models = [m.strip() for m in str(args.models).split(",") if m.strip()]
    if not models:
        raise ValueError("--models 至少需要一个模型名，例如 base,small")
    if args.cache_dir is not None:
        raise JobRuntimeError(
            "legacy_model_cache_override_rejected",
            "--cache-dir 已弃用，benchmark 模型缓存固定使用当前工作区。",
            "请移除 --cache-dir，模型缓存将写入当前工作区 cache/whisper。",
        )
    explicit_output = args.output is not None
    path_policy = JobRuntime.from_config(runtime, PipelineConfig(), output_root=args.output)
    output_root = path_policy.output_root
    preparation = prepare_demo_asset(args.demo, runtime=runtime)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise JobRuntimeError(
            "job_path_escape", "Job 输出目录路径无效。", "请提供可访问的输出目录后重试。"
        ) from exc
    benchmark_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    def emit(*values: object) -> None:
        print(*values, file=sys.stderr if getattr(args, "json", False) else sys.stdout)
    if explicit_output:
        emit("警告：正在使用旧版外部输出兼容模式（旧版外部输出），benchmark Job 和报告将写入显式 --output 目录。")
    demo_display = preparation.display_name
    report: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "demo": demo_display,
        "demo_display": demo_display,
        "demo_asset_id": preparation.ref.asset_id,
        "demo_asset_disposition": preparation.result.disposition,
        "models": models,
        "team_number": args.team_number,
        "max_rounds": args.max_rounds,
        "runs": [],
        "note": "benchmark-asr 会重复运行小范围 pipeline，适合用前 3 回合比较 tiny/base/small/medium 在本机的耗时和字幕质量。",
    }
    emit("ASR 模型对比实验")
    emit("=" * 72)
    emit(f"demo={demo_display}")
    if preparation.result.disposition == "imported":
        emit("已导入到当前工作区素材库，之后可重复使用。")
    else:
        emit("工作区已有相同 Demo，本次直接复用，不再占用一份长期空间。")
    emit(f"models={', '.join(models)} team={args.team_number or '[自动/全部]'} max_rounds={args.max_rounds}")
    for model in models:
        from cs2pov.storage.artifact_store import safe_name
        safe_model_name = safe_name(model.replace("/", "_").replace("\\\\", "_"), 50)
        job_id = f"{benchmark_stamp}_benchmark_{safe_model_name}"
        config = PipelineConfig(
            output_root=str(output_root),
            job_id=job_id,
            selected_team_number=args.team_number,
            export_scope="pov_team",
            asr_language=args.language,
            transcription_profile="benchmark",
            whisper_model=model,
            whisper_device=args.device or cfg.get("whisper_device") or "cpu",
            whisper_compute_type=args.compute_type or cfg.get("whisper_compute_type") or "int8",
            whisper_cache_dir=str(runtime.paths.whisper_cache_dir),
            whisper_vad_filter=bool(cfg.get("whisper_vad_filter", True)),
            transcription_mode=cfg.get("transcription_mode") or "round",
            dry_run_translation=True,
            max_rounds=args.max_rounds,
            glossary_enabled=bool(cfg.get("glossary_enabled", True)),
            subtitle_bilingual_format=cfg.get("subtitle_bilingual_format") or "label",
            subtitle_export_preset=cfg.get("subtitle_export_preset") or "editing",
            subtitle_overlap_policy=cfg.get("subtitle_overlap_policy") or "stack",
            max_subtitle_segment_seconds=float(cfg.get("max_subtitle_segment_seconds", 10.0)),
            subtitle_min_duration_seconds=float(cfg.get("subtitle_min_duration_seconds", 0.7)),
        )
        emit(f"\n--- benchmark: {model} ---")
        started = time.perf_counter()
        ok = True
        error = None
        job_dir = None
        coverage = {}
        try:
            policy = JobRuntime(runtime, output_root, config, path_policy.legacy_external_output)
            engine = PipelineEngine(
                config,
                runtime=runtime,
                job_runtime=policy,
                demo_asset_ref=preparation.ref,
                demo_asset_display_name=preparation.display_name,
                demo_assets=preparation.service,
            )
            if args.json:
                engine.progress = ProgressSink(engine.store.progress_log_path, verbose=False)
            engine.run(None)
            job_dir = engine.store.job_dir.name
            if engine.store.transcription_coverage_path.exists():
                coverage = read_json(engine.store.transcription_coverage_path)
        except Exception as exc:  # pragma: no cover - depends on real demo/env
            ok = False
            error = redact_text(
                f"{type(exc).__name__}: {exc}",
                (
                    str(runtime.root),
                    str(output_root),
                    str(preparation.resolved_path),
                    str(Path(args.demo).expanduser().resolve()),
                ),
            )
            emit(f"FAILED: {error}")
        elapsed = round(time.perf_counter() - started, 3)
        item = {
            "model": model,
            "ok": ok,
            "elapsed_seconds": elapsed,
            "job_dir": job_dir,
            "error": error,
            "transcript_segments": coverage.get("postprocessed_transcript_segments") or coverage.get("transcript_segments"),
            "longest_transcript_segment_seconds": coverage.get("longest_transcript_segment_seconds"),
            "coverage_ratio_before_postprocess": coverage.get("coverage_ratio_before_postprocess"),
            "coverage_ratio_after_postprocess": coverage.get("coverage_ratio_after_postprocess"),
            "filtered_hallucination_segments": coverage.get("filtered_hallucination_segments"),
        }
        report["runs"].append(item)
        emit(f"result: ok={ok} elapsed={elapsed}s segments={item['transcript_segments']} longest={item['longest_transcript_segment_seconds']}")
    report_path = output_root / f"asr_benchmark_{benchmark_stamp}.json"
    write_json(report_path, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        emit("\nBenchmark 报告已生成：")
        emit(report_path)
        emit("建议：不要只看耗时，也要打开各 run 的 final/*.srt 比较字幕质量。")
    if explicit_output:
        emit("警告：旧版外部输出 benchmark 已完成；请检查并迁移该 Job。")
    return 0 if all(run.get("ok") for run in report["runs"]) else 1

def run_config(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.config_cmd == "show":
        cfg_data = load_config()
        if not args.show_secrets:
            cfg_data = mask_config_for_display(cfg_data)
        print(json.dumps(cfg_data, ensure_ascii=False, indent=2))
        warning = llm_model_warning(load_config().get("llm_model"))
        if warning:
            print(f"\n提示：{warning}")
        if not args.show_secrets and load_config().get("llm_api_key"):
            print("\n提示：API key 已隐藏。确需查看可用 cs2pov config show --show-secrets。")
        return 0
    if args.config_cmd == "set":
        if getattr(args, "whisper_cache_dir", None) is not None:
            payload = {"ok": False, "command": "config.set", "error": {"code": "legacy_model_cache_override_rejected", "message_zh": "whisper-cache-dir 已弃用，配置未修改。", "suggestion_zh": "模型缓存跟随当前工作区，请使用 workspace init/use。"}}
            print(json.dumps(payload, ensure_ascii=False) if getattr(args, "json", False) else payload["error"]["message_zh"] + "\n" + payload["error"]["suggestion_zh"])
            return 1
        updates = {}
        if getattr(args, "transcription_profile", None):
            updates.update(apply_profile_to_values(args.transcription_profile))
        for attr, key in [
            ("base_url", "llm_base_url"),
            ("api_key", "llm_api_key"),
            ("model", "llm_model"),
            ("whisper_model", "whisper_model"),
            ("whisper_device", "whisper_device"),
            ("whisper_compute_type", "whisper_compute_type"),
            ("whisper_cache_dir", "whisper_cache_dir"),
            ("transcription_mode", "transcription_mode"),
            ("max_subtitle_segment_seconds", "max_subtitle_segment_seconds"),
            ("voice_cluster_gap", "voice_cluster_gap_seconds"),
            ("bilingual_format", "subtitle_bilingual_format"),
            ("subtitle_preset", "subtitle_export_preset"),
            ("overlap_policy", "subtitle_overlap_policy"),
            ("min_subtitle_duration", "subtitle_min_duration_seconds"),
        ]:
            value = getattr(args, attr, None)
            if value is not None:
                updates[key] = value
        if (not getattr(args, "transcription_profile", None)) and any(getattr(args, name, None) is not None for name in ["whisper_model", "whisper_device", "whisper_compute_type"]):
            updates["transcription_profile"] = "custom"
        if args.whisper_vad is not None:
            updates["whisper_vad_filter"] = bool(args.whisper_vad)
        if args.filter_hallucinations is not None:
            updates["filter_hallucinations"] = bool(args.filter_hallucinations)
        if args.glossary is not None:
            updates["glossary_enabled"] = bool(args.glossary)
        path = save_config(updates)
        print(f"配置已保存：{path}")
        return 0
    parser.error("config 需要 show 或 set")
    return 2


def run_pipeline(args: argparse.Namespace) -> int:
    runtime = _resolve_write_runtime()
    if args.whisper_cache_dir is not None:
        raise JobRuntimeError(
            "legacy_model_cache_override_rejected",
            "--whisper-cache-dir 已弃用，不能覆盖当前工作区模型缓存。",
            "请移除该参数；模型缓存固定使用当前工作区 cache/whisper。",
        )
    defaults = load_config()
    explicit_whisper_override = any([args.whisper_model, args.whisper_device, args.whisper_compute_type])
    profile_id = args.transcription_profile or (None if explicit_whisper_override else defaults.get("transcription_profile"))
    if profile_id in TRANSCRIPTION_PROFILES:
        resolved_profile = apply_profile_to_values(
            profile_id,
            whisper_model=args.whisper_model,
            whisper_device=args.whisper_device,
            whisper_compute_type=args.whisper_compute_type,
        )
    else:
        resolved_profile = apply_profile_to_values(
            None,
            whisper_model=args.whisper_model,
            whisper_device=args.whisper_device,
            whisper_compute_type=args.whisper_compute_type,
        )
    config = PipelineConfig(
        output_root=args.output or str(runtime.paths.jobs_dir),
        map_name=args.map_name,
        selected_pov_steamid=args.pov_steamid,
        selected_team_number=args.team_number,
        export_scope=args.export_scope,
        asr_language=args.language,
        transcription_profile=str(resolved_profile.get("transcription_profile") or ("custom" if explicit_whisper_override else defaults.get("transcription_profile") or "balanced")),
        whisper_model=str(resolved_profile.get("whisper_model") or defaults.get("whisper_model") or "base"),
        whisper_device=str(resolved_profile.get("whisper_device") or defaults.get("whisper_device") or "cpu"),
        whisper_compute_type=str(resolved_profile.get("whisper_compute_type") or defaults.get("whisper_compute_type") or "int8"),
        whisper_cache_dir=str(runtime.paths.whisper_cache_dir),
        whisper_vad_filter=bool(defaults.get("whisper_vad_filter", True)) if args.whisper_vad is None else bool(args.whisper_vad),
        transcription_mode=args.transcription_mode or defaults.get("transcription_mode") or "round",
        activity_padding_seconds=args.activity_padding,
        keep_temp_audio=args.keep_temp_audio,
        llm_base_url=defaults.get("llm_base_url"),
        llm_api_key=defaults.get("llm_api_key"),
        llm_model=defaults.get("llm_model"),
        skip_translation=args.skip_translation,
        dry_run_translation=args.dry_run_translation,
        max_rounds=args.max_rounds,
        min_round_duration_seconds=args.min_round_duration,
        include_unrecognized_voice=args.include_unrecognized_voice,
        unrecognized_min_duration_seconds=args.unrecognized_min_duration,
        filter_hallucinations=bool(defaults.get("filter_hallucinations", True)) if args.filter_hallucinations is None else bool(args.filter_hallucinations),
        max_subtitle_segment_seconds=float(defaults.get("max_subtitle_segment_seconds", 10.0)) if args.max_subtitle_segment_seconds is None else float(args.max_subtitle_segment_seconds),
        voice_cluster_gap_seconds=float(defaults.get("voice_cluster_gap_seconds", 1.0)) if args.voice_cluster_gap is None else float(args.voice_cluster_gap),
        subtitle_bilingual_format=args.bilingual_format or defaults.get("subtitle_bilingual_format") or "label",
        subtitle_export_preset=args.subtitle_preset or defaults.get("subtitle_export_preset") or "editing",
        subtitle_overlap_policy=args.overlap_policy or defaults.get("subtitle_overlap_policy") or "stack",
        subtitle_min_duration_seconds=float(defaults.get("subtitle_min_duration_seconds", 0.7)) if args.min_subtitle_duration is None else float(args.min_subtitle_duration),
        glossary_enabled=bool(defaults.get("glossary_enabled", True)) if args.glossary is None else bool(args.glossary),
        player_aliases=_parse_player_alias_args(args.player_alias),
    )
    preparation = prepare_demo_asset(args.demo, runtime=runtime)
    if preparation.result.disposition == "imported":
        print("已导入到当前工作区素材库，之后可重复使用。")
    else:
        print("工作区已有相同 Demo，本次直接复用，不再占用一份长期空间。")
    policy = JobRuntime.from_config(runtime, config, output_root=args.output)
    config = policy.adapt_config(config)
    if policy.legacy_external_output:
        print("警告：正在使用旧版外部输出兼容模式（旧版外部输出），Job 将写入显式 --output 目录。")
    engine = PipelineEngine(
        config,
        runtime=runtime,
        job_runtime=policy,
        demo_asset_ref=preparation.ref,
        demo_asset_display_name=preparation.display_name,
        demo_assets=preparation.service,
    )
    from_stage = StageName(args.from_stage) if args.from_stage else None
    to_stage = StageName(args.to_stage) if args.to_stage else None
    engine.run(None, from_stage=from_stage, to_stage=to_stage)
    if policy.legacy_external_output:
        print("警告：旧版外部输出任务已完成；请检查并迁移该 Job。")
    return 0


def _parse_player_alias_args(values: list[str] | None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError("--player-alias 格式必须是 steamid=显示名，例如 7656119...=donk")
        sid, display = value.split("=", 1)
        sid = sid.strip()
        display = display.strip()
        if not sid or not display:
            raise ValueError("--player-alias 不能为空。格式：steamid=显示名")
        aliases[sid] = display
    return aliases


def run_doctor() -> int:
    import importlib.util
    import platform

    print("CS2 POV Translator 环境诊断")
    print("=" * 60)
    print(f"Python: {platform.python_version()} ({platform.system()} {platform.release()})")
    checks = [
        ("demoparser2", "解析 CS2 demo / 语音包"),
        ("zstandard", "解压 .dem.zst"),
        ("pyogg", "Opus 语音解码"),
        ("faster_whisper", "Whisper 转录"),
    ]
    ok = True
    for module, desc in checks:
        exists = importlib.util.find_spec(module) is not None
        print(f"{module:<16} {'OK' if exists else 'MISSING':<8} {desc}")
        ok = ok and exists
    cfg = load_config()
    print("-" * 60)
    print(f"转录质量档位:    {cfg.get('transcription_profile') or 'balanced'}")
    print(f"Whisper 默认模型: {cfg.get('whisper_model')}")
    print(f"Whisper 设备:    {cfg.get('whisper_device') or 'cpu'} / compute_type={cfg.get('whisper_compute_type') or 'int8'}")
    print(f"模型缓存目录:    {cfg.get('whisper_cache_dir') or '[未设置，使用默认 Hugging Face 缓存]'}")
    print(f"Whisper VAD:      {'ON' if cfg.get('whisper_vad_filter') else 'OFF'}")
    print(f"转录切片模式:    {cfg.get('transcription_mode') or 'round'}")
    print(f"幻觉过滤:        {'ON' if cfg.get('filter_hallucinations') else 'OFF'}")
    print(f"最长字幕重贴阈值: {cfg.get('max_subtitle_segment_seconds', 10.0)}s")
    print(f"双语字幕格式:    {cfg.get('subtitle_bilingual_format') or 'label'}")
    print(f"字幕导出预设:    {cfg.get('subtitle_export_preset') or 'editing'}")
    print(f"字幕重叠策略:    {cfg.get('subtitle_overlap_policy') or 'stack'}")
    print(f"最短显示时长:    {cfg.get('subtitle_min_duration_seconds', 0.7)}s")
    print(f"术语词典:        {'ON' if cfg.get('glossary_enabled', True) else 'OFF'}（global 通用术语 + 地图试点: {', '.join(SUPPORTED_MAPS)}）")
    print(f"LLM base_url: {cfg.get('llm_base_url') or '[未配置]'}")
    print(f"LLM model:    {cfg.get('llm_model') or '[未配置]'}")
    warning = llm_model_warning(cfg.get("llm_model"))
    if warning:
        print(f"LLM warning:  {warning}")
    print(f"LLM api_key:  {'[已配置]' if cfg.get('llm_api_key') else '[未配置]'}")
    if not ok:
        print("\n缺依赖时，建议运行：pip install -e .[all]")
        return 1
    print("\n基础依赖齐全。接下来可以运行 Start_CS2_POV_Translator.bat 或 cs2pov-wizard。")
    return 0



def run_glossary(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.glossary_cmd == "list":
        terms = glossary_terms_as_dicts(args.map_name, scope=getattr(args, "scope", "all"))
        payload = {
            "map_name": args.map_name,
            "supported_maps": list(SUPPORTED_MAPS),
            "scope": getattr(args, "scope", "all"),
            "term_count": len(terms),
            "terms": terms,
            "note": "v0.8.6 包含 global 通用术语 + de_mirage/de_dust2/de_anubis 地图试点。词典用于 prompt 约束和 warning 报告，不会硬替换字幕文本。",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("CS2 POV Translator 术语词典")
            print("=" * 72)
            print(f"地图: {args.map_name} | 范围: {getattr(args, 'scope', 'all')}")
            if not terms:
                print("当前版本没有这张地图的地图词典；仍可使用 global 通用术语。试点地图：de_mirage / de_dust2 / de_anubis。")
                return 0
            print("说明：词典仅用于翻译提示和术语 warning，不做硬替换。v0.8.6 包含 global 通用术语 pilot + Mirage/Dust2/Anubis 地图试点。")
            print("来源：英文/中文/俄语社区资料交叉整理，完整说明见 docs/GLOSSARY_MIRAGE_PILOT.zh.md、docs/GLOSSARY_DUST2_PILOT.zh.md 与 docs/GLOSSARY_ANUBIS_PILOT.zh.md。")
            for item in terms:
                ru = ", ".join(item.get("ru") or []) or "-"
                en = ", ".join(item.get("en") or [])
                print(f"- [{item['confidence']}] {item['id']}: {en} / {ru} -> {item['zh']}  ({item['zone']})")
        return 0
    if args.glossary_cmd == "check":
        from cs2pov.cli.job_ops import resolve_job_dir
        from cs2pov.storage.artifact_store import ArtifactStore
        from cs2pov.storage.jsonl import read_json
        job = resolve_job_dir(Path(args.path))
        if job is None:
            raise FileNotFoundError(f"找不到 Job 目录：{args.path}")
        store = ArtifactStore(job)
        try:
            used = read_json(store.glossary_used_path) if store.glossary_used_path.exists() else {}
        except Exception:
            used = {}
        try:
            warnings = read_json(store.glossary_warnings_path) if store.glossary_warnings_path.exists() else {}
        except Exception:
            warnings = {}
        payload = {"job_dir": str(job), "glossary_used": used, "glossary_warnings": warnings}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("CS2 POV Translator 词典使用报告")
            print("=" * 72)
            print(f"Job: {job}")
            if not used:
                print("未找到 artifacts/glossary_used.json。请先运行 translate/retranslate。")
                return 0
            print(f"地图: {used.get('map_name')} | enabled={used.get('enabled')} | global_supported={used.get('global_supported')} | map_supported={used.get('map_supported')}")
            print(f"词条数: {used.get('term_count')}（global={used.get('global_term_count')} map={used.get('map_term_count')}） | 命中词条数: {used.get('matched_term_count')}（global={used.get('matched_global_term_count')} map={used.get('matched_map_term_count')}）")
            warn_count = (warnings or {}).get("warning_count", 0)
            print(f"术语 warning: {warn_count}")
            if warn_count:
                print("前 10 条 warning：")
                for item in (warnings.get("warnings") or [])[:10]:
                    print(f"- {item.get('segment_id')}: {item.get('source')} -> {item.get('preferred_zh')} | {item.get('original_text')} => {item.get('translated_text')}")
            print("提示：warning 只是人工复核线索，不代表翻译一定错误。")
        return 0
    parser.error("glossary 需要 list 或 check")
    return 2

def run_clean(path: Path, delete: bool, clean_voice: bool = True, clean_temp: bool = True, runtime: WorkspaceRuntime | None = None) -> int:
    import shutil
    from cs2pov.storage.artifact_store import directory_size_bytes

    if delete:
        runtime = resolve_write_runtime(runtime)
    targets: list[Path] = []
    path = Path(path)
    if not path.exists():
        print(f"路径不存在：{path}")
        return 1

    candidate_jobs = [path] if (path / "manifest.json").exists() else [p for p in path.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    for job in candidate_jobs:
        if delete:
            warn_external_job(job, runtime)
        if clean_voice:
            targets.append(job / "artifacts" / "voice")
        if clean_temp:
            targets.append(job / "artifacts" / "temp_audio")
            targets.append(job / "debug" / "temp_audio")
            if runtime is not None:
                try:
                    job.resolve().relative_to(runtime.paths.jobs_dir.resolve())
                except ValueError:
                    pass
                else:
                    # Cache cleanup is intentionally limited to this Job ID.
                    targets.append(runtime.paths.audio_cache_dir / job.name)

    existing = [t for t in targets if t.exists()]
    total = sum(directory_size_bytes(t) for t in existing)
    print("CS2 POV Translator 清理预览")
    print("=" * 60)
    if not existing:
        print("没有找到可清理的 voice/temp_audio 目录。")
        return 0
    for t in existing:
        print(f"{_format_size(directory_size_bytes(t)):>10}  {t}")
    print("-" * 60)
    print(f"可释放约：{_format_size(total)}")
    if not delete:
        print("当前为预览模式；确认删除请追加 --yes。")
        return 0
    for t in existing:
        if t.is_symlink():
            t.unlink(missing_ok=True)
        else:
            shutil.rmtree(t, ignore_errors=True)
    print("清理完成。注意：删除 voice 缓存后，如需重新转录必须重新 extract_voice。")
    return 0


def run_feedback(path: Path | None, out: Path | None = None, *, runtime: WorkspaceRuntime | None = None) -> int:
    import zipfile
    from datetime import datetime

    job_dir, runtime = require_write_job(path, runtime)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out or job_dir / "debug" / "feedback" / f"cs2pov_feedback_{job_dir.name}_{stamp}.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    included = _feedback_files(job_dir)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in included:
            if file.exists() and file.is_file():
                arcname = str(file.relative_to(job_dir)).replace("\\", "/")
                sanitized = _sanitized_feedback_file(job_dir, file)
                if sanitized is None:
                    zf.write(file, arcname=arcname)
                else:
                    zf.writestr(arcname, sanitized)
        zf.writestr("README_FEEDBACK.txt", _feedback_readme(job_dir, included))

    print("反馈包已生成：")
    print(out_path)
    print("\n已排除 artifacts/voice 和 artifacts/temp_audio，避免打包大音频。")
    print("manifest.json 中的 API key 会保持脱敏；仍建议你上传前自己快速检查一次。")
    return 0


def _feedback_files(job_dir: Path) -> list[Path]:
    names = [
        "manifest.json",
        "progress.log",
        "errors.log",
        "artifacts/demo_info.json",
        "artifacts/rounds_raw.json",
        "artifacts/rounds.json",
        "artifacts/voice_activity.jsonl",
        "artifacts/transcript_segments.jsonl",
        "artifacts/round_contexts.jsonl",
        "artifacts/translated_segments.jsonl",
        "artifacts/transcription_coverage.json",
        "artifacts/glossary_used.json",
        "artifacts/glossary_warnings.json",
        "artifacts/player_stats.json",
        "artifacts/player_aliases.json",
    ]
    files = [job_dir / name for name in names]
    for folder in ["final", "review", "debug"]:
        base = job_dir / folder
        if base.exists():
            files.extend(sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in {".srt", ".txt", ".json", ".jsonl", ".log", ".yaml", ".yml", ".md", ".html"}))
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def _sanitized_feedback_file(job_dir: Path, file: Path) -> str | None:
    """Return sanitized text for shareable feedback files, or None to copy raw.

    Feedback packs are often uploaded to chats or issue trackers.  They should
    preserve technical diagnostics but avoid leaking local absolute paths such
    as ``D:\\个人项目\\...``.
    """
    rel = file.relative_to(job_dir).as_posix()

    if rel in {"manifest.json", "artifacts/demo_info.json"}:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            return None
        payload = _scrub_feedback_paths(payload, job_dir.name)
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    # Logs and text diagnostics can also contain absolute local paths printed
    # during export/resume operations.  Keep the debugging context, but strip
    # drive/user/project prefixes before the files leave the user's machine.
    if file.suffix.lower() in {".log", ".txt"}:
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return None
        except Exception:
            return None
        return _scrub_feedback_text(text, job_dir.name)

    return None


def _scrub_feedback_text(text: str, job_id: str) -> str:
    """Scrub local absolute paths from free-form feedback text.

    JSON files are sanitized structurally by ``_scrub_feedback_paths``.  Logs are
    free-form, so this helper handles the common cases seen on Windows and Unix:
    paths inside the current job become job-relative paths, while unrelated
    absolute paths are replaced with ``[已隐藏-本地路径]/<name>``.
    """
    text = text.replace("\\", "/")

    # If a log line contains a path into this job directory, keep only the
    # useful path inside the job, e.g. ``final/team_2.bilingual.srt``.
    job_pattern = re.compile(r"(?:[A-Za-z]:)?/(?:[^\s]+/)*" + re.escape(job_id) + r"/")
    text = job_pattern.sub("", text)

    def _hide_absolute(match: re.Match[str]) -> str:
        raw = match.group(0).rstrip(".,;:)")
        trailing = match.group(0)[len(raw):]
        suffix = raw.rsplit("/", 1)[-1]
        replacement = f"[已隐藏-本地路径]/{suffix}" if suffix else "[已隐藏-本地路径]"
        return replacement + trailing

    # Hide remaining absolute paths.  Keep the match conservative to avoid
    # altering URLs such as https://api.deepseek.com.
    text = re.sub(r"(?<![A-Za-z0-9_:/-])[A-Za-z]:/[^\s]+", _hide_absolute, text)
    text = re.sub(r"(?<![A-Za-z0-9_:/-])/(?:Users|home)/[^\s]+", _hide_absolute, text)
    return text


def _scrub_feedback_paths(value: Any, job_id: str) -> Any:
    if isinstance(value, dict):
        return {k: _scrub_feedback_paths(v, job_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_feedback_paths(v, job_id) for v in value]
    if not isinstance(value, str):
        return value
    text = value.replace("\\", "/")
    # Keep paths inside the job because they are useful for debugging, but drop
    # local drive/user/project prefixes.
    marker = f"/{job_id}/"
    if marker in text:
        return text.split(marker, 1)[1]
    marker_no_lead = f"{job_id}/"
    if marker_no_lead in text:
        return text.split(marker_no_lead, 1)[1]
    # Hide other absolute local paths, including original demo locations.
    if re.match(r"^[A-Za-z]:/", text) or text.startswith("/"):
        suffix = Path(text).name
        return f"[已隐藏-本地路径]/{suffix}" if suffix else "[已隐藏-本地路径]"
    return text


def _feedback_readme(job_dir: Path, included: list[Path]) -> str:
    rels = [p.relative_to(job_dir).as_posix() for p in included if p.exists()]
    return "\n".join([
        "CS2 POV Translator feedback pack",
        f"job_name={job_dir.name}",
        "job_dir=[已隐藏-本地路径]",
        "",
        "Included files:",
        *[f"- {name}" for name in rels],
        "",
        "Excluded by design:",
        "- artifacts/voice/",
        "- artifacts/temp_audio/",
        "- raw demo files",
        "- local absolute path prefixes",
    ])


def _format_size(n: int) -> str:
    value = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


if __name__ == "__main__":
    raise SystemExit(main())
