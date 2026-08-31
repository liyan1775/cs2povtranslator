from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".cs2pov"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEPRECATED_LLM_MODELS: dict[str, str] = {
    "deepseek-chat": DEFAULT_DEEPSEEK_MODEL,
    "deepseek-reasoner": DEFAULT_DEEPSEEK_MODEL,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "llm_base_url": None,
    "llm_api_key": None,
    "llm_model": None,
    "transcription_profile": "balanced",
    "whisper_model": "base",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
    "whisper_cache_dir": None,
    "whisper_vad_filter": True,
    "transcription_mode": "round",
    "filter_hallucinations": True,
    "max_subtitle_segment_seconds": 10.0,
    "voice_cluster_gap_seconds": 1.0,
    "subtitle_bilingual_format": "label",
    "subtitle_export_preset": "editing",
    "subtitle_overlap_policy": "stack",
    "subtitle_min_duration_seconds": 0.7,
    "glossary_enabled": True,
}


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError):
        return dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(data: dict[str, Any]) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    merged = dict(load_config())
    merged.update(data)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return CONFIG_PATH


def mask_config_for_display(config: dict[str, Any]) -> dict[str, Any]:
    """Return config suitable for terminal output / feedback packs.

    The actual config file stores the API key locally so the tool can call the
    LLM, but display commands should not print secrets by default.
    """
    masked = dict(config)
    if masked.get("llm_api_key"):
        masked["llm_api_key"] = "[已配置-已隐藏]"
        masked["llm_api_key_configured"] = True
    else:
        masked["llm_api_key"] = None
        masked["llm_api_key_configured"] = False
    model = masked.get("llm_model")
    masked["llm_model_deprecated"] = is_deprecated_llm_model(model)
    replacement = recommended_llm_model(model)
    if replacement:
        masked["recommended_llm_model"] = replacement
    masked["whisper_cache_dir_deprecated"] = bool(masked.get("whisper_cache_dir"))
    if masked["whisper_cache_dir_deprecated"]:
        masked["whisper_cache_dir_note"] = "已弃用：模型缓存跟随当前工作区。"
    return masked


def is_deprecated_llm_model(model: str | None) -> bool:
    return bool(model and model.strip() in DEPRECATED_LLM_MODELS)


def recommended_llm_model(model: str | None) -> str | None:
    if not model:
        return None
    return DEPRECATED_LLM_MODELS.get(model.strip())


def llm_model_warning(model: str | None) -> str | None:
    replacement = recommended_llm_model(model)
    if not replacement:
        return None
    return f"模型 {model} 即将/已经不推荐继续使用，建议改为 {replacement}。"
