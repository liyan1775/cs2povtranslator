"""Speech-to-text transcription via faster-whisper.

Transcribes per-player WAV files into PartialSegment records.
Implements incremental JSONL caching for crash-resilience.

Key P1 constraints:
  - Model download error handling (E2-0001)
  - Transcription failure per WAV (E2-0002)
  - Cache bypass when WAVs are newer than cache
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from cs2tl.errors import (
    whisper_model_download_failed,
    whisper_transcription_failed,
)

logger = logging.getLogger(__name__)


@dataclass
class PartialSegment:
    """A transcribed voice segment (before translation)."""

    steam_id: str
    start_time: float  # seconds from demo start
    end_time: float
    text: str
    confidence: float


def transcribe_all(
    wav_files: dict[str, Path],
    model_name: str = "base",
    device: str = "auto",
    cache_path: Path | None = None,
) -> list[PartialSegment]:
    """Transcribe all WAV files using faster-whisper.

    Args:
        wav_files: Map of steam_id -> WAV path.
        model_name: Whisper model size (tiny/base/small/medium/large-v3).
        device: "auto", "cpu", or "cuda".
        cache_path: Path to demo.transcribed.jsonl for cache read/write.

    Returns:
        List of PartialSegment with transcription results.
    """
    # --- Cache check ---
    if cache_path and cache_path.exists():
        newest_wav_mtime = max(
            (p.stat().st_mtime for p in wav_files.values() if p.exists()),
            default=0,
        )
        if cache_path.stat().st_mtime >= newest_wav_mtime:
            logger.info("Transcription cache hit: %s", cache_path)
            return load_cached_transcript(cache_path)

    # --- Load Whisper model ---
    model = _load_model(model_name, device)

    segments: list[PartialSegment] = []
    total = len(wav_files)

    for i, (steam_id, wav_path) in enumerate(sorted(wav_files.items())):
        logger.info("Transcribing [%d/%d] %s ...", i + 1, total, wav_path.name)
        try:
            file_segments = _transcribe_one(model, steam_id, wav_path)
            segments.extend(file_segments)
            logger.info(
                "  → %d segments, avg confidence %.2f",
                len(file_segments),
                sum(s.confidence for s in file_segments) / max(len(file_segments), 1),
            )
        except Exception as e:
            raise whisper_transcription_failed(str(wav_path), str(e)) from e

        # Write incrementally (one line per segment, append-only)
        if cache_path:
            _append_to_cache(cache_path, file_segments)

    logger.info("Transcription complete: %d segments from %d files", len(segments), total)
    return segments


def _load_model(model_name: str, device: str):
    """Load the faster-whisper model. Maps 'auto' device to 'cpu' on Windows if CUDA not detected."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise whisper_model_download_failed(
            model_name, "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from e

    # Resolve device
    resolved_device = _resolve_device(device)

    try:
        model = WhisperModel(model_name, device=resolved_device, compute_type="int8")
        logger.info("Whisper model '%s' loaded on %s", model_name, resolved_device)
        return model
    except Exception as e:
        raise whisper_model_download_failed(model_name, str(e)) from e


def _resolve_device(device: str) -> str:
    """Resolve 'auto' to the best available device."""
    if device != "auto":
        return device
    import sys
    if sys.platform == "win32":
        # Check for CUDA
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"
    return "cpu"


def _transcribe_one(model, steam_id: str, wav_path: Path) -> list[PartialSegment]:
    """Transcribe a single WAV file."""
    segments_out, info = model.transcribe(
        str(wav_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )

    result: list[PartialSegment] = []
    for segment in segments_out:
        if segment.text.strip():  # skip truly empty results
            result.append(
                PartialSegment(
                    steam_id=steam_id,
                    start_time=round(segment.start, 3),
                    end_time=round(segment.end, 3),
                    text=segment.text.strip(),
                    confidence=round(segment.avg_logprob, 3),
                )
            )
    return result


def load_cached_transcript(cache_path: Path) -> list[PartialSegment]:
    """Read demo.transcribed.jsonl back into PartialSegment list."""
    segments: list[PartialSegment] = []
    with open(cache_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            segments.append(
                PartialSegment(
                    steam_id=data["steam_id"],
                    start_time=data["start_time"],
                    end_time=data["end_time"],
                    text=data["text"],
                    confidence=data["confidence"],
                )
            )
    return segments


def _append_to_cache(cache_path: Path, segments: list[PartialSegment]) -> None:
    """Append segments to the JSONL cache file (one JSON object per line)."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "a", encoding="utf-8") as f:
        for seg in segments:
            f.write(
                json.dumps(
                    {
                        "steam_id": seg.steam_id,
                        "start_time": seg.start_time,
                        "end_time": seg.end_time,
                        "text": seg.text,
                        "confidence": seg.confidence,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
