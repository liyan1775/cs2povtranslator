import os
import sys
from pathlib import Path


def test_faster_whisper_adapter_never_mutates_environment(monkeypatch, tmp_path):
    captured = {}
    class Fake:
        def __init__(self, name, **kwargs): captured.update(kwargs)
    monkeypatch.setitem(sys.modules, "faster_whisper", type("M", (), {"WhisperModel": Fake}))
    from cs2pov.adapters.whisper_adapter import FasterWhisperAdapter
    before = dict(os.environ)
    FasterWhisperAdapter(cache_dir=str(tmp_path))
    assert dict(os.environ) == before
    assert captured["download_root"] == str(tmp_path)
