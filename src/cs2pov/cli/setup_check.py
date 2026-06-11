from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path
from typing import Any

from cs2pov.storage.config_store import load_config, llm_model_warning
from cs2pov.services.dictionary_service import SUPPORTED_MAPS

REQUIRED_MODULES: list[tuple[str, str, str]] = [
    ("demoparser2", "CS2 demo 解析和语音包读取", 'pip install -e ".[all]"'),
    ("zstandard", ".dem.zst 解压", 'pip install -e ".[all]"'),
    ("pyogg", "Opus 语音解码", 'pip install -e ".[all]"'),
    ("faster_whisper", "Whisper 转录", 'pip install -e ".[all]"'),
]


def build_setup_report(project_root: Path | None = None) -> dict[str, Any]:
    """Build a user-facing readiness report.

    This intentionally differs from doctor: doctor is a technical dependency
    check, while setup-check answers the product question: "Can a normal user
    start processing a demo now, and what should they do next?"
    """
    root = project_root or Path.cwd()
    cfg = load_config()
    modules = []
    missing_required = False
    for module, desc, fix in REQUIRED_MODULES:
        ok = importlib.util.find_spec(module) is not None
        modules.append({"module": module, "description": desc, "ok": ok, "fix": fix})
        missing_required = missing_required or not ok
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    start_bat = root / "Start_CS2_POV_Translator.bat"
    installer_bat = root / "Install_CS2_POV_Translator.bat"
    api_key_configured = bool(cfg.get("llm_api_key"))
    llm_model = cfg.get("llm_model")
    llm_base_url = cfg.get("llm_base_url")
    model_warning = llm_model_warning(llm_model)
    ready_for_dry_run = not missing_required
    ready_for_translation = ready_for_dry_run and api_key_configured and bool(llm_model) and bool(llm_base_url)
    return {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "project_root": str(root),
        "venv_python_exists": venv_python.exists(),
        "start_bat_exists": start_bat.exists(),
        "installer_bat_exists": installer_bat.exists(),
        "modules": modules,
        "missing_required": missing_required,
        "transcription_profile": cfg.get("transcription_profile") or "balanced",
        "whisper_model": cfg.get("whisper_model") or "base",
        "whisper_device": cfg.get("whisper_device") or "cpu",
        "whisper_compute_type": cfg.get("whisper_compute_type") or "int8",
        "whisper_cache_dir": cfg.get("whisper_cache_dir"),
        "transcription_mode": cfg.get("transcription_mode") or "round",
        "whisper_vad_filter": bool(cfg.get("whisper_vad_filter", True)),
        "max_subtitle_segment_seconds": cfg.get("max_subtitle_segment_seconds", 10.0),
        "subtitle_export_preset": cfg.get("subtitle_export_preset") or "editing",
        "subtitle_overlap_policy": cfg.get("subtitle_overlap_policy") or "stack",
        "subtitle_bilingual_format": cfg.get("subtitle_bilingual_format") or "label",
        "glossary_enabled": bool(cfg.get("glossary_enabled", True)),
        "glossary_pilot_maps": list(SUPPORTED_MAPS),
        "llm_base_url_configured": bool(llm_base_url),
        "llm_model": llm_model,
        "llm_api_key_configured": api_key_configured,
        "llm_model_warning": model_warning,
        "ready_for_dry_run": ready_for_dry_run,
        "ready_for_translation": ready_for_translation,
    }


def print_setup_report(report: dict[str, Any]) -> int:
    print("CS2 POV Translator 启动前检查")
    print("=" * 72)
    print(f"Python: {report['python']} ({report['platform']})")
    print(f"项目目录: {report['project_root']}")
    print(f"本地虚拟环境: {'OK' if report['venv_python_exists'] else 'WARN'}  .venv\\Scripts\\python.exe")
    print(f"启动器:       {'OK' if report['start_bat_exists'] else 'WARN'}  Start_CS2_POV_Translator.bat")
    print(f"安装器:       {'OK' if report['installer_bat_exists'] else 'WARN'}  Install_CS2_POV_Translator.bat")
    print("\n基础依赖：")
    for item in report["modules"]:
        status = "OK" if item["ok"] else "MISSING"
        print(f"  {status:<8} {item['module']:<16} {item['description']}")
        if not item["ok"]:
            print(f"           修复建议：{item['fix']}")
    print("\n默认处理配置：")
    print(f"  转录质量档位:     {report['transcription_profile']}")
    print(f"  Whisper 模型:     {report['whisper_model']}")
    print(f"  Whisper 设备:     {report['whisper_device']} / compute_type={report['whisper_compute_type']}")
    print(f"  模型缓存目录:     {report['whisper_cache_dir'] or '[未设置，使用默认 Hugging Face 缓存]'}")
    print(f"  转录切片模式:     {report['transcription_mode']}")
    print(f"  Whisper VAD:      {'ON' if report['whisper_vad_filter'] else 'OFF'}")
    print(f"  最长字幕显示阈值: {report['max_subtitle_segment_seconds']}s")
    print(f"  字幕导出预设:     {report['subtitle_export_preset']}")
    print(f"  字幕重叠策略:     {report['subtitle_overlap_policy']}")
    print(f"  双语字幕格式:     {report['subtitle_bilingual_format']}")
    print(f"  地图术语词典:     {'ON' if report.get('glossary_enabled') else 'OFF'}（试点：{', '.join(report.get('glossary_pilot_maps') or [])}）")
    print("\n翻译配置：")
    print(f"  LLM base_url: {'已配置' if report['llm_base_url_configured'] else '未配置'}")
    print(f"  LLM model:    {report['llm_model'] or '未配置'}")
    print(f"  API key:      {'已配置' if report['llm_api_key_configured'] else '未配置'}")
    if report.get("llm_model_warning"):
        print(f"  模型提示:     {report['llm_model_warning']}")
    print("\n结论：")
    if report["ready_for_translation"]:
        print("  OK：可以直接处理真实 demo，并进行真实中文翻译。")
        print("  推荐入口：双击 Start_CS2_POV_Translator.bat，选择 1 新建字幕工程。")
        return 0
    if report["ready_for_dry_run"]:
        print("  PARTIAL：基础依赖齐全，可以先 dry-run 生成演示字幕。")
        print("  若要真实翻译，请运行：")
        print("    cs2pov config set --base-url https://api.deepseek.com --model deepseek-v4-flash --api-key sk-你的key")
        return 0
    print("  NOT READY：基础依赖不完整。")
    print("  首次安装建议：双击 Install_CS2_POV_Translator.bat，或在 PowerShell 中运行：")
    print('    python -m venv .venv')
    print('    .\\.venv\\Scripts\\Activate.ps1')
    print('    pip install -e ".[all]"')
    print('    cs2pov setup-check')
    return 1
