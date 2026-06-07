"""Error taxonomy for cs2tl.

Every error raised by cs2tl uses the CS2tlError class with a unique
[CS2TL-E{X}-{NNNN}] code. The format is:

  [CS2TL-E{X}-{NNNN}] Human-readable message
  Cause: What triggered the error
  Fix: What the user should do

Error code ranges:
  E1 — Extractor (csgove subprocess, WAV files)
  E2 — Transcriber (faster-whisper)
  E3 — Dictionary (YAML, schema, git)
  E4 — Round detection (awpy)
  E5 — Translator (LLM API)
  E6 — Subtitles (SRT output, encoding)
  E7 — Config (file loading, validation)
  E8 — Clock (timestamp sync)
"""

from __future__ import annotations

import sys
from typing import NoReturn


class CS2tlError(Exception):
    """Structured error with code, problem, cause, and fix."""

    def __init__(self, code: str, message: str, cause: str, fix: str) -> None:
        self.code = code
        self.message = message
        self.cause = cause
        self.fix = fix
        super().__init__(self._format())

    def _format(self) -> str:
        return (
            f"[CS2TL-{self.code}] {self.message}\n"
            f"  Cause: {self.cause}\n"
            f"  Fix: {self.fix}"
        )


def exit_with_error(err: CS2tlError, exit_code: int = 1) -> NoReturn:
    """Print error to stderr and exit cleanly."""
    print(str(err), file=sys.stderr)
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# E1 — Extractor
# ---------------------------------------------------------------------------

def extractor_not_found(binary: str) -> CS2tlError:
    return CS2tlError(
        code="E1-0001",
        message=f"{binary} not found",
        cause=f"The csgo-voice-extractor binary ({binary}) is not installed or not on PATH.",
        fix=(
            "Download csgo-voice-extractor from "
            "https://github.com/akiver/csgo-voice-extractor/releases/latest "
            f"and ensure '{binary}' is on your PATH."
        ),
    )


def extractor_failed(demo_path: str, stderr: str) -> CS2tlError:
    return CS2tlError(
        code="E1-0002",
        message=f"csgove exited with an error processing {demo_path}",
        cause=f"Subprocess stderr:\n{stderr}",
        fix="Verify the demo file is not corrupted and is a valid Faceit/community server demo.",
    )


def no_voice_data(demo_path: str) -> CS2tlError:
    return CS2tlError(
        code="E1-0003",
        message=f"No voice audio found in {demo_path}",
        cause="No players used their microphones, or voice chat was disabled on this server.",
        fix="Try a different demo where players were actively communicating.",
    )


def opus_decoder_failed(detail: str) -> CS2tlError:
    return CS2tlError(
        code="E1-0004",
        message="Opus audio decoder initialization failed",
        cause=f"pyogg/libopus could not create a decoder: {detail}",
        fix="Verify that pyogg is correctly installed. On CPU-only machines, try: "
        "pip install --force-reinstall pyogg",
    )


# ---------------------------------------------------------------------------
# E2 — Transcriber
# ---------------------------------------------------------------------------

def whisper_model_download_failed(model: str, detail: str) -> CS2tlError:
    return CS2tlError(
        code="E2-0001",
        message=f"Failed to download Whisper model '{model}'",
        cause=f"Network or filesystem error: {detail}",
        fix="Check your internet connection. You can pre-download the model with: "
        "python -c 'from faster_whisper import WhisperModel; WhisperModel(\"base\", device=\"cpu\")'",
    )


def whisper_transcription_failed(wav_path: str, detail: str) -> CS2tlError:
    return CS2tlError(
        code="E2-0002",
        message=f"Whisper transcription failed for {wav_path}",
        cause=detail,
        fix="Verify the WAV file is not corrupted. Try a larger or smaller Whisper model.",
    )


# ---------------------------------------------------------------------------
# E3 — Dictionary
# ---------------------------------------------------------------------------

def dictionary_clone_failed(repo_url: str, detail: str) -> CS2tlError:
    return CS2tlError(
        code="E3-0001",
        message=f"Failed to clone dictionary repository from {repo_url}",
        cause=detail,
        fix="Check your internet connection and verify the repository URL. "
        "Use --no-dictionary to translate without a dictionary.",
    )


def dictionary_yaml_error(map_name: str, detail: str) -> CS2tlError:
    return CS2tlError(
        code="E3-0002",
        message=f"Invalid YAML in dictionary for {map_name}",
        cause=detail,
        fix="Check the zones.yml format. Expected: map name, version, terms list with aliases and chinese fields.",
    )


