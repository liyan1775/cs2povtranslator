"""Tests for configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from cs2tl.config import (
    AppConfig,
    DictionaryConfig,
    LLMConfig,
    WhisperConfig,
    _build_config,
    _deep_merge,
    load_config,
    write_default_config,
)
from cs2tl.errors import CS2tlError


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_override(self):
        base = {"llm": {"provider": "openai", "model": "gpt-4o"}}
        override = {"llm": {"model": "gpt-3.5-turbo"}}
        result = _deep_merge(base, override)
        assert result["llm"]["provider"] == "openai"  # preserved
        assert result["llm"]["model"] == "gpt-3.5-turbo"  # overridden

    def test_new_key_added(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 2}


class TestBuildConfig:
    def test_empty_raw_produces_defaults(self):
        config = _build_config({})
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o"
        assert config.whisper.model == "base"

    def test_partial_override(self):
        config = _build_config({"llm": {"model": "claude-sonnet-4-6"}})
        assert config.llm.provider == "openai"  # default preserved
        assert config.llm.model == "claude-sonnet-4-6"


class TestLoadConfig:
    def test_loads_sample_config(self, sample_config_yml):
        config = load_config(cli_config_path=sample_config_yml)
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o"
        assert config.whisper.model == "base"
        assert config.dictionary.auto_update is False

    def test_cli_overrides_file(self, sample_config_yml, tmp_dir):
        """CLI path takes precedence over env/file."""
        override_path = tmp_dir / "override.yml"
        override_path.write_text(yaml.dump({"llm": {"model": "gpt-4-turbo"}}), encoding="utf-8")

        config = load_config(cli_config_path=override_path, project_config=sample_config_yml)
        assert config.llm.model == "gpt-4-turbo"

    def test_missing_config_file_raises_e7_0001(self):
        """Loading a nonexistent config file path raises E7-0001."""
        # This path bypasses load_config's graceful fallback and hits _load_yaml directly.
        from cs2tl.config import _load_yaml
        nonexistent = Path("/nonexistent/cs2tl_config_does_not_exist.yml")
        with pytest.raises(CS2tlError) as exc_info:
            _load_yaml(nonexistent)
        assert "E7-0001" in exc_info.value.code

    def test_env_var_override(self, sample_config_yml, tmp_dir, monkeypatch):
        env_path = tmp_dir / "env_config.yml"
        env_path.write_text(yaml.dump({"whisper": {"model": "large-v3"}}), encoding="utf-8")
        monkeypatch.setenv("CS2TL_CONFIG", str(env_path))

        config = load_config(project_config=sample_config_yml)
        assert config.whisper.model == "large-v3"


class TestApiKeyResolution:
    def test_env_var_fills_empty_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-envtest")
        config = _build_config({"llm": {"api_key": ""}})
        from cs2tl.config import _resolve_api_key
        config.llm = _resolve_api_key(config.llm)
        assert config.llm.api_key == "sk-envtest"

    def test_config_key_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fromenv")
        config = _build_config({"llm": {"api_key": "sk-fromfile"}})
        from cs2tl.config import _resolve_api_key
        config.llm = _resolve_api_key(config.llm)
        assert config.llm.api_key == "sk-fromfile"


class TestWriteDefaultConfig:
    def test_writes_valid_yaml(self, tmp_dir):
        path = tmp_dir / "config.yml"
        result = write_default_config(path, "openai", "sk-test", "gpt-4o")
        assert result.exists()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["llm"]["provider"] == "openai"
        assert data["llm"]["api_key"] == "sk-test"
        assert data["whisper"]["model"] == "base"


class TestValidation:
    def test_invalid_whisper_model_raises(self):
        with pytest.raises(ValueError, match="Invalid Whisper model"):
            WhisperConfig(model="huge")

    def test_default_config_valid(self):
        config = AppConfig()
        assert config.llm.provider == "openai"
        assert config.whisper.device == "auto"
