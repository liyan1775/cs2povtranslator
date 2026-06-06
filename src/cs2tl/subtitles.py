"""SRT subtitle file generation.

Converts TranslationSegments into per-team SRT subtitle files
with the "player_name: translated_text" format.

Key P1 constraints:
  - P1-12: Player name prefix enforced in every SRT entry
  - Team grouping with empty-team fallback
  - UTF-8 encoding (with optional BOM for Chinese video editors)
"""

from __future__ import annotations

import logging
from pathlib import Path

from cs2tl.errors import subtitle_write_failed

logger = logging.getLogger(__name__)


def write_srt(
    segments: list,  # TranslationSegment
    output_dir: Path,
    demo_name: str,
    encoding: str = "utf-8",
) -> dict[str, Path]:
    """Generate per-team SRT files from translated segments.

    Args:
        segments: TranslationSegment list.
        output_dir: Output directory for SRT files.
        demo_name: Base name for generated SRT files (without extension).
        encoding: Output encoding. "utf-8" or "utf-8-bom" for Chinese editors.

    Returns:
        Mapping: team label -> path to generated SRT.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group by team
    by_team: dict[str, list] = {}
    for seg in segments:
        team = getattr(seg, "team", "unknown")
        by_team.setdefault(team, []).append(seg)

    # Sort each team's segments by start_time
    for team_segs in by_team.values():
        team_segs.sort(key=lambda s: getattr(s, "start_time", 0.0))

    result: dict[str, Path] = {}
    for team in sorted(by_team.keys()):
        team_segs = by_team[team]
        team_safe = team.replace(" ", "_")
        output_path = output_dir / f"{demo_name}.team_{team_safe}.srt"
        _write_one_srt(output_path, team_segs, encoding)
        result[team] = output_path
        logger.info("Wrote %s: %d entries", output_path.name, len(team_segs))

    return result


def _write_one_srt(path: Path, segments: list, encoding: str) -> None:
    """Write a single SRT file for one team."""
    try:
        content = _build_srt_content(segments)
        if encoding == "utf-8-bom":
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(content)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
    except OSError as e:
        raise subtitle_write_failed(str(path), str(e)) from e


def _build_srt_content(segments: list) -> str:
    """Build the full SRT content string from segments."""
    if not segments:
        # Empty team — produce a single placeholder entry
        return "1\n00:00:00,000 --> 00:00:01,000\n无语音通讯\n\n"

    entries: list[str] = []
    for i, seg in enumerate(segments, start=1):
        player_name = getattr(seg, "player_name", "unknown")
        start = getattr(seg, "start_time", 0.0)
        end = getattr(seg, "end_time", start + 1.0)
        text = getattr(seg, "translated_text", "") or getattr(seg, "original_text", "")

        entry = format_srt_entry(i, start, end, player_name, text)
        if entry:
            entries.append(entry)

    return "\n".join(entries) + "\n\n" if entries else "1\n00:00:00,000 --> 00:00:01,000\n无语音通讯\n\n"


def format_srt_timestamp(seconds: float) -> str:
    """Convert float seconds to SRT timestamp format: HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    whole_secs = int(secs)
    millis = int((secs - whole_secs) * 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_secs:02d},{millis:03d}"


def format_srt_entry(
    index: int,
    start_seconds: float,
    end_seconds: float,
    player_name: str,
    text: str,
) -> str:
    """Format a single SRT subtitle entry.

    Output format:
        1
        00:00:01,500 --> 00:00:03,200
        donk: 我来架A小

    Args:
        index: 1-based subtitle index.
        start_seconds: Start time in seconds.
        end_seconds: End time in seconds.
        player_name: Player's in-game name (prefixed before text).
        text: Translated subtitle text.

    Returns:
        Formatted SRT entry block.
    """
    start_ts = format_srt_timestamp(start_seconds)
    end_ts = format_srt_timestamp(end_seconds)
    return f"{index}\n{start_ts} --> {end_ts}\n{player_name}: {text}\n"
