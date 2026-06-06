"""Tests for translator module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cs2tl.translator import (
    FALLBACK_PREFIX,
    TranslationSegment,
    _estimate_cost,
    _estimate_tokens,
    _format_voice_lines,
    _parse_response,
    build_system_prompt,
    call_llm,
)


class TestTranslationSegment:
    def test_creation(self):
        seg = TranslationSegment(
            steam_id="sid1",
            player_name="donk",
            team="T",
            start_time=10.0,
            end_time=12.5,
            original_text="I'm holding cat",
            translated_text="我在架A小",
            round_number=3,
            warnings=[],
        )
        assert seg.player_name == "donk"
        assert seg.translated_text == "我在架A小"


class TestPromptBuilding:
    def test_default_prompt_includes_target_language(self):
        prompt = build_system_prompt(target_language="简体中文")
        assert "简体中文" in prompt
        assert "CS2" in prompt

    def test_prompt_includes_term_table_when_provided(self):
        prompt = build_system_prompt(term_table="| cat | A小 |")
        assert "cat" in prompt
        assert "A小" in prompt

    def test_prompt_includes_no_dict_note_when_empty(self):
        prompt = build_system_prompt(no_dictionary=True)
        assert "No map-specific dictionary" in prompt or "general gaming" in prompt

    def test_custom_template(self):
        custom = "Translate to {target_language}. Terms: {term_table_section}. Lines: {voice_lines}."
        prompt = build_system_prompt(
            target_language="Chinese",
            term_table="B = B点",
            custom_template=custom,
        )
        assert "Chinese" in prompt
        assert "B点" in prompt


class TestParseResponse:
    def test_parses_valid_json_array(self):
        response = json.dumps([
            {"line": 1, "translated": "我在架A小"},
            {"line": 2, "translated": "A大打了一颗烟"},
        ])
        result = _parse_response(response, 2)
        assert len(result) == 2
        assert result[0] == "我在架A小"

    def test_fallback_on_invalid_json(self):
        response = "not valid json at all"
        result = _parse_response(response, 3)
        assert len(result) == 3
        assert result[0] == response  # raw text repeated

    def test_fallback_prefix_preserved(self):
        response = f"{FALLBACK_PREFIX} API error"
        result = _parse_response(response, 2)
        assert result[0].startswith(FALLBACK_PREFIX)

    def test_extracts_json_from_markdown_code_block(self):
        response = '```json\n[{"translated": "test"}]\n```'
        result = _parse_response(response, 1)
        assert result[0] == "test"


class TestFormatVoiceLines:
    def test_formats_numbered_list(self):
        segs = [
            MagicMock(steam_id="sid1", text="hello"),
            MagicMock(steam_id="sid2", text="world"),
        ]
        output = _format_voice_lines(segs)
        assert "1." in output
        assert "2." in output
        assert "sid1" in output
        assert "hello" in output


class TestTokenEstimation:
    def test_estimate_tokens_english(self):
        tokens = _estimate_tokens("hello world testing 123")
        assert tokens > 0

    def test_estimate_cost(self):
        cost = _estimate_cost(1000, 500, "gpt-4o")
        assert cost > 0


class TestCallLLM:
    def test_returns_fallback_on_no_api_key(self):
        from cs2tl.config import LLMConfig
        cfg = LLMConfig(provider="openai", api_key="", model="gpt-4o")
        result = call_llm("system", "user", cfg, max_retries=0)
        assert FALLBACK_PREFIX in result

    def test_raises_auth_error_on_401(self, monkeypatch):
        from cs2tl.config import LLMConfig
        cfg = LLMConfig(provider="openai", api_key="sk-fake", model="gpt-4o")

        def mock_call(*args, **kwargs):
            raise Exception("401 Unauthorized")
        monkeypatch.setattr("cs2tl.translator._call_openai", mock_call)

        from cs2tl.errors import CS2tlError
        with pytest.raises(CS2tlError) as exc_info:
            call_llm("sys", "user", cfg, max_retries=0)
        assert exc_info.value.code == "E5-0001"


import json

import pytest
