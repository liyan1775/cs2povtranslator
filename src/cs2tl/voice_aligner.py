"""Voice timestamp alignment using demoparser2 voice packet ticks.

csgove's split-compact mode compresses each player's voice by removing
silence, which loses the real demo timeline.  This module reads the
original voice-packet ticks from the demo via demoparser2 and maps
them back onto the transcribed segments so SRT timestamps span the
full match duration instead of being crammed into 2-3 minutes.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Consecutive voice packets closer than this (seconds) are treated as
# one continuous utterance.
UTTERANCE_GAP_THRESHOLD = 0.5


def align_segments(
    segments: list,       # PartialSegment
    demo_path: Path,
) -> list:
    """Replace compacted-WAV timestamps with real demo timestamps.

    Algorithm
    ---------
    1.  Decompress .dem.zst → temp .dem (if needed).
    2.  Parse every voice packet via ``demoparser2.parse_voice()``.
    3.  Group packets by steam-id, merge consecutive packets that are
        within *UTTERANCE_GAP_THRESHOLD* into utterances.
    4.  Sort the transcribed *segments* by (steam_id, start_time) so
        the compacted order is preserved.
    5.  Walk through the segments per player and assign each segment
        the timestamp of the next available utterance.
    6.  If segments outnumber utterances (rare), the last utterance's
        timestamp is reused for the remaining segments.

    Returns
    -------
    The same list of segments with ``start_time`` and ``end_time``
    updated in-place.  Segments whose steam-id has no voice packets
    are left untouched.
    """
    # 1. Decompress .zst if needed
    tmp_dem: Path | None = None
    actual_demo = demo_path
    try:
        if demo_path.suffix == ".zst":
            import zstandard as zstd
            with open(demo_path, "rb") as f:
                compressed = f.read()
            dctx = zstd.ZstdDecompressor()
            decompressed = dctx.decompress(compressed)
            fd, tmp = tempfile.mkstemp(suffix=".dem",
                                       prefix=demo_path.stem + "_")
            with os.fdopen(fd, "wb") as f:
                f.write(decompressed)
            actual_demo = Path(tmp)
            tmp_dem = actual_demo
            logger.debug("Aligner: decompressed %s → %s",
                         demo_path.name, actual_demo.name)

        # 2. Parse voice packets
        from demoparser2 import DemoParser
        parser = DemoParser(str(actual_demo))
        voice_data = parser.parse_voice()
        # CS2 competitive / Faceit always uses 64 tick
        tick_rate = 64.0
        logger.info("Aligner: %d voice packets, tick_rate=%.0f",
                    len(voice_data), tick_rate)

        # 3. Build per-player utterance list
        #    raw_ticks: {steam_id: [tick_seconds_sorted]}
        raw_ticks: dict[str, list[float]] = {}
        for pkt in voice_data:
            sid = str(int(pkt["steamid"]))
            if len(sid) == 17 and sid.startswith("7656"):
                t = pkt["tick"] / tick_rate
                raw_ticks.setdefault(sid, []).append(t)

        # Merge consecutive packets into utterances
        utterances: dict[str, list[tuple[float, float]]] = {}
        for sid, ticks in raw_ticks.items():
            ticks.sort()
            merged: list[tuple[float, float]] = []
            utt_start = ticks[0]
            utt_end = ticks[0]
            for t in ticks[1:]:
                if t - utt_end <= UTTERANCE_GAP_THRESHOLD:
                    utt_end = t
                else:
                    merged.append((utt_start, utt_end))
                    utt_start = utt_end = t
            merged.append((utt_start, utt_end))
            utterances[sid] = merged

        total_utts = sum(len(v) for v in utterances.values())
        logger.info("Aligner: %d utterances across %d players",
                    total_utts, len(utterances))

        # 4. Group and sort segments by (steam_id, start_time)
        by_player: dict[str, list] = {}
        for seg in segments:
            sid = getattr(seg, "steam_id", "")
            by_player.setdefault(sid, []).append(seg)
        for sid in by_player:
            by_player[sid].sort(key=lambda s: getattr(s, "start_time", 0.0))

        # 5. Assign utterance timestamps
        aligned = 0
        for sid, segs in by_player.items():
            utts = utterances.get(sid, [])
            if not utts:
                continue
            for i, seg in enumerate(segs):
                # Use duration from the compacted segment (best we have)
                duration = getattr(seg, "end_time", 0.0) - getattr(seg, "start_time", 0.0)
                if duration <= 0:
                    duration = 2.0  # sensible default

                if i < len(utts):
                    seg.start_time = utts[i][0]
                    seg.end_time = max(utts[i][1], utts[i][0] + duration)
                else:
                    # More segments than utterances — reuse last utterance
                    seg.start_time = utts[-1][0]
                    seg.end_time = utts[-1][0] + duration
                aligned += 1

        logger.info("Aligner: updated timestamps for %d segments", aligned)

    except Exception as e:
        logger.warning("Voice alignment failed (timestamps will be compacted): %s", e)
    finally:
        if tmp_dem is not None:
            try:
                tmp_dem.unlink()
            except OSError:
                pass

    return segments
