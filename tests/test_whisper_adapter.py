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


def test_adapter_without_cache_keeps_kwargs_and_reports_import_error(monkeypatch):
    import builtins
    real = builtins.__import__
    def fail(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("missing")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fail)
    from cs2pov.adapters.whisper_adapter import FasterWhisperAdapter, WhisperAdapterError
    try:
        FasterWhisperAdapter(cache_dir=None)
    except WhisperAdapterError as exc:
        assert "faster-whisper" in str(exc)
