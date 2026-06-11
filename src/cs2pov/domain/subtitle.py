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
    overlap_policy: str = "allow"  # allow | shift | compact | merge | stack
    max_duration_seconds: float | None = None
    min_duration_seconds: float = 0.7
    min_gap_seconds: float = 0.08
    max_visible_cues: int = 2
    min_stack_fragment_seconds: float = 0.35


def policy_from_preset(preset: str | None, *, overlap_policy: str | None = None, max_duration_seconds: float | None = None, min_duration_seconds: float | None = None) -> SubtitlePolicy:
    preset_name = (preset or "review").strip().lower()
    defaults: dict[str, SubtitlePolicy] = {
        # Review keeps overlap close to the real comms timeline so users can
        # check ASR/translation against the original audio.
        "review": SubtitlePolicy(name="review", overlap_policy="allow", max_duration_seconds=10.0, min_duration_seconds=0.7, min_gap_seconds=0.08),
        # Editing is optimized for CS2 POV clips: keep the timeline
        # single-track friendly, but never merge a whole voice pile into a
        # half-screen subtitle block. At any moment, show at most two speaker
        # cues; when a third cue starts, the newest cue replaces the earliest
        # visible one instead of delaying the new comm.
        "editing": SubtitlePolicy(name="editing", overlap_policy="stack", max_duration_seconds=7.0, min_duration_seconds=0.7, min_gap_seconds=0.12, max_visible_cues=2, min_stack_fragment_seconds=0.35),
        # Compact is stricter on duration while keeping the same max-2 visual
        # stack as editing, useful when字幕太密.
        "compact": SubtitlePolicy(name="compact", overlap_policy="stack", max_duration_seconds=5.0, min_duration_seconds=0.55, min_gap_seconds=0.08, max_visible_cues=2, min_stack_fragment_seconds=0.30),
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
    if policy.overlap_policy not in {"allow", "shift", "compact", "merge", "stack"}:
        raise ValueError("overlap_policy 必须是 allow/shift/compact/merge/stack。")
    policy.max_visible_cues = max(1, int(policy.max_visible_cues or 2))
    policy.min_stack_fragment_seconds = max(0.0, float(policy.min_stack_fragment_seconds or 0.0))
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


def _merge_overlapping_items(items: Sequence, text_fn: Callable) -> list[tuple[float, float, str]]:
    """Merge overlapping cue objects into single SRT cue payloads.

    SRT itself has no speaker-aware layout semantics. If two independent cues
    overlap, editing apps can import/draw them as separate subtitle blocks and
    visually stack them on top of each other. For剪映-friendly exports, merge an
    overlap cluster into one cue whose text contains all speakers in chronological
    order. This keeps the timeline non-overlapping without changing the source
    transcript/translation artifacts.
    """

    merged: list[tuple[float, float, str]] = []
    current: list = []
    current_start = 0.0
    current_end = 0.0

    def flush() -> None:
        nonlocal current, current_start, current_end
        if not current:
            return
        text_blocks: list[str] = []
        seen: set[str] = set()
        for cue in sorted(current, key=lambda x: (x.start_time, x.end_time)):
            text = str(text_fn(cue)).strip()
            if text and text not in seen:
                text_blocks.append(text)
                seen.add(text)
        merged.append((current_start, current_end, "\n".join(text_blocks)))
        current = []

    for item in sorted(items, key=lambda x: (x.start_time, x.end_time)):
        start = float(item.start_time)
        end = float(item.end_time)
        if not current:
            current = [item]
            current_start = start
            current_end = end
            continue
        if start < current_end:
            current.append(item)
            current_end = max(current_end, end)
            continue
        flush()
        current = [item]
        current_start = start
        current_end = end
    flush()
    return merged


def _stack_visible_items(items: Sequence, text_fn: Callable, max_visible: int = 2) -> list[tuple[float, float, str]]:
    """Render an editing-safe max-N subtitle stack.

    This is intentionally different from merge: it never accumulates every
    overlapping speaker into one large block. It keeps at most `max_visible`
    active speaker cues. If a new cue starts while the stack is full, the new
    cue replaces the earliest visible cue. Replaced cues are not delayed and do
    not come back later, which matches POV editing expectations: latest comms
    are usually more important than stale overlapping ones.
    """

    sorted_items = sorted(items, key=lambda x: (float(x.start_time), float(x.end_time)))
    if not sorted_items:
        return []

    stack: list = []
    rendered: list[tuple[float, float, str]] = []
    last_time: float | None = None

    def stack_text() -> str:
        blocks: list[str] = []
        seen: set[str] = set()
        for cue in stack:
            text = str(text_fn(cue)).strip()
            if text and text not in seen:
                blocks.append(text)
                seen.add(text)
        return "\n".join(blocks)

    def emit_until(next_time: float) -> None:
        nonlocal last_time
        if last_time is None:
            last_time = next_time
            return
        if next_time <= last_time:
            return
        text = stack_text()
        if text:
            # Coalesce adjacent fragments with identical text to avoid needless
            # SRT flicker when an unrelated hidden cue starts/ends.
            if rendered and rendered[-1][2] == text and abs(rendered[-1][1] - last_time) < 1e-6:
                rendered[-1] = (rendered[-1][0], next_time, text)
            else:
                rendered.append((last_time, next_time, text))
        last_time = next_time

    events: list[tuple[float, int, object]] = []
    for item in sorted_items:
        events.append((float(item.start_time), 1, item))
        events.append((float(item.end_time), 0, item))
    # End events first at the same timestamp, then start events. This prevents a
    # cue ending at 2.000 from occupying a visible slot for another cue starting
    # at exactly 2.000. Starts are processed chronologically.
    events.sort(key=lambda e: (e[0], e[1], float(e[2].end_time) if e[1] else 0.0))

    for time, kind, item in events:
        emit_until(time)
        if kind == 0:
            stack = [cue for cue in stack if cue is not item]
        else:
            if item in stack:
                continue
            # Drop ended cues defensively in case malformed input has non-sorted
            # or zero-length timing.
            stack = [cue for cue in stack if float(cue.end_time) > time]
            # Same speaker emitted another overlapping ASR segment. Treat the
            # latest segment as an update to that speaker's visible slot instead
            # of spending both visual slots on one player.
            item_speaker = (str(getattr(item, "steamid", "")), str(getattr(item, "player_name", "")))
            replaced_same_speaker = False
            for pos, cue in enumerate(stack):
                cue_speaker = (str(getattr(cue, "steamid", "")), str(getattr(cue, "player_name", "")))
                if cue_speaker == item_speaker:
                    stack[pos] = item
                    replaced_same_speaker = True
                    break
            if replaced_same_speaker:
                continue
            if len(stack) >= max_visible:
                stack.pop(0)
            stack.append(item)
    return rendered


def _smooth_short_stack_fragments(items: list[tuple[float, float, str]], min_seconds: float) -> list[tuple[float, float, str]]:
    """Absorb very short stack transition fragments into neighbors.

    Max-2 stack rendering changes text whenever a cue starts or ends. Real ASR
    segments often differ by only a few hundred milliseconds, which would create
    flickery SRT fragments. If a short fragment is a subset of the next or
    previous text, stretch that neighbor across the transition. This slightly
    over-displays an already visible line, but preserves the important rule: no
    delayed new comms and no more than two visible speaker blocks.
    """

    if min_seconds <= 0 or len(items) <= 1:
        return items
    out = list(items)
    changed = True
    while changed:
        changed = False
        result: list[tuple[float, float, str]] = []
        idx = 0
        while idx < len(out):
            start, end, text = out[idx]
            duration = end - start
            prev = result[-1] if result else None
            nxt = out[idx + 1] if idx + 1 < len(out) else None
            if duration < min_seconds:
                # A-only -> A+B: start the next, richer cue a little earlier.
                if nxt is not None and text and text in nxt[2]:
                    out[idx + 1] = (start, nxt[1], nxt[2])
                    changed = True
                    idx += 1
                    continue
                # A+B -> B-only: keep the previous, richer cue a little longer.
                if prev is not None and text and text in prev[2]:
                    result[-1] = (prev[0], end, prev[2])
                    changed = True
                    idx += 1
                    continue
            result.append((start, end, text))
            idx += 1
        out = result
    return out


def render_srt(items, text_fn: Callable, policy: SubtitlePolicy | None = None) -> str:
    lines: list[str] = []
    display_items = apply_subtitle_policy(list(items), policy)
    if policy is not None and policy.overlap_policy == "merge":
        merged_items = _merge_overlapping_items(display_items, text_fn)
        for idx, (start, end, text) in enumerate(merged_items, 1):
            lines.append(str(idx))
            lines.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    if policy is not None and policy.overlap_policy == "stack":
        stacked_items = _stack_visible_items(display_items, text_fn, max_visible=policy.max_visible_cues)
        stacked_items = _smooth_short_stack_fragments(stacked_items, policy.min_stack_fragment_seconds)
        for idx, (start, end, text) in enumerate(stacked_items, 1):
            lines.append(str(idx))
            lines.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    for idx, item in enumerate(display_items, 1):
        lines.append(str(idx))
        lines.append(f"{format_srt_time(item.start_time)} --> {format_srt_time(item.end_time)}")
        lines.append(text_fn(item))
        lines.append("")
    return "\n".join(lines).strip() + "\n"
