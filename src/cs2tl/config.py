"""Configuration loading and validation.

Config resolution precedence:
  1. --config / -c CLI flag
  2. CS2TL_CONFIG environment variable
  3. ./.cs2tl.yml (project-local, current directory)
  4. ~/.cs2tl/config.yml (default)

Data directory resolution precedence:
  1. CS2TL_DATA_DIR environment variable
  2. ./cs2tl-data/ (project root)
  3. ~/.cs2tl/ (fallback)
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


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

def _find_project_root() -> Path:
    """Walk up from this source file's location to find the project root.

    Looks for the first parent directory containing either ``.git/`` or
    ``pyproject.toml``.  When running from a pip-installed wheel (site-packages
    contains no .git), falls back to ``os.getcwd()``.
    """
    start = Path(__file__).resolve().parent
    for ancestor in [start, *start.parents]:
        if (ancestor / ".git").exists() or (ancestor / "pyproject.toml").exists():
            return ancestor
    # Fallback: running from a pip-installed wheel
    return Path.cwd()


def default_data_dir() -> Path:
    """Return the preferred data directory (``{project_root}/cs2tl-data/``).

    The directory is *not* created here — callers should mkdir when needed.
    """
    env_dir = os.environ.get("CS2TL_DATA_DIR", "")
    if env_dir:
        return Path(env_dir)
    return _find_project_root() / "cs2tl-data"


def _legacy_home_dir() -> Path:
    """Return the legacy home directory path (~/.cs2tl/)."""
    return Path.home() / ".cs2tl"


def default_config_path() -> Path:
    """Return ~/.cs2tl/config.yml."""
    return _legacy_home_dir() / "config.yml"


def project_config_path() -> Path:
    """Return ./.cs2tl.yml in the current directory."""
    return Path.cwd() / ".cs2tl.yml"


def default_cache_dir() -> Path:
    """Return the cache directory under the resolved data dir.

    Prefers ``cs2tl-data/cache/`` → falls back to ``~/.cs2tl/cache/``.
    """
    data_dir = default_data_dir()
    # If the env var is set or the project root has a cs2tl-data dir, use it
    if os.environ.get("CS2TL_DATA_DIR") or (data_dir.parent / ".git").exists():
        return data_dir / "cache"
    # Fallback: use legacy home path
    return _legacy_home_dir() / "cache"


def default_dictionary_dir() -> Path:
    """Return the dictionary directory under the resolved data dir.

    Prefers ``cs2tl-data/dictionaries/`` → falls back to ``~/.cs2tl/dictionaries/``.
    """
    return default_data_dir() / "dictionaries"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Data migration (legacy ~/.cs2tl/ → cs2tl-data/)
# ---------------------------------------------------------------------------

def migrate_old_data(interactive: bool = True) -> bool:
    """Copy-then-verify migration from legacy ``~/.cs2tl/`` to ``cs2tl-data/``.

    Steps:
      1. Detect if ``~/.cs2tl/cache/`` has data.
      2. Prompt in interactive mode, auto-migrate in non-interactive mode.
      3. Copy files → verify count + sizes → delete source on success.
      4. Rollback on failure (delete partial copies, keep source).

    Returns:
        True if migration was performed, False if nothing to migrate.
    """
    legacy_dir = _legacy_home_dir()
    legacy_cache = legacy_dir / "cache"
    if not legacy_cache.exists() or not any(legacy_cache.iterdir()):
        return False

    target_dir = default_data_dir()
    target_cache = target_dir / "cache"

    # Already migrated?
    if target_cache.exists() and any(target_cache.iterdir()):
        logger.info("Target cache already has data, skipping migration.")
        return False

    if interactive:
        try:
            answer = input(
                f"\n检测到旧缓存 {legacy_cache}，迁移到 {target_cache}？[Y/n] "
            ).strip().lower()
            if answer and answer != "y":
                print("跳过迁移。旧缓存保留在 ~/.cs2tl/ 中。")
                return False
        except (EOFError, KeyboardInterrupt):
            print("\n跳过迁移。")
            return False

    print(f"正在迁移缓存数据: {legacy_cache} → {target_cache}")
    logger.info("Migrating data from %s to %s", legacy_cache, target_cache)

    # Collect source files
    src_files: list[tuple[Path, Path]] = []
    for root, _dirs, files in os.walk(legacy_cache):
        root_path = Path(root)
        for fname in files:
            src = root_path / fname
            rel = src.relative_to(legacy_cache)
            dst = target_cache / rel
            src_files.append((src, dst))

    if not src_files:
        return False

    # copy-then-verify
    target_cache.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    try:
        for src, dst in src_files:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(dst)

        # Verify: file count and total size match
        src_total = sum(f[0].stat().st_size for f in src_files)
        dst_total = sum(c.stat().st_size for c in copied)
        if len(copied) != len(src_files) or dst_total != src_total:
            raise RuntimeError(
                f"验证失败: 源文件 {len(src_files)} 个 ({src_total} bytes), "
                f"目标文件 {len(copied)} 个 ({dst_total} bytes)"
            )

        # Success — remove legacy cache
        shutil.rmtree(legacy_cache, ignore_errors=True)
        print(f"✅ 迁移完成: {len(copied)} 个文件已移至 {target_cache}")
        logger.info("Migration complete: %d files", len(copied))
        return True

    except Exception as e:
        # Rollback: delete partially copied files
        logger.warning("Migration failed, rolling back: %s", e)
        for dst in copied:
            try:
                dst.unlink()
            except OSError:
                pass
        # Remove empty directories in target_cache
        try:
            shutil.rmtree(target_cache, ignore_errors=True)
        except OSError:
            pass
        print(f"⚠️ 迁移失败: {e}。旧缓存保留在 {legacy_cache} 中。")
        return False


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
    """Set derived paths (cache_dir, dictionary.local_path) if not overridden.

    Priority chain for data directory:
      1. CS2TL_DATA_DIR environment variable
      2. ./cs2tl-data/ (project root)
      3. ~/.cs2tl/ (fallback)
    """
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
