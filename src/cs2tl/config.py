"""Configuration loading and validation.

Config resolution precedence:
  1. --config / -c CLI flag
  2. CS2TL_CONFIG environment variable
  3. ./.cs2tl.yml (project-local, current directory)
  4. ~/.cs2tl/config.yml (default)
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LLMConfig(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    base_url: str | None = None
    model: str = "gpt-4o"

    @field_validator("api_key")
    @classmethod
    def api_key_must_not_be_empty_when_present(cls, v: str) -> str:
        # Empty string means "read from env var" — that's fine
        return v


class WhisperConfig(BaseModel):
    model: str = "base"
    device: str = "auto"

    @field_validator("model")
    @classmethod
    def valid_model_sizes(cls, v: str) -> str:
        valid = {"tiny", "base", "small", "medium", "large-v2", "large-v3"}
        if v not in valid:
            raise ValueError(f"Invalid Whisper model '{v}'. Must be one of: {', '.join(sorted(valid))}")
        return v


class DictionaryConfig(BaseModel):
    repo_url: str = "https://github.com/akiver/cs2-callout-dictionary"
    auto_update: bool = True
    local_path: str = ""  # set by resolve_paths()


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    dictionary: DictionaryConfig = Field(default_factory=DictionaryConfig)
    cache_dir: str = ""


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def default_config_path() -> Path:
    """Return ~/.cs2tl/config.yml."""
    return Path.home() / ".cs2tl" / "config.yml"


def project_config_path() -> Path:
    """Return ./.cs2tl.yml in the current directory."""
    return Path.cwd() / ".cs2tl.yml"


def default_cache_dir() -> Path:
    """Return ~/.cs2tl/cache/."""
    return Path.home() / ".cs2tl" / "cache"


def default_dictionary_dir() -> Path:
    """Return ~/.cs2tl/dictionaries/."""
    return Path.home() / ".cs2tl" / "dictionaries"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Config discovery + loading
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    """Load and safe-parse a YAML file."""
    if not path.exists():
        from cs2tl.errors import config_not_found
        raise config_not_found(str(path))
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        from cs2tl.errors import config_invalid_yaml
        raise config_invalid_yaml(str(path), str(e)) from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        from cs2tl.errors import config_invalid_yaml
        raise config_invalid_yaml(str(path), "Config must be a YAML mapping, not a scalar or list")
    return data


def _resolve_api_key(config: LLMConfig) -> LLMConfig:
    """Fill in api_key from environment variable if not set in config."""
    if config.api_key:
        return config
    env_key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("CS2TL_API_KEY", "")
    if env_key:
        config.api_key = env_key
    return config


def _check_permissions(path: Path) -> None:
    """Warn if config file has overly permissive permissions (Unix only)."""
    if not path.exists():
        return
    if sys.platform == "win32":
        # os.chmod is a no-op for this mask on Windows
        return
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            import warnings
            warnings.warn(
                f"Config file {path} is readable by others. "
                "Consider: chmod 600 {path}"
            )
    except OSError:
        pass


def resolve_paths(config: AppConfig) -> AppConfig:
    """Set derived paths (cache_dir, dictionary.local_path) if not overridden."""
    if not config.cache_dir:
        config.cache_dir = str(_ensure_dir(default_cache_dir()))
    if not config.dictionary.local_path:
        config.dictionary.local_path = str(_ensure_dir(default_dictionary_dir()))
    return config


def load_config(
    cli_config_path: Path | None = None,
    project_config: Path | None = None,
) -> AppConfig:
    """Load configuration following the 4-level precedence chain.

    Returns a fully resolved AppConfig (filled with defaults for missing fields).
    """
    raw: dict = {}

    # Level 4: ~/.cs2tl/config.yml (baseline)
    default_path = default_config_path()
    if default_path.exists():
        raw = _load_yaml(default_path)

    # Level 3: ./.cs2tl.yml (project-level override)
    proj_path = project_config or project_config_path()
    if proj_path.exists():
        proj_data = _load_yaml(proj_path)
        raw = _deep_merge(raw, proj_data)

    # Level 2: CS2TL_CONFIG env var
    env_path = os.environ.get("CS2TL_CONFIG", "")
    if env_path:
        env_p = Path(env_path)
        if env_p.exists():
            raw = _deep_merge(raw, _load_yaml(env_p))

    # Level 1: --config / -c CLI flag (highest priority)
    if cli_config_path and cli_config_path.exists():
        raw = _deep_merge(raw, _load_yaml(cli_config_path))

    # Build config with defaults for missing sections
    config = _build_config(raw)

    # Resolve API key from env if empty
    config.llm = _resolve_api_key(config.llm)

    # Set derived paths
    config = resolve_paths(config)

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base. override values win."""
    result = {**base}
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _build_config(raw: dict) -> AppConfig:
    """Build AppConfig from raw dict, applying defaults for missing sections."""
    return AppConfig(
        llm=LLMConfig(**(raw.get("llm", {}))),
        whisper=WhisperConfig(**(raw.get("whisper", {}))),
        dictionary=DictionaryConfig(**(raw.get("dictionaries", {}))),
        cache_dir=raw.get("cache_dir", ""),
    )


# ---------------------------------------------------------------------------
# Config writing (for `cs2tl config init`)
# ---------------------------------------------------------------------------

def write_default_config(path: Path, provider: str, api_key: str, model: str, whisper_model: str = "base") -> Path:
    """Write a minimal config file. Used by the interactive first-run wizard."""
    data = {
        "llm": {
            "provider": provider,
            "api_key": api_key,
            "model": model,
        },
        "whisper": {
            "model": whisper_model,
            "device": "auto",
        },
        "dictionaries": {
            "repo_url": "https://github.com/akiver/cs2-callout-dictionary",
            "auto_update": True,
        },
    }
    _ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    _check_permissions(path)
    return path
