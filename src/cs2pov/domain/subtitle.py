from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Iterable, Sequence

from cs2pov.domain.models import TranslationSegment, TranscriptSegment, VoiceActivityCue


@dataclass(slots=True)
class SubtitlePolicy:
    """Display policy applied at export time only.

    The pipeline keeps transcript/translation timestamps as source artifacts. This
    policy changes only the exported SRT cues, so users can re-export different
    editing/review/debug versions without rerunning Whisper or the LLM.
    """

    name: str = "review"
    overlap_policy: str = "allow"  # allow | shift | compact
    max_duration_seconds: float | None = None
    min_duration_seconds: float = 0.7
    min_gap_seconds: float = 0.08


def policy_from_preset(preset: str | None, *, overlap_policy: str | None = None, max_duration_seconds: float | None = None, min_duration_seconds: float | None = None) -> SubtitlePolicy:
    preset_name = (preset or "review").strip().lower()
    defaults: dict[str, SubtitlePolicy] = {
        # Review keeps overlap close to the real comms timeline so users can
        # check ASR/translation against the original audio.
        "review": SubtitlePolicy(name="review", overlap_policy="allow", max_duration_seconds=10.0, min_duration_seconds=0.7, min_gap_seconds=0.08),
        # Editing is safer for剪辑软件: it lightly shifts overlapping subtitles
        # and keeps on-screen duration short.
        "editing": SubtitlePolicy(name="editing", overlap_policy="shift", max_duration_seconds=7.0, min_duration_seconds=0.7, min_gap_seconds=0.12),
        # Compact is the strictest user-facing export, useful when字幕太密.
        "compact": SubtitlePolicy(name="compact", overlap_policy="compact", max_duration_seconds=5.0, min_duration_seconds=0.55, min_gap_seconds=0.08),
        # Debug preserves timing shape while still clipping pathological cues.
        "debug": SubtitlePolicy(name="debug", overlap_policy="allow", max_duration_seconds=12.0, min_duration_seconds=0.5, min_gap_seconds=0.05),
    }
    if preset_name not in defaults:
        raise ValueError(f"未知字幕预设：{preset}。可选：editing/review/compact/debug。")
    policy = replace(defaults[preset_name])
    if overlap_policy:
        policy.overlap_policy = overlap_policy.strip().lower()
    if max_duration_seconds is not None:
        policy.max_duration_seconds = max_duration_seconds if max_duration_seconds > 0 else None
    if min_duration_seconds is not None:
        policy.min_duration_seconds = max(0.0, min_duration_seconds)
    if policy.overlap_policy not in {"allow", "shift", "compact"}:
        raise ValueError("overlap_policy 必须是 allow/shift/compact。")
    return policy


def format_srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def bilingual_text(segment: TranslationSegment, style: str = "label") -> str:
    """Render the default bilingual subtitle text.

    `label` avoids the arrow glyph that some editing software/user fonts render
    awkwardly, while `arrow` keeps the older v0.1 style for comparison.
    """
    original = segment.original_text.strip() or "[无法识别]"
    translated = segment.translated_text.strip() or "[未翻译]"
    if style == "arrow":
        return f"[{segment.player_name}] {original}\n→ {translated}"
    return f"[{segment.player_name}] {original}\n[中文] {translated}"


def compact_bilingual_text(segment: TranslationSegment, style: str = "label") -> str:
    original = segment.original_text.strip() or "[无法识别]"
    translated = segment.translated_text.strip() or "[未翻译]"
    if style == "arrow":
        return f"[{segment.player_name}] {original}\n→ {translated}"
    return f"[{segment.player_name}] {original}\n{translated}"


def original_text(segment: TranscriptSegment) -> str:
    text = segment.original_text.strip() or "[无法识别]"
    return f"[{segment.player_name}] {text}"


def zh_text(segment: TranslationSegment) -> str:
    text = segment.translated_text.strip() or "[未翻译]"
    return f"[{segment.player_name}] {text}"


def zh_text_no_player(segment: TranslationSegment) -> str:
    return segment.translated_text.strip() or "[未翻译]"


def debug_translation_text(segment: TranslationSegment) -> str:
    original = segment.original_text.strip() or "[无法识别]"
    translated = segment.translated_text.strip() or "[未翻译]"
    team = segment.team_number if segment.team_number is not None else "?"
    rnd = segment.round_number if segment.round_number is not None else "?"
    return f"[R{rnd}][T{team}][{segment.player_name}] {original}\n[中文] {translated}"


def voice_activity_text(cue: VoiceActivityCue) -> str:
    return f"[{cue.player_name}] voice ({cue.packet_count} packets)"


def apply_subtitle_policy(items: Sequence, policy: SubtitlePolicy | None = None) -> list:
    """Return export-only cue copies after applying duration/overlap policy."""
    if policy is None:
        return list(items)
    sorted_items = sorted(items, key=lambda x: (x.start_time, x.end_time))
    processed: list = []
    prev_end = -1.0
    for item in sorted_items:
        start = float(item.start_time)
        end = max(float(item.end_time), start + 0.05)
        original_duration = end - start

        if policy.max_duration_seconds is not None and original_duration > policy.max_duration_seconds:
            end = start + policy.max_duration_seconds
        if end - start < policy.min_duration_seconds:
            end = start + policy.min_duration_seconds

        if policy.overlap_policy in {"shift", "compact"} and processed:
            min_start = prev_end + policy.min_gap_seconds
            if start < min_start:
                if policy.overlap_policy == "shift":
                    duration = end - start
                    start = min_start
                    end = start + duration
                else:
                    # Compact mode favors a clean editing timeline. It first
                    # tries to shorten the cue; if that would make it too short,
                    # it shifts the cue forward.
                    if end - min_start >= policy.min_duration_seconds:
                        start = min_start
                    else:
                        duration = min(max(end - start, policy.min_duration_seconds), policy.max_duration_seconds or max(end - start, policy.min_duration_seconds))
                        start = min_start
                        end = start + duration
        if policy.max_duration_seconds is not None and end - start > policy.max_duration_seconds:
            end = start + policy.max_duration_seconds
        if end <= start:
            end = start + max(0.05, policy.min_duration_seconds)
        try:
            processed.append(replace(item, start_time=start, end_time=end))
        except TypeError:
            item.start_time = start
            item.end_time = end
            processed.append(item)
        prev_end = max(prev_end, end)
    return processed


def render_srt(items, text_fn: Callable, policy: SubtitlePolicy | None = None) -> str:
    lines: list[str] = []
    display_items = apply_subtitle_policy(list(items), policy)
    for idx, item in enumerate(display_items, 1):
        lines.append(str(idx))
        lines.append(f"{format_srt_time(item.start_time)} --> {format_srt_time(item.end_time)}")
        lines.append(text_fn(item))
        lines.append("")
    return "\n".join(lines).strip() + "\n"
