from __future__ import annotations

import json

from cs2pov.storage.config_store import (
    DEFAULT_DEEPSEEK_MODEL,
    is_deprecated_llm_model,
    llm_model_warning,
    mask_config_for_display,
    recommended_llm_model,
)


def test_deepseek_chat_has_replacement_warning() -> None:
    assert is_deprecated_llm_model("deepseek-chat")
    assert recommended_llm_model("deepseek-chat") == DEFAULT_DEEPSEEK_MODEL
    assert DEFAULT_DEEPSEEK_MODEL in (llm_model_warning("deepseek-chat") or "")


def test_deepseek_v4_flash_is_not_deprecated() -> None:
    assert not is_deprecated_llm_model(DEFAULT_DEEPSEEK_MODEL)
    assert recommended_llm_model(DEFAULT_DEEPSEEK_MODEL) is None
    assert llm_model_warning(DEFAULT_DEEPSEEK_MODEL) is None


def test_masked_config_marks_deprecated_model_without_leaking_key() -> None:
    masked = mask_config_for_display({"llm_api_key": "sk-secret", "llm_model": "deepseek-chat"})
    raw = json.dumps(masked, ensure_ascii=False)

    assert "sk-secret" not in raw
    assert masked["llm_api_key_configured"] is True
    assert masked["llm_model_deprecated"] is True
    assert masked["recommended_llm_model"] == DEFAULT_DEEPSEEK_MODEL
