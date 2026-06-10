from __future__ import annotations

import json
import re
import unicodedata
import wave
from pathlib import Path
from typing import Any

from cs2pov.adapters.whisper_adapter import FasterWhisperAdapter
from cs2pov.domain.models import Round, TranscriptSegment, round_from_dict
from cs2pov.storage.artifact_store import ArtifactStore, safe_name
from cs2pov.storage.jsonl import read_json, read_jsonl, write_json, write_jsonl

UNRECOGNIZED_TEXT = "[未识别语音]"


class TranscriptionService:
    def __init__(self, adapter_factory=FasterWhisperAdapter):
        self.adapter_factory = adapter_factory

    def transcribe_all(
        self,
        store: ArtifactStore,
        model_name: str,
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "auto",
        selected_team_number: int | None = None,
        vad_filter: bool = True,
        include_unrecognized_voice: bool = False,
        unrecognized_min_duration_seconds: float = 0.35,
        transcription_mode: str = "round",
        max_rounds: int | None = None,
        activity_padding_seconds: float = 0.06,
        keep_temp_audio: bool = False,
        filter_hallucinations: bool = True,
        max_subtitle_segment_seconds: float = 10.0,
        voice_cluster_gap_seconds: float = 1.0,
        progress_callback=None,
    ) -> list[TranscriptSegment]:
        manifest = read_json(store.voice_manifest_path)
        adapter = self.adapter_factory(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            language=language,
            vad_filter=vad_filter,
        )
        transcription_mode = (transcription_mode or "round").lower()
        if transcription_mode not in {"round", "activity", "player"}:
            raise ValueError("transcription_mode 只能是 round / activity / player")

        players = [p for p in manifest.get("players", []) if selected_team_number is None or p.get("team_number") == selected_team_number]
        selected_rounds = _selected_rounds_for_transcription(store, selected_team_number, max_rounds)
        if transcription_mode == "player":
            segments = self._transcribe_player_wavs(players, adapter)
        else:
            segments = self._transcribe_windowed(
                store=store,
                players=players,
                adapter=adapter,
                mode=transcription_mode,
                selected_rounds=selected_rounds,
                activity_padding_seconds=activity_padding_seconds,
                keep_temp_audio=keep_temp_audio,
                progress_callback=progress_callback,
            )

        segments_before_postprocess = list(segments)
        pre_postprocess_coverage = build_transcription_coverage(
            store,
            segments_before_postprocess,
            selected_team_number=selected_team_number,
            unrecognized_min_duration_seconds=unrecognized_min_duration_seconds,
            selected_rounds=selected_rounds,
        )
        postprocess_stats = {
            "raw_transcript_segments_before_postprocess": len(segments_before_postprocess),
            "postprocessed_transcript_segments": 0,
            "coverage_ratio_before_postprocess": pre_postprocess_coverage.get("coverage_ratio_ge_min_duration"),
            "matched_voice_cues_before_postprocess": pre_postprocess_coverage.get("matched_voice_cues_ge_min_duration"),
            "unmatched_voice_cues_before_postprocess": pre_postprocess_coverage.get("unmatched_voice_cues_ge_min_duration"),
            "filtered_hallucination_segments": 0,
            "long_segments_rebased_to_voice_activity": 0,
            "segments_created_by_long_cue_rebase": 0,
        }
        if filter_hallucinations:
            before = len(segments)
            segments = [s for s in segments if not is_probable_whisper_hallucination(s.original_text)]
            postprocess_stats["filtered_hallucination_segments"] = before - len(segments)
        if max_subtitle_segment_seconds and max_subtitle_segment_seconds > 0:
            segments, rebase_stats = rebase_long_segments_to_voice_activity(
                store,
                segments,
                selected_team_number=selected_team_number,
                selected_rounds=selected_rounds,
                threshold_seconds=float(max_subtitle_segment_seconds),
                cluster_gap_seconds=float(voice_cluster_gap_seconds),
                split_text_across_clusters=(transcription_mode != "round"),
            )
            postprocess_stats.update(rebase_stats)

        # Rebase can split one long ASR string into multiple subtitle pieces.
        # A punctuation-dominated tail may be created only after splitting, so
        # run the conservative hallucination filter once more after rebase.
        postprocess_stats["filtered_hallucination_segments_after_rebase"] = 0
        if filter_hallucinations:
            before_after_rebase = len(segments)
            segments = [s for s in segments if not is_probable_whisper_hallucination(s.original_text)]
            postprocess_stats["filtered_hallucination_segments_after_rebase"] = before_after_rebase - len(segments)

        coverage = build_transcription_coverage(
            store,
            segments,
            selected_team_number=selected_team_number,
            unrecognized_min_duration_seconds=unrecognized_min_duration_seconds,
            selected_rounds=selected_rounds,
        )
        postprocess_stats["postprocessed_transcript_segments"] = len(segments)
        coverage.update({
            "transcription_mode": transcription_mode,
            "whisper_vad_filter": bool(vad_filter),
            "max_rounds_limit": max_rounds,
            "selected_round_numbers": [r.round_number for r in selected_rounds] if selected_rounds is not None else None,
            "long_transcript_segments_gt_30s": sum(1 for s in segments if s.end_time - s.start_time > 30.0),
            "longest_transcript_segment_seconds": round(max((s.end_time - s.start_time for s in segments), default=0.0), 3),
            "filter_hallucinations": bool(filter_hallucinations),
            "max_subtitle_segment_seconds": float(max_subtitle_segment_seconds),
            "voice_cluster_gap_seconds": float(voice_cluster_gap_seconds),
            "coverage_ratio_after_postprocess": coverage.get("coverage_ratio_ge_min_duration"),
            "coverage_note_after_postprocess": "覆盖率是启发式诊断。长 cue 重贴到真实 voice activity 后，字幕更短更适合剪辑，但 overlap 匹配口径可能导致 postprocess 后覆盖率下降。请同时查看 before/after 字段和 SRT 实际质量。",
            **postprocess_stats,
        })
        placeholders: list[TranscriptSegment] = []
        if include_unrecognized_voice:
            placeholders = _build_unrecognized_placeholders(
                store,
                segments,
                selected_team_number=selected_team_number,
                min_duration=unrecognized_min_duration_seconds,
                selected_rounds=selected_rounds,
            )
            segments.extend(placeholders)
            coverage["unrecognized_placeholders_added"] = len(placeholders)
        else:
            coverage["unrecognized_placeholders_added"] = 0

        segments.sort(key=lambda s: (s.start_time, s.end_time, s.player_name, s.id))
        write_jsonl(store.transcripts_path, segments)
        write_json(store.transcription_coverage_path, coverage)
        if not keep_temp_audio:
            _cleanup_temp_audio(store)
        return segments

    def _transcribe_player_wavs(self, players: list[dict[str, Any]], adapter: Any) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for player in players:
            wav_path = Path(player["wav_path"])
            packets = json.loads(Path(player["packet_info_path"]).read_text(encoding="utf-8"))
            raw_segments = adapter.transcribe(wav_path)
            for idx, raw in enumerate(raw_segments, 1):
                seg = _raw_to_transcript_segment(player, idx, raw, packets)
                if seg is not None:
                    segments.append(seg)
        return segments

    def _transcribe_windowed(
        self,
        store: ArtifactStore,
        players: list[dict[str, Any]],
        adapter: Any,
        mode: str,
        selected_rounds: list[Round] | None,
        activity_padding_seconds: float,
        keep_temp_audio: bool,
        progress_callback=None,
    ) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        voice_rows = _filtered_voice_rows(store, None)
        if selected_rounds is not None:
            voice_rows = [row for row in voice_rows if _row_inside_any_round(row, selected_rounds)]
        player_by_sid = {str(p["steamid"]): p for p in players}
        packets_by_sid: dict[str, list[dict[str, Any]]] = {}
        if mode == "activity":
            windows_by_sid = _activity_windows_by_sid(voice_rows)
        else:
            windows_by_sid = _round_windows_by_sid(voice_rows, selected_rounds)

        total_windows = sum(len(windows) for sid, windows in windows_by_sid.items() if sid in player_by_sid)
        completed_windows = 0
        for sid, windows in windows_by_sid.items():
            player = player_by_sid.get(sid)
            if not player:
                continue
            packets = packets_by_sid.setdefault(sid, json.loads(Path(player["packet_info_path"]).read_text(encoding="utf-8")))
            wav_path = Path(player["wav_path"])
            for win_idx, window in enumerate(windows, 1):
                completed_windows += 1
                if progress_callback:
                    rn = window.get("round_number")
                    rn_text = f"Round {rn}" if rn is not None else mode
                    progress_callback(f"转录中... {rn_text}，玩家 {player.get('name') or sid}（窗口 {completed_windows}/{total_windows}）")
                start_offset, end_offset = _demo_window_to_wav_offsets(window["start_time"], window["end_time"], packets, activity_padding_seconds)
                if end_offset <= start_offset:
                    continue
                snippet = _write_wav_slice(
                    source_wav=wav_path,
                    target_dir=store.temp_audio_dir / safe_name(str(player.get("name") or sid), 30),
                    name=f"{mode}_{win_idx:05d}_{round(window['start_time'], 3)}_{round(window['end_time'], 3)}.wav",
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
                raw_segments = adapter.transcribe(snippet)
                for raw_idx, raw in enumerate(raw_segments, 1):
                    raw_with_global_offset = dict(raw)
                    raw_with_global_offset["start"] = float(raw.get("start", 0.0)) + start_offset
                    raw_with_global_offset["end"] = float(raw.get("end", 0.0)) + start_offset
                    seg = _raw_to_transcript_segment(player, win_idx * 1000 + raw_idx, raw_with_global_offset, packets)
                    if seg is not None:
                        # Clamp pathological spillover from ASR to the window.  The text is still preserved,
                        # but the subtitle cue no longer covers minutes of unrelated demo time.
                        seg.start_time = round(max(seg.start_time, float(window["start_time"])), 3)
                        seg.end_time = round(min(seg.end_time, float(window["end_time"])), 3)
                        if seg.end_time <= seg.start_time:
                            seg.end_time = round(seg.start_time + 0.5, 3)
                        if window.get("round_number") is not None:
                            seg.round_number = int(window["round_number"])
                        segments.append(seg)
                if not keep_temp_audio:
                    try:
                        snippet.unlink(missing_ok=True)
                    except Exception:
                        pass
        return segments


def _raw_to_transcript_segment(player: dict[str, Any], idx: int, raw: dict[str, Any], packets: list[dict[str, Any]]) -> TranscriptSegment | None:
    demo_start = _map_wav_offset_to_demo_time(float(raw["start"]), packets)
    demo_end = _map_wav_offset_to_demo_time(float(raw["end"]), packets)
    if demo_end <= demo_start:
        demo_end = demo_start + max(0.5, float(raw["end"]) - float(raw["start"]))
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    return TranscriptSegment(
        id=f"tr_{player['steamid']}_{idx:05d}",
        steamid=str(player["steamid"]),
        player_name=str(player.get("name") or player["steamid"]),
        team_number=player.get("team_number"),
        start_time=round(demo_start, 3),
        end_time=round(demo_end, 3),
        original_text=text,
        language=raw.get("language"),
        confidence=raw.get("confidence"),
    )


def _selected_rounds_for_transcription(store: ArtifactStore, selected_team_number: int | None, max_rounds: int | None) -> list[Round] | None:
    if not store.rounds_path.exists():
        return None
    rounds = [round_from_dict(row) for row in read_json(store.rounds_path)]
    if max_rounds is None:
        return rounds
    voice_rows = _filtered_voice_rows(store, selected_team_number)
    selected: list[Round] = []
    for rnd in rounds:
        if any(rnd.start_time <= float(row["start_time"]) < rnd.end_time for row in voice_rows):
            selected.append(rnd)
            if len(selected) >= max_rounds:
                break
    return selected


def _activity_windows_by_sid(voice_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    windows: dict[str, list[dict[str, Any]]] = {}
    for row in voice_rows:
        sid = str(row["steamid"])
        windows.setdefault(sid, []).append({
            "start_time": float(row["start_time"]),
            "end_time": float(row["end_time"]),
            "round_number": row.get("round_number"),
        })
    for rows in windows.values():
        rows.sort(key=lambda x: (x["start_time"], x["end_time"]))
    return windows


def _round_windows_by_sid(voice_rows: list[dict[str, Any]], selected_rounds: list[Round] | None) -> dict[str, list[dict[str, Any]]]:
    if selected_rounds is None:
        # Fall back to activity windows if round data is unavailable.
        return _activity_windows_by_sid(voice_rows)
    windows: dict[str, list[dict[str, Any]]] = {}
    for rnd in selected_rounds:
        by_sid: dict[str, list[dict[str, Any]]] = {}
        for row in voice_rows:
            if rnd.start_time <= float(row["start_time"]) < rnd.end_time:
                by_sid.setdefault(str(row["steamid"]), []).append(row)
        for sid, rows in by_sid.items():
            windows.setdefault(sid, []).append({
                "start_time": min(float(r["start_time"]) for r in rows),
                "end_time": max(float(r["end_time"]) for r in rows),
                "round_number": rnd.round_number,
            })
    return windows


def _row_inside_any_round(row: dict[str, Any], rounds: list[Round]) -> bool:
    start = float(row["start_time"])
    return any(r.start_time <= start < r.end_time for r in rounds)


def _demo_window_to_wav_offsets(start_time: float, end_time: float, packets: list[dict[str, Any]], padding: float = 0.0) -> tuple[float, float]:
    if not packets:
        return 0.0, 0.0
    start_time = float(start_time) - max(0.0, padding)
    end_time = float(end_time) + max(0.0, padding)
    overlapping = [
        p for p in packets
        if float(p["demo_end"]) >= start_time and float(p["demo_start"]) <= end_time
    ]
    if not overlapping:
        return 0.0, 0.0
    first = overlapping[0]
    last = overlapping[-1]
    return float(first["wav_offset"]), float(last["wav_offset"]) + float(last["duration"])


def _write_wav_slice(source_wav: Path, target_dir: Path, name: str, start_offset: float, end_offset: float) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name(name, 120)
    with wave.open(str(source_wav), "rb") as src:
        params = src.getparams()
        framerate = src.getframerate()
        start_frame = max(0, int(start_offset * framerate))
        end_frame = max(start_frame + 1, int(end_offset * framerate))
        src.setpos(min(start_frame, src.getnframes()))
        frames = src.readframes(max(0, min(end_frame, src.getnframes()) - start_frame))
        with wave.open(str(target_path), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(frames)
    return target_path


def build_transcription_coverage(
    store: ArtifactStore,
    transcripts: list[TranscriptSegment],
    selected_team_number: int | None,
    unrecognized_min_duration_seconds: float,
    selected_rounds: list[Round] | None = None,
) -> dict[str, Any]:
    voice_rows = _filtered_voice_rows(store, selected_team_number)
    if selected_rounds is not None:
        voice_rows = [row for row in voice_rows if _row_inside_any_round(row, selected_rounds)]
    by_steam: dict[str, list[TranscriptSegment]] = {}
    for seg in transcripts:
        by_steam.setdefault(seg.steamid, []).append(seg)
    for segs in by_steam.values():
        segs.sort(key=lambda s: (s.start_time, s.end_time))

    unmatched = []
    matched_count = 0
    for cue in voice_rows:
        duration = float(cue["end_time"]) - float(cue["start_time"])
        if duration < unrecognized_min_duration_seconds:
            continue
        overlaps = by_steam.get(str(cue["steamid"]), [])
        if any(_overlaps(float(cue["start_time"]), float(cue["end_time"]), seg.start_time, seg.end_time) for seg in overlaps):
            matched_count += 1
        else:
            unmatched.append(cue)

    long_voice_count = matched_count + len(unmatched)
    by_team: dict[str, dict[str, int]] = {}
    for cue in voice_rows:
        team = str(cue.get("team_number"))
        by_team.setdefault(team, {"voice_cues": 0, "voice_cues_ge_min": 0})
        by_team[team]["voice_cues"] += 1
        if float(cue["end_time"]) - float(cue["start_time"]) >= unrecognized_min_duration_seconds:
            by_team[team]["voice_cues_ge_min"] += 1

    return {
        "selected_team_number": selected_team_number,
        "transcript_segments": len(transcripts),
        "voice_activity_cues": len(voice_rows),
        "voice_activity_cues_ge_min_duration": long_voice_count,
        "matched_voice_cues_ge_min_duration": matched_count,
        "unmatched_voice_cues_ge_min_duration": len(unmatched),
        "unrecognized_min_duration_seconds": unrecognized_min_duration_seconds,
        "coverage_ratio_ge_min_duration": round(matched_count / long_voice_count, 4) if long_voice_count else None,
        "by_team": by_team,
        "note": "Coverage is heuristic: one transcript segment can cover multiple short PTT bursts after compact-WAV decoding.",
    }


def _build_unrecognized_placeholders(
    store: ArtifactStore,
    transcripts: list[TranscriptSegment],
    selected_team_number: int | None,
    min_duration: float,
    selected_rounds: list[Round] | None = None,
) -> list[TranscriptSegment]:
    voice_rows = _filtered_voice_rows(store, selected_team_number)
    if selected_rounds is not None:
        voice_rows = [row for row in voice_rows if _row_inside_any_round(row, selected_rounds)]
    by_steam: dict[str, list[TranscriptSegment]] = {}
    for seg in transcripts:
        by_steam.setdefault(seg.steamid, []).append(seg)
    placeholders: list[TranscriptSegment] = []
    per_steam_idx: dict[str, int] = {}
    for cue in voice_rows:
        start = float(cue["start_time"])
        end = float(cue["end_time"])
        if end - start < min_duration:
            continue
        steamid = str(cue["steamid"])
        if any(_overlaps(start, end, seg.start_time, seg.end_time) for seg in by_steam.get(steamid, [])):
            continue
        per_steam_idx[steamid] = per_steam_idx.get(steamid, 0) + 1
        placeholders.append(TranscriptSegment(
            id=f"unrec_{steamid}_{per_steam_idx[steamid]:05d}",
            steamid=steamid,
            player_name=str(cue.get("player_name") or steamid),
            team_number=cue.get("team_number"),
            start_time=round(start, 3),
            end_time=round(end, 3),
            original_text=UNRECOGNIZED_TEXT,
            language="unrecognized",
            confidence=0.0,
        ))
    return placeholders



def is_probable_whisper_hallucination(text: str) -> bool:
    """Return True for safe-to-drop Whisper noise, not for real short callouts.

    The filter is intentionally conservative for CS2 comms: it keeps short real
    calls such as "go", "A", "B?", "one!", "警家一个", and Cyrillic/Korean
    words, but drops punctuation-only or punctuation-dominated Whisper tails such
    as ",,,,,,,,," or "끝,,,,,,,,,,,,".
    """
    value = (text or "").strip()
    if not value:
        return True
    stripped = re.sub(r"\s+", "", value)
    if not stripped:
        return True

    meaningful = 0
    punctuation_or_symbol = 0
    other = 0
    for ch in stripped:
        category = unicodedata.category(ch)
        if category[0] in {"L", "N"}:
            meaningful += 1
        elif category[0] in {"P", "S"}:
            punctuation_or_symbol += 1
        else:
            other += 1

    if meaningful == 0 and punctuation_or_symbol > 0 and other == 0:
        return True

    total = meaningful + punctuation_or_symbol + other
    punctuation_ratio = punctuation_or_symbol / total if total else 0.0

    # Whisper sometimes emits one stray Hangul/Latin character followed by a
    # very long comma tail.  This is still noise, unlike a real one-word call.
    if total >= 8 and meaningful <= 2 and punctuation_or_symbol >= 6 and punctuation_ratio >= 0.70:
        return True
    if total >= 16 and punctuation_ratio >= 0.85 and meaningful <= 4:
        return True

    return False


def rebase_long_segments_to_voice_activity(
    store: ArtifactStore,
    segments: list[TranscriptSegment],
    selected_team_number: int | None,
    selected_rounds: list[Round] | None,
    threshold_seconds: float,
    cluster_gap_seconds: float,
    split_text_across_clusters: bool = True,
) -> tuple[list[TranscriptSegment], dict[str, int]]:
    """Split pathologically long ASR cues back onto actual voice-activity clusters.

    Round-mode transcription is intentionally better for Whisper context, but some
    models still emit a cue that spans an entire player's round window.  When that
    happens, keep the round-mode text but place it on the player's real speaking
    bursts so SRT cues do not stay on screen for 60-90 seconds.
    """
    voice_rows = _filtered_voice_rows(store, selected_team_number)
    if selected_rounds is not None:
        voice_rows = [row for row in voice_rows if _row_inside_any_round(row, selected_rounds)]
    by_sid: dict[str, list[dict[str, Any]]] = {}
    for row in voice_rows:
        by_sid.setdefault(str(row["steamid"]), []).append(row)

    output: list[TranscriptSegment] = []
    rebased = 0
    created = 0
    clamped_without_split = 0
    for seg in segments:
        duration = seg.end_time - seg.start_time
        if duration <= threshold_seconds or seg.original_text == UNRECOGNIZED_TEXT:
            output.append(seg)
            continue
        rows = [
            row for row in by_sid.get(seg.steamid, [])
            if _overlaps(float(row["start_time"]), float(row["end_time"]), seg.start_time, seg.end_time, tolerance=0.25)
        ]
        if not rows:
            output.append(seg)
            continue
        clusters = _cluster_voice_rows(rows, max_gap_seconds=cluster_gap_seconds)
        if not clusters:
            output.append(seg)
            continue
        # If all activity collapses to one cluster, simply clamp to the actual speech span.
        if len(clusters) == 1:
            start, end = clusters[0]
            if end - start < duration:
                output.append(_copy_segment_with_timing(seg, seg.id + "_vc01", start, end))
                rebased += 1
                created += 1
            else:
                output.append(seg)
            continue
        if not split_text_across_clusters:
            # In round mode, Whisper often returns a semantically coherent sentence for
            # audio that maps back to several disjoint PTT bursts.  Splitting by word
            # creates unusable subtitles such as "Ben" + "ch.".  Keep the sentence
            # intact and anchor it near the first real speaking burst.  Do not simply
            # leave it on screen for the full hard cap; estimate a readable display
            # duration from the text length so SRT cues are closer to editing-ready.
            start = clusters[0][0]
            display_seconds = _estimate_readable_subtitle_seconds(seg.original_text, hard_cap_seconds=float(threshold_seconds))
            end = min(clusters[-1][1], start + display_seconds)
            if end <= start:
                end = max(clusters[0][1], start + 1.0)
            output.append(_copy_segment_with_timing(seg, seg.id + "_vc01", start, end))
            rebased += 1
            created += 1
            clamped_without_split += 1
            continue

        pieces = _split_text_for_clusters(seg.original_text, len(clusters))
        if len(pieces) <= 1:
            # Very short text across many bursts: put it on the first actual burst, not the whole round.
            start, end = clusters[0]
            output.append(_copy_segment_with_timing(seg, seg.id + "_vc01", start, end))
            rebased += 1
            created += 1
            continue
        n = min(len(pieces), len(clusters))
        for idx in range(n):
            start, end = clusters[idx]
            output.append(_copy_segment_with_timing(seg, f"{seg.id}_vc{idx+1:02d}", start, end, pieces[idx]))
        rebased += 1
        created += n
    output.sort(key=lambda s: (s.start_time, s.end_time, s.player_name, s.id))
    return output, {
        "long_segments_rebased_to_voice_activity": rebased,
        "segments_created_by_long_cue_rebase": created,
        "long_segments_clamped_without_text_split": clamped_without_split,
    }


def _estimate_readable_subtitle_seconds(text: str, hard_cap_seconds: float, min_seconds: float = 2.0) -> float:
    """Estimate a compact but readable duration for a subtitle cue.

    This is deliberately conservative: it is only used after a pathological
    long ASR cue has already been identified.  The goal is to avoid many cues
    landing exactly on the hard cap, while still keeping a full round-mode
    sentence intact for readability.
    """
    hard_cap = max(float(hard_cap_seconds), min_seconds)
    normalized = " ".join((text or "").split())
    if not normalized:
        return min_seconds
    # Count visible characters rather than bytes.  A higher chars-per-second
    # value is acceptable because bilingual export already shows the original
    # and translated lines together; this estimate is a cap for abnormal cues,
    # not perfect word-level timing.
    visible_chars = sum(1 for ch in normalized if not ch.isspace())
    estimated = 1.4 + visible_chars / 14.0
    return round(min(hard_cap, max(min_seconds, estimated)), 3)


def _cluster_voice_rows(rows: list[dict[str, Any]], max_gap_seconds: float) -> list[tuple[float, float]]:
    clusters: list[tuple[float, float]] = []
    for row in sorted(rows, key=lambda r: (float(r["start_time"]), float(r["end_time"]))):
        start = float(row["start_time"])
        end = float(row["end_time"])
        if end <= start:
            continue
        if not clusters or start - clusters[-1][1] > max_gap_seconds:
            clusters.append((start, end))
        else:
            clusters[-1] = (clusters[-1][0], max(clusters[-1][1], end))
    return [(round(a, 3), round(b, 3)) for a, b in clusters]


def _copy_segment_with_timing(seg: TranscriptSegment, new_id: str, start: float, end: float, text: str | None = None) -> TranscriptSegment:
    if end <= start:
        end = start + 0.5
    return TranscriptSegment(
        id=new_id,
        steamid=seg.steamid,
        player_name=seg.player_name,
        team_number=seg.team_number,
        start_time=round(start, 3),
        end_time=round(end, 3),
        original_text=text if text is not None else seg.original_text,
        language=seg.language,
        round_number=seg.round_number,
        confidence=seg.confidence,
    )


def _split_text_for_clusters(text: str, count: int) -> list[str]:
    text = " ".join((text or "").split())
    if count <= 1 or not text:
        return [text] if text else []
    sentence_parts = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", text) if p.strip()]
    if len(sentence_parts) >= count:
        return _rebalance_parts(sentence_parts, count)
    words = text.split()
    if len(words) >= count:
        return [" ".join(part) for part in _chunk_evenly(words, count)]
    # Last resort for languages without spaces.
    chars = list(text)
    if len(chars) >= count:
        return ["".join(part).strip() for part in _chunk_evenly(chars, count) if "".join(part).strip()]
    return [text]


def _rebalance_parts(parts: list[str], count: int) -> list[str]:
    if len(parts) == count:
        return parts
    chunks = _chunk_evenly(parts, count)
    return [" ".join(chunk).strip() for chunk in chunks if " ".join(chunk).strip()]


def _chunk_evenly(items: list[Any], count: int) -> list[list[Any]]:
    count = max(1, min(count, len(items)))
    chunks: list[list[Any]] = []
    for i in range(count):
        start = round(i * len(items) / count)
        end = round((i + 1) * len(items) / count)
        chunk = items[start:end]
        if chunk:
            chunks.append(chunk)
    return chunks

def _filtered_voice_rows(store: ArtifactStore, selected_team_number: int | None) -> list[dict[str, Any]]:
    rows = read_jsonl(store.voice_activity_path)
    if selected_team_number is not None:
        rows = [row for row in rows if row.get("team_number") == selected_team_number]
    return sorted(rows, key=lambda row: (float(row["start_time"]), float(row["end_time"]), str(row.get("player_name", ""))))


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float, tolerance: float = 0.05) -> bool:
    return max(a_start, b_start) <= min(a_end, b_end) + tolerance


def _map_wav_offset_to_demo_time(offset: float, packets: list[dict[str, Any]]) -> float:
    if not packets:
        return offset
    best = packets[0]
    for packet in packets:
        start = float(packet["wav_offset"])
        duration = float(packet["duration"])
        end = start + duration
        if start <= offset <= end:
            return float(packet["demo_start"]) + (offset - start)
        if start <= offset:
            best = packet
        else:
            break
    return float(best["demo_start"]) + max(0.0, offset - float(best["wav_offset"]))


def _cleanup_temp_audio(store: ArtifactStore) -> None:
    if not store.temp_audio_dir.exists():
        return
    for path in sorted(store.temp_audio_dir.rglob("*"), reverse=True):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except Exception:
            pass
