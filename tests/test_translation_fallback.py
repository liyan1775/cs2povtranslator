from cs2pov.services.translation_service import _fallback_translation


def test_fallback_messages_are_specific():
    assert _fallback_translation("hi", reason="unconfigured") == "[未翻译：未配置 LLM]"
    assert _fallback_translation("hi", reason="skipped") == "[未翻译：已跳过翻译]"
    assert _fallback_translation("hi", reason="llm_failed").startswith("[未翻译：LLM 调用失败")
    assert _fallback_translation("hi", reason="dry_run") == "[演示翻译] hi"
