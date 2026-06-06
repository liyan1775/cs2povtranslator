"""Shared test fixtures for cs2tl."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml


@pytest.fixture
def tmp_dir():
    """Temporary directory that cleans up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_config_yml(tmp_dir: Path) -> Path:
    """Write a minimal valid config YAML to a temp file."""
    data = {
        "llm": {
            "provider": "openai",
            "api_key": "sk-test1234",
            "model": "gpt-4o",
        },
        "whisper": {
            "model": "base",
            "device": "cpu",
        },
        "dictionaries": {
            "repo_url": "https://github.com/test/cs2-callout-dictionary",
            "auto_update": False,
        },
    }
    path = tmp_dir / "config.yml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def sample_dust2_zones_yml(tmp_dir: Path) -> Path:
    """Write a valid de_dust2 zones.yml to a temp directory."""
    map_dir = tmp_dir / "de_dust2"
    map_dir.mkdir(parents=True)
    data = {
        "map": "de_dust2",
        "version": "1.0.0",
        "terms": [
            {
                "aliases": ["A short", "A ramp", "catwalk", "cat"],
                "chinese": "A小道",
                "category": "zone",
            },
            {
                "aliases": ["A long", "long A", "pit"],
                "chinese": "A大道",
                "category": "zone",
            },
            {
                "aliases": ["B site", "B bombsite", "B"],
                "chinese": "B包点",
                "category": "bombsite",
            },
            {"aliases": ["mid", "middle"], "chinese": "中路", "category": "zone"},
            {"aliases": ["CT spawn", "CT base"], "chinese": "CT家", "category": "spawn"},
        ],
    }
    path = map_dir / "zones.yml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def partial_segments():
    """A list of PartialSegment dicts for testing the translation pipeline."""
    return [
        {
            "steam_id": "76561198000000001",
            "start_time": 10.0,
            "end_time": 12.5,
            "text": "I'm holding cat from mid.",
            "confidence": 0.95,
            "round_number": 3,
        },
        {
            "steam_id": "76561198000000001",
            "start_time": 15.0,
            "end_time": 16.0,
            "text": "One smoke A long!",
            "confidence": 0.87,
            "round_number": 3,
        },
        {
            "steam_id": "76561198000000002",
            "start_time": 20.0,
            "end_time": 21.5,
            "text": "Rush B!",
            "confidence": 0.92,
            "round_number": 4,
        },
    ]


@pytest.fixture
def player_infos():
    """A dict mapping steam_id to PlayerInfo-like dicts."""
    return {
        "76561198000000001": {"steam_id": "76561198000000001", "player_name": "donk", "team": "T"},
        "76561198000000002": {"steam_id": "76561198000000002", "player_name": "s1mple", "team": "CT"},
    }


@pytest.fixture
def transcribed_jsonl(tmp_path, partial_segments):
    """Write a demo.transcribed.jsonl fixture file."""
    path = tmp_path / "demo.transcribed.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for seg in partial_segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def translated_jsonl(tmp_path):
    """Write a demo.translated.jsonl fixture file."""
    segments = [
        {
            "steam_id": "76561198000000001",
            "player_name": "donk",
            "team": "T",
            "start_time": 10.0,
            "end_time": 12.5,
            "original_text": "I'm holding cat from mid.",
            "translated_text": "我在中路架A小",
            "round_number": 3,
            "warnings": [],
        },
        {
            "steam_id": "76561198000000001",
            "player_name": "donk",
            "team": "T",
            "start_time": 15.0,
            "end_time": 16.0,
            "original_text": "One smoke A long!",
            "translated_text": "A大打了一颗烟！",
            "round_number": 3,
            "warnings": [],
        },
        {
            "steam_id": "76561198000000002",
            "player_name": "s1mple",
            "team": "CT",
            "start_time": 20.0,
            "end_time": 21.5,
            "original_text": "Rush B!",
            "translated_text": "冲B了！",
            "round_number": 4,
            "warnings": [],
        },
    ]
    path = tmp_path / "demo.translated.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    return path
