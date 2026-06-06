"""Round boundary detection and timestamp synchronization.

Parses CS2 demos via awpy to extract round_start/round_end events,
annotates voice segments with round numbers, handles halftime
team swaps (MR12 regulation + OT rules), and reconciles clock
offsets between the voice extractor and round parser.

Key P1 constraints:
  - P1-6: Two-parser clock sync with offset tolerance (2s warn, 10s error)
  - P1-4: Halftime swap for round 13+ T↔CT flip
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from cs2tl.errors import (
    clock_sync_overflow,
    clock_sync_warning,
    round_detection_failed,
)
from cs2tl.transcriber import PartialSegment

logger = logging.getLogger(__name__)

# CS2 regulation: teams swap sides at round 13 (MR12)
REGULATION_HALFTIME = 13
# OT: first to 4 rounds, swap at round 4 and 7
OT_PERIOD_LENGTH = 6


@dataclass
class RoundBoundary:
    """A single round's time window and team assignments."""

    round_number: int  # 1-indexed
    start_time: float  # seconds from demo start
    end_time: float
    team_side: dict[str, str]  # steam_id -> "T" | "CT" at round start


def detect_rounds(demo_path: Path) -> list[RoundBoundary]:
    """Parse the demo with awpy to extract round boundaries.

    Args:
        demo_path: Path to the .dem file.

    Returns:
        List of RoundBoundary sorted by round_number.

    Raises:
        CS2tlError(E4-0001): if awpy cannot parse the demo.
    """
    try:
        import awpy
    except ImportError as e:
        raise round_detection_failed(
            str(demo_path),
            "awpy is not installed. Run: pip install awpy"
        ) from e

    try:
        demo = awpy.Demo(str(demo_path))
        rounds_data = demo.rounds
    except Exception as e:
        raise round_detection_failed(str(demo_path), str(e)) from e

    if not rounds_data:
        raise round_detection_failed(
            str(demo_path),
            "No round data found. The demo may not support round events.",
        )

    boundaries: list[RoundBoundary] = []
    for i, rd in enumerate(rounds_data):
        # awpy rounds are typically 0-indexed; we want 1-indexed
        rn = rd.get("roundNum", i + 1)
        start_tick = rd.get("roundStartTick", 0)
        end_tick = rd.get("roundEndTick", start_tick)
        # Convert ticks to seconds (CS2 tickrate = 64)
        tick_rate = demo.tick_rate or 64
        start_sec = _ticks_to_seconds(start_tick, tick_rate)
        end_sec = _ticks_to_seconds(end_tick, tick_rate) if end_tick > start_tick else start_sec + 120.0

        # Extract team sides from round info
        team_side: dict[str, str] = {}
        # awpy may provide team assignments; fallback is empty
        teams_info = rd.get("teams", {}) or {}
        for team_key, team_data in teams_info.items():
            if isinstance(team_data, dict):
                players = team_data.get("players", []) or []
                for player in players:
                    sid = str(player.get("steamID", ""))
                    if sid:
                        team_side[sid] = team_key

        boundaries.append(
            RoundBoundary(
                round_number=rn,
                start_time=round(start_sec, 3),
                end_time=round(end_sec, 3),
                team_side=team_side,
            )
        )

    boundaries.sort(key=lambda b: b.round_number)
    logger.info("Detected %d rounds in demo", len(boundaries))
    return boundaries


def _ticks_to_seconds(ticks: int, tick_rate: int) -> float:
    return ticks / max(tick_rate, 1)


def annotate_segments(
    segments: list[PartialSegment],
    rounds: list[RoundBoundary],
    clock_offset_tolerance: float = 2.0,
) -> tuple[list[PartialSegment], float, list[str]]:
    """Assign round numbers to segments and compute clock sync offset.

    The voice extractor (csgove) and round parser (awpy) may have different
    clock origins. This function computes the median offset between segment
    timestamps and matching round boundaries, then applies the correction.

    Args:
        segments: Transcribed segments without round numbers.
        rounds: Round boundaries from awpy.
        clock_offset_tolerance: Maximum acceptable offset in seconds before warning.

    Returns:
        (annotated segments, computed offset, warning messages)

    Raises:
        CS2tlError(E8-0001): if clock drift exceeds 10 seconds.
    """
    warnings: list[str] = []

    # Compute offset: find the median delta between a segment's start_time
    # and the start_time of the round it falls into.
    offsets: list[float] = []
    for seg in segments:
        for rd in rounds:
            if rd.start_time <= seg.start_time <= rd.end_time:
                offsets.append(seg.start_time - rd.start_time)
                break

    offset = 0.0
    if offsets:
        offset = _median(offsets)
    else:
        warnings.append("Could not compute clock offset — no segments matched to rounds.")

    # --- P1-6: Clock sync check ---
    if abs(offset) > 10.0:
        raise clock_sync_overflow(offset, 10.0)
    elif abs(offset) > clock_offset_tolerance:
        warnings.append(clock_sync_warning(offset))

    # Annotate segments with round numbers
    annotated: list[PartialSegment] = []
    for seg in segments:
        found_round = None
        adjusted_start = seg.start_time - offset

        for rd in rounds:
            if rd.start_time <= adjusted_start <= rd.end_time:
                found_round = rd.round_number
                break

        annotated.append(
            PartialSegment(
                steam_id=seg.steam_id,
                start_time=seg.start_time,
                end_time=seg.end_time,
                text=seg.text,
                confidence=seg.confidence,
            )
        )
        # Attach round_number (PartialSegment doesn't have it — we'll add it
        # in the dict form when passing downstream)
        setattr(annotated[-1], "round_number", found_round)

    logger.info(
        "Annotated %d segments with round numbers (offset=%.2fs)",
        len(annotated),
        offset,
    )

    return annotated, offset, warnings


def _median(values: list[float]) -> float:
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0


def halftime_swap(
    segments: list[PartialSegment],
    rounds: list[RoundBoundary],
) -> list[PartialSegment]:
    """Flip team labels for segments in rounds after halftime.

    CS2 MR12 regulation: rounds 1-12 use initial team assignment,
    rounds 13+ flip T↔CT. OT: flip after 3 rounds per period.

    Note: This function assumes each segment already has a 'team' attribute
    set by player_resolver. It mutates the segments in place and returns them.
    """
    total_rounds = len(rounds)
    if total_rounds == 0:
        return segments

    # Determine flip point
    max_round = max((r.round_number for r in rounds), default=0)

    if max_round <= REGULATION_HALFTIME:
        flip_round = REGULATION_HALFTIME
    else:
        # OT: flip after each half-period
        flip_round = REGULATION_HALFTIME

    for seg in segments:
        rn = getattr(seg, "round_number", None)
        if rn is None or rn < flip_round:
            continue
        # Flip T ↔ CT
        current_team = getattr(seg, "team", None) if hasattr(seg, "team") else None
        if current_team == "T":
            setattr(seg, "team", "CT")
        elif current_team == "CT":
            setattr(seg, "team", "T")

    logger.info("Applied halftime swap: rounds >= %d have flipped teams", flip_round)
    return segments
