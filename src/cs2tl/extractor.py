"""Voice extraction from CS2 demos via demoparser2 + pyogg (libopus).

Replaces the v0.0 csgove (Go binary) approach with a pure-Python pipeline:
  demoparser2.parse_voice() → pyogg.opus_decode() → wave.write()

Key architectural properties:
  - Timestamps are correct at extraction time (tick / 64.0), eliminating
    the need for voice_aligner (deleted in v0.1).
  - Corrupt opus frames are skipped with a counter (D5 decision).
  - WAV files use fixed names ({steam_id}.wav) — overwrite, don't accumulate.
  - zst decompression is delegated to shared.decompress_zst().
"""

from __future__ import annotations

import ctypes
import logging
import wave
from dataclasses import dataclass, field
from pathlib import Path

from cs2tl.errors import (
    extractor_failed,
    no_voice_data,
    opus_decoder_failed,
)
from cs2tl.shared import decompress_zst

logger = logging.getLogger(__name__)

# --- Opus constants (CS2 voice chat: 24kHz mono) ---
SAMPLE_RATE = 24000
CHANNELS = 1
# Maximum samples per opus frame at 24kHz: 120ms × 240 samples/ms = 2880.
# We allocate 5760 to be safe (headroom for 48kHz frames downsampled).
MAX_SAMPLES = 5760

# CS2 competitive / Faceit tick rate (hardcoded — demoparser2 has no tick_rate()).
TICK_RATE = 64.0

# BOT filter: real Steam ID64s are exactly 17 digits and start with "7656".
STEAM_ID_LENGTH = 17
STEAM_ID_PREFIX = "7656"


@dataclass
class ExtractionResult:
    """Result of voice extraction from a demo file.

    Attributes:
        wav_files: steam_id → path to {steam_id}.wav.
        voice_timestamps: steam_id → list of (start_seconds, end_seconds)
            for each voice packet, derived from game ticks.
        output_dir: Directory containing the WAV files.
        skipped_frames: Number of corrupt opus frames that were skipped.
    """

    wav_files: dict[str, Path] = field(default_factory=dict)
    voice_timestamps: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    voice_packet_info: dict[str, list[dict]] = field(default_factory=dict)
    output_dir: Path = Path()
    skipped_frames: int = 0


