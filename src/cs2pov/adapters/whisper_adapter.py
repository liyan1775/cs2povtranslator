from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class WhisperAdapterError(RuntimeError):
    pass


class FasterWhisperAdapter:
    def __init__(
        self,
        model_name: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "auto",
        vad_filter: bool = True,
        cache_dir: str | None = None,
    ):
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise WhisperAdapterError("缺少 faster-whisper。请运行：pip install faster-whisper") from exc
        self.model_name = model_name
        self.language = None if language == "auto" else language
        self.vad_filter = bool(vad_filter)
        kwargs = {"device": device, "compute_type": compute_type}
        if cache_dir:
            cache_root = Path(cache_dir).expanduser()
            cache_root.mkdir(parents=True, exist_ok=True)
            # Project-level cache: keep models off C: without changing the user's
            # global environment.  Setting HF_HOME helps downstream Hugging Face
            # calls, while download_root directs faster-whisper itself.
            os.environ.setdefault("HF_HOME", str(cache_root))
            kwargs["download_root"] = str(cache_root)
        self.model = WhisperModel(model_name, **kwargs)

    def transcribe(self, wav_path: Path) -> list[dict[str, Any]]:
        # v0.1.4 defaults VAD on after real-demo feedback showed better coverage
        # for tiny on CS2 compact voice. The CLI still exposes --no-whisper-vad
        # because ASR behavior depends on model, language mix and audio quality.
        segments, info = self.model.transcribe(str(wav_path), language=self.language, vad_filter=self.vad_filter)
        language = getattr(info, "language", None)
        out: list[dict[str, Any]] = []
        for seg in segments:
            text = str(getattr(seg, "text", "")).strip()
            if not text:
                continue
            out.append({
                "start": float(getattr(seg, "start")),
                "end": float(getattr(seg, "end")),
                "text": text,
                "language": language,
                "confidence": None,
            })
        return out
