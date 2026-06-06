"""Tests for transcriber module."""

from __future__ import annotations

import json
from pathlib import Path

from cs2tl.transcriber import (
    PartialSegment,
    _resolve_device,
    load_cached_transcript,
)


class TestPartialSegment:
    def test_create_and_serialize(self):
        seg = PartialSegment(
            steam_id="76561198000000001",
            start_time=10.0,
            end_time=12.5,
            text="I'm holding cat from mid",
            confidence=0.95,
        )
        data = {
            "steam_id": seg.steam_id,
            "start_time": seg.start_time,
            "end_time": seg.end_time,
            "text": seg.text,
            "confidence": seg.confidence,
        }
        assert data["text"] == "I'm holding cat from mid"


class TestCache:
    def test_load_cached_transcript(self, tmp_path):
        cache = tmp_path / "demo.transcribed.jsonl"
        segments = [
            {"steam_id": "sid1", "start_time": 1.0, "end_time": 2.0, "text": "hello", "confidence": 0.9},
            {"steam_id": "sid1", "start_time": 3.0, "end_time": 4.0, "text": "world", "confidence": 0.85},
        ]
        with open(cache, "w", encoding="utf-8") as f:
            for s in segments:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        loaded = load_cached_transcript(cache)
        assert len(loaded) == 2
        assert loaded[0].steam_id == "sid1"
        assert loaded[0].text == "hello"

    def test_load_cached_transcript_skips_empty_lines(self, tmp_path):
        cache = tmp_path / "demo.transcribed.jsonl"
        with open(cache, "w", encoding="utf-8") as f:
            f.write('\n{"steam_id":"sid1","start_time":0,"end_time":1,"text":"x","confidence":0.5}\n\n')
        loaded = load_cached_transcript(cache)
        assert len(loaded) == 1


class TestResolveDevice:
    def test_returns_explicit_device(self):
        assert _resolve_device("cpu") == "cpu"
        assert _resolve_device("cuda") == "cuda"

    def test_auto_on_windows_without_cuda_defaults_to_cpu(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "win32")
        result = _resolve_device("auto")
        assert result == "cpu"