def run_extraction(
    demo_path: Path,
    output_dir: Path,
) -> ExtractionResult:
    """Extract per-player voice audio from a CS2 demo.

    Pipeline:
      1. Decompress .dem.zst → temp .dem (via shared.decompress_zst).
      2. Parse voice packets via demoparser2.parse_voice().
      3. Group by steam_id, filter BOTs, sort by tick.
      4. Create opus decoder → decode each packet → accumulate PCM.
      5. Write per-player WAV files ({steam_id}.wav).
      6. Build ExtractionResult with timestamps from game ticks.
      7. Clean up temp .dem.

    Args:
        demo_path: Path to .dem or .dem.zst file.
        output_dir: Directory for extracted WAV files.

    Returns:
        ExtractionResult with WAV paths and voice timestamps.

    Raises:
        CS2tlError: E1-0003 if zero voice data, E1-0004 if opus decoder
            creation fails, E1-0002 for other extraction failures.
    """
    from demoparser2 import DemoParser
    from pyogg.opus import opus_decoder_create, opus_decode

    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dem: Path | None = None

    try:
        # 1. Decompress .zst if needed
        actual_demo = demo_path
        if demo_path.suffix == ".zst":
            tmp_dem = decompress_zst(demo_path)
            actual_demo = tmp_dem
            logger.info("Decompressed %s → %s", demo_path.name, tmp_dem.name)

        # 2. Parse voice packets
        parser = DemoParser(str(actual_demo))
        voice_data = parser.parse_voice()
        logger.info("Parsed %d voice packets from demo", len(voice_data))

        # 3. Group by steam_id, filter BOTs, sort by tick
        by_player: dict[str, list[tuple[int, bytes]]] = {}
        for pkt in voice_data:
            sid = str(int(pkt["steamid"]))
            if len(sid) == STEAM_ID_LENGTH and sid.startswith(STEAM_ID_PREFIX):
                by_player.setdefault(sid, []).append(
                    (pkt["tick"], pkt["bytes"])
                )

        if not by_player:
            raise no_voice_data(str(demo_path))

        # Sort each player's packets by tick
        for sid in by_player:
            by_player[sid].sort(key=lambda x: x[0])

        # 4. Create opus decoder (D7 decision — fail loud with E1-0004)
        err = ctypes.c_int()
        decoder = opus_decoder_create(
            ctypes.c_int32(SAMPLE_RATE),
            ctypes.c_int(CHANNELS),
            ctypes.pointer(err),
        )
        if not decoder:
            raise opus_decoder_failed(
                f"opus_decoder_create returned NULL (error code: {err.value})"
            )

        pcm_buf = (ctypes.c_short * MAX_SAMPLES)()
        wav_files: dict[str, Path] = {}
        timestamps: dict[str, list[tuple[float, float]]] = {}
        packet_info: dict[str, list[dict]] = {}
        skipped_frames = 0

        # 5. Decode per player (D5 decision — skip corrupt frames)
        for sid, packets in by_player.items():
            all_pcm = bytearray()
            player_ts: list[tuple[float, float]] = []
            player_packets: list[dict] = []
            wav_offset = 0.0  # cumulative seconds in the WAV

            for tick, opus_bytes in packets:
                raw_buf = (ctypes.c_ubyte * len(opus_bytes))(*opus_bytes)
                samples = opus_decode(
                    decoder,
                    ctypes.cast(raw_buf, ctypes.POINTER(ctypes.c_ubyte)),
                    ctypes.c_int32(len(opus_bytes)),
                    ctypes.cast(pcm_buf, ctypes.POINTER(ctypes.c_short)),
                    ctypes.c_int32(MAX_SAMPLES),
                    ctypes.c_int(0),
                )

                if samples > 0:
                    for j in range(samples):
                        all_pcm.extend(
                            pcm_buf[j].to_bytes(2, "little", signed=True)
                        )
                    t_sec = tick / TICK_RATE
                    duration = samples / SAMPLE_RATE
                    player_ts.append((round(t_sec, 3), round(t_sec + duration, 3)))
                    # Track per-packet WAV offset for timestamp alignment later
                    player_packets.append({
                        "demo_start": round(t_sec, 3),
                        "demo_end": round(t_sec + duration, 3),
                        "wav_offset": round(wav_offset, 3),
                        "duration": round(duration, 3),
                    })
                    wav_offset += duration
                elif samples < 0:
                    logger.warning(
                        "opus_decode error %d for steam_id=%s at tick=%d — skipping frame",
                        samples, sid, tick,
                    )
                    skipped_frames += 1

            # 6. Write WAV (fixed filename — overwrites, doesn't accumulate)
            if all_pcm:
                wav_path = output_dir / f"{sid}.wav"
                with wave.open(str(wav_path), "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)  # 16-bit = 2 bytes
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(all_pcm)
                wav_files[sid] = wav_path
                timestamps[sid] = player_ts
                packet_info[sid] = player_packets
                logger.debug(
                    "Wrote %s: %d packets, %.2fs of audio",
                    wav_path.name, len(packets),
                    sum(d for _, d in player_ts) if player_ts else 0,
                )

        # 7. Zero-voice check (after filtering — E1-0003)
        if not wav_files:
            raise no_voice_data(str(demo_path))

        if skipped_frames:
            logger.info("Skipped %d corrupt opus frames across all players", skipped_frames)

        logger.info(
            "Extracted %d voice files (%d players)%s",
            len(wav_files), len(wav_files),
            f", skipped {skipped_frames} corrupt frames" if skipped_frames else "",
        )

        return ExtractionResult(
            wav_files=wav_files,
            voice_timestamps=timestamps,
            voice_packet_info=packet_info,
            output_dir=output_dir,
            skipped_frames=skipped_frames,
        )

    except Exception as e:
        # Re-raise CS2tlError as-is; wrap unexpected errors
        from cs2tl.errors import CS2tlError
        if isinstance(e, CS2tlError):
            raise
        raise extractor_failed(str(demo_path), str(e)) from e

    finally:
        # 8. Clean up temporary decompressed .dem
        if tmp_dem is not None:
            try:
                tmp_dem.unlink()
                logger.debug("Cleaned up temp file: %s", tmp_dem)
            except OSError:
                pass


def align_transcriber_timestamps(
    partial_segs: list,
    voice_packet_info: dict[str, list[dict]],
) -> list:
    """Map Whisper's WAV-relative timestamps back to demo-relative time.

    The transcriber sees concatenated voice packets as one WAV file, so its
    timestamps are relative to WAV start (0:00).  Real demo timestamps come
    from the extractor's per-packet ``voice_packet_info`` which records the
    (demo_start, wav_offset, duration) of every decoded opus frame.

    Mutates each segment's ``start_time`` and ``end_time`` in-place and
    returns the same list.  Callers should use the return value for
    clarity but reassignment is not strictly required.

    Algorithm:
      For each segment, find the voice packet whose WAV range contains the
      segment's ``start_time``, then apply:
          offset = packet.demo_start - packet.wav_offset
          segment.start_time += offset
          segment.end_time   += offset

    Segments that don't fall cleanly into any packet (edge cases like VAD
    splitting a phrase across packet boundaries) are snapped to the nearest
    packet — we use the packet whose WAV range overlaps the segment's start.
    """
    if not voice_packet_info:
        return list(partial_segs)

    for seg in partial_segs:
        sid = getattr(seg, "steam_id", "")
        packets = voice_packet_info.get(sid, [])
        if not packets:
            continue

        wav_start = getattr(seg, "start_time", 0.0)
        wav_end = getattr(seg, "end_time", wav_start + 1.0)

        # Find the packet whose WAV range covers wav_start
        best_pkt = None
        for pkt in packets:
            pkt_wav_end = pkt["wav_offset"] + pkt["duration"]
            if pkt["wav_offset"] <= wav_start < pkt_wav_end + 0.05:
                best_pkt = pkt
                break

        if best_pkt is None:
            # Fallback: snap to the chronologically closest packet
            if packets:
                best_pkt = min(
                    packets,
                    key=lambda p: abs(p["wav_offset"] - wav_start),
                )

        if best_pkt is not None:
            offset = best_pkt["demo_start"] - best_pkt["wav_offset"]
            seg.start_time = round(wav_start + offset, 3)
            seg.end_time = round(wav_end + offset, 3)

    return partial_segs