def invalid_map_name(map_name: str, valid_maps: list[str]) -> CS2tlError:
    return CS2tlError(
        code="E3-0003",
        message=f"Invalid map name: '{map_name}'",
        cause="The map name must be a known CS2 competitive map without path separators.",
        fix=f"Use one of: {', '.join(sorted(valid_maps))}",
    )


# ---------------------------------------------------------------------------
# E4 — Round Detection
# ---------------------------------------------------------------------------

def round_detection_failed(demo_path: str, detail: str) -> CS2tlError:
    return CS2tlError(
        code="E4-0001",
        message=f"Failed to detect rounds in {demo_path}",
        cause=detail,
        fix="The demo may be from an unsupported version. Translation will continue "
        "with round_number=null. Manually specify --map if auto-detection also failed.",
    )


# ---------------------------------------------------------------------------
# E5 — Translator
# ---------------------------------------------------------------------------

def llm_auth_failed(detail: str) -> CS2tlError:
    return CS2tlError(
        code="E5-0001",
        message="LLM API authentication failed",
        cause=f"API key is invalid or expired: {detail}",
        fix="Run 'cs2tl config init' to reconfigure your API key, or set the OPENAI_API_KEY environment variable.",
    )


def llm_rate_limited(retry_after: str | None = None) -> CS2tlError:
    return CS2tlError(
        code="E5-0002",
        message="LLM API rate limit exceeded",
        cause="Too many requests sent to the API in a short period.",
        fix=f"Wait before retrying. {f'Retry after: {retry_after}s' if retry_after else ''} "
        "Consider using a model with higher rate limits.",
    )


def llm_response_malformed(detail: str) -> CS2tlError:
    return CS2tlError(
        code="E5-0003",
        message="LLM returned a malformed response",
        cause=detail,
        fix="The model may have hallucinated the output format. Re-running the round may produce a valid response. "
        "If this persists, try a different model.",
    )


# ---------------------------------------------------------------------------
# E6 — Subtitles
# ---------------------------------------------------------------------------

def subtitle_write_failed(output_path: str, detail: str) -> CS2tlError:
    return CS2tlError(
        code="E6-0001",
        message=f"Failed to write SRT file: {output_path}",
        cause=detail,
        fix="Check disk space and write permissions for the output directory.",
    )


def subtitle_encoding_failed(char: str) -> CS2tlError:
    return CS2tlError(
        code="E6-0002",
        message=f"Failed to encode character in SRT output: U+{ord(char):04X}",
        cause="The translation contains characters incompatible with the selected encoding.",
        fix="Use --encoding utf-8 or --encoding utf-8-bom for full Unicode support.",
    )


# ---------------------------------------------------------------------------
# E7 — Config
# ---------------------------------------------------------------------------

def config_not_found(path: str) -> CS2tlError:
    return CS2tlError(
        code="E7-0001",
        message=f"Config file not found: {path}",
        cause="First run: no configuration has been created yet.",
        fix="Run 'cs2tl config init' to create your configuration interactively.",
    )


def config_invalid_yaml(path: str, detail: str) -> CS2tlError:
    return CS2tlError(
        code="E7-0002",
        message=f"Config file is invalid YAML: {path}",
        cause=detail,
        fix="Fix the YAML syntax in your config file, or run 'cs2tl config init' to recreate it.",
    )


def config_missing_key(path: str, key: str) -> CS2tlError:
    return CS2tlError(
        code="E7-0003",
        message=f"Required configuration key missing: {key}",
        cause=f"Config file {path} is missing the '{key}' field.",
        fix="Add the missing field to your config file, or run 'cs2tl config init' to recreate it.",
    )


# ---------------------------------------------------------------------------
# E8 — Clock
# ---------------------------------------------------------------------------

def clock_sync_warning(offset: float) -> str:
    """Returns a warning string (not an error) for moderate clock drift."""
    return (
        f"Clock drift detected: {offset:.2f}s offset between voice extractor "
        f"and round parser timestamps. Round assignments may be slightly misaligned."
    )


def clock_sync_overflow(offset: float, tolerance: float) -> CS2tlError:
    return CS2tlError(
        code="E8-0001",
        message=f"Excessive clock drift: {offset:.2f}s exceeds tolerance of {tolerance:.1f}s",
        cause="The voice extractor and round parser disagree significantly on demo timing. "
        "This may indicate incompatible parser versions or a corrupted demo.",
        fix="Verify that csgo-voice-extractor and awpy are compatible with the current CS2 version. "
        "Try a different demo to confirm the issue is not demo-specific.",
    )
