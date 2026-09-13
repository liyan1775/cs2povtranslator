from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib

from cs2pov.domain.job import (
    FinalArtifactEntry,
    FinalArtifactKind,
    FinalArtifactTimebase,
    JobPhase,
)
from cs2pov.domain.job_state import advance_job_phase
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.review import DraftCommsTimeline, ReviewedCommsTimeline
from cs2pov.domain.subtitle import (
    SubtitlePolicy,
    bilingual_text,
    compact_bilingual_text,
    debug_translation_text,
    original_text,
    policy_from_preset,
    render_srt,
    voice_activity_text,
    zh_text,
    zh_text_no_player,
)
from cs2pov.domain.voice import VoiceActivityCue


MICROSECONDS_PER_SECOND = 1_000_000


class SubtitlePortError(RuntimeError):
    """Stable application error for current Job subtitle export."""

    def __init__(self, code: str, message_zh: str, suggestion_zh: str, path: str):
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        self.path = path
        super().__init__(message_zh)


@dataclass(frozen=True, slots=True)
class CurrentSubtitleCue:
    """In-memory subtitle projection; durable timeline data remains integer based."""

    cue_id: str
    round_id: str
    player_id: str
    player_name: str
    team_number: int | None
    start_us: int
    end_us: int
    original_text: str
    translated_text: str
    # These are explicit dataclass fields so existing render_srt policy code can
    # use dataclasses.replace(cue, start_time=..., end_time=...). They are an
    # export-only projection; start_us/end_us remain the durable source clock.
    start_time: float | None = None
    end_time: float | None = None

    def __post_init__(self) -> None:
        if self.start_time is None:
            object.__setattr__(self, "start_time", self.start_us / MICROSECONDS_PER_SECOND)
        if self.end_time is None:
            object.__setattr__(self, "end_time", self.end_us / MICROSECONDS_PER_SECOND)

    @property
    def steamid(self) -> str:
        return self.player_id

    @property
    def round_number(self) -> str:
        return self.round_id


@dataclass(frozen=True, slots=True)
class CurrentVoiceActivity:
    activity_id: str
    player_id: str
    player_name: str
    start_us: int
    end_us: int
    packet_count: int
    start_time: float | None = None
    end_time: float | None = None

    def __post_init__(self) -> None:
        if self.start_time is None:
            object.__setattr__(self, "start_time", self.start_us / MICROSECONDS_PER_SECOND)
        if self.end_time is None:
            object.__setattr__(self, "end_time", self.end_us / MICROSECONDS_PER_SECOND)

    @property
    def steamid(self) -> str:
        return self.player_id


@dataclass(slots=True)
class _PolicyCue:
    start_time: float
    end_time: float
    original_text: str = ""
    translated_text: str = ""
    player_name: str = ""
    team_number: int | None = None
    round_number: str = "?"
    steamid: str = ""
    packet_count: int = 0


def microseconds_to_srt_milliseconds(value_us: int) -> int:
    """Convert demo microseconds to SRT milliseconds using half-up rounding."""
    if not isinstance(value_us, int) or isinstance(value_us, bool) or value_us < 0:
        raise ValueError("时间必须是非负整数微秒。")
    return (value_us + 500) // 1000


def format_demo_time_srt(value_us: int) -> str:
    total_ms = microseconds_to_srt_milliseconds(value_us)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _round_seconds_to_us(value: float) -> int:
    """Recover policy-adjusted time in integer microseconds deterministically."""
    return int((Decimal(str(max(0.0, value))) * MICROSECONDS_PER_SECOND).to_integral_value(rounding=ROUND_HALF_UP))


def _player_name(player_id: str, names: Mapping[str, str] | None) -> str:
    return (names or {}).get(player_id, player_id)


def adapt_draft_timeline(
    timeline: DraftCommsTimeline,
    *,
    player_names: Mapping[str, str] | None = None,
    team_numbers: Mapping[str, int | None] | None = None,
) -> tuple[CurrentSubtitleCue, ...]:
    return tuple(
        CurrentSubtitleCue(
            cue.cue_id,
            cue.round_id,
            cue.player_id,
            _player_name(cue.player_id, player_names),
            (team_numbers or {}).get(cue.player_id),
            cue.start_us,
            cue.end_us,
            cue.asr_original,
            cue.translated_zh,
        )
        for cue in timeline.cues
    )


def adapt_reviewed_timeline(
    timeline: ReviewedCommsTimeline,
    *,
    player_names: Mapping[str, str] | None = None,
    team_numbers: Mapping[str, int | None] | None = None,
) -> tuple[CurrentSubtitleCue, ...]:
    return tuple(
        CurrentSubtitleCue(
            cue.cue_id,
            cue.round_id,
            cue.player_id,
            _player_name(cue.player_id, player_names),
            (team_numbers or {}).get(cue.player_id),
            cue.start_us,
            cue.end_us,
            cue.asr_original,
            cue.final_translated_zh,
        )
        for cue in timeline.cues
    )


def adapt_voice_activities(
    activities: Iterable[VoiceActivityCue], *, player_names: Mapping[str, str] | None = None
) -> tuple[CurrentVoiceActivity, ...]:
    return tuple(
        CurrentVoiceActivity(
            activity.activity_id,
            activity.player_id,
            _player_name(activity.player_id, player_names),
            activity.time_range.start_us,
            activity.time_range.end_us,
            activity.packet_count,
        )
        for activity in activities
    )


def _render_with_integer_clock(items: Sequence, text_fn, policy: SubtitlePolicy) -> str:
    # Existing policy code is deliberately reused for overlap, duration and stack
    # semantics. Its temporary float projection never crosses the persistence boundary.
    policy_items = [
        _PolicyCue(
            item.start_time,
            item.end_time,
            getattr(item, "original_text", ""),
            getattr(item, "translated_text", ""),
            getattr(item, "player_name", ""),
            getattr(item, "team_number", None),
            str(getattr(item, "round_number", "?")),
            getattr(item, "steamid", ""),
            getattr(item, "packet_count", 0),
        )
        for item in items
    ]
    def format_policy_time(value: float) -> str:
        return format_demo_time_srt(_round_seconds_to_us(value))

    return render_srt(
        policy_items,
        text_fn,
        policy=policy,
        time_formatter=format_policy_time,
    )


def render_current_srt(
    cues: Sequence[CurrentSubtitleCue],
    fmt: str,
    *,
    preset: str = "review",
    bilingual_format: str = "label",
    policy: SubtitlePolicy | None = None,
) -> str:
    fmt = fmt.strip().lower()
    selected_policy = policy or policy_from_preset(preset)
    if fmt == "bilingual":
        def text_fn(cue):
            return bilingual_text(cue, style=bilingual_format)
    elif fmt == "compact":
        def text_fn(cue):
            return compact_bilingual_text(cue, style=bilingual_format)
    elif fmt == "zh":
        text_fn = zh_text
    elif fmt == "zh_clean":
        text_fn = zh_text_no_player
    elif fmt == "original":
        text_fn = original_text
    elif fmt == "debug":
        text_fn = debug_translation_text
    else:
        raise ValueError(f"未知字幕格式：{fmt}。")
    return _render_with_integer_clock(cues, text_fn, selected_policy)


def render_current_voice_activity_srt(
    activities: Sequence[CurrentVoiceActivity], *, preset: str = "debug", policy: SubtitlePolicy | None = None
) -> str:
    return _render_with_integer_clock(activities, voice_activity_text, policy or policy_from_preset(preset))


def export_current_subtitle_preset(
    timeline: DraftCommsTimeline | ReviewedCommsTimeline,
    preset: str,
    *,
    player_names: Mapping[str, str] | None = None,
    team_numbers: Mapping[str, int | None] | None = None,
    voice_activities: Iterable[VoiceActivityCue] = (),
    bilingual_format: str = "label",
    round_id: str | None = None,
) -> dict[str, str]:
    if isinstance(timeline, DraftCommsTimeline):
        cues = adapt_draft_timeline(timeline, player_names=player_names, team_numbers=team_numbers)
    elif isinstance(timeline, ReviewedCommsTimeline):
        cues = adapt_reviewed_timeline(timeline, player_names=player_names, team_numbers=team_numbers)
    else:
        raise TypeError("timeline 必须是 DraftCommsTimeline 或 ReviewedCommsTimeline。")
    if round_id is not None:
        cues = tuple(cue for cue in cues if cue.round_id == round_id)
    normalized = preset.strip().lower()
    formats = {
        "editing": ("compact", "zh", "bilingual"),
        "review": ("bilingual", "original", "debug"),
        "compact": ("compact",),
        "debug": ("debug", "voice_activity", "original"),
    }
    if normalized not in formats:
        raise ValueError("未知导出预设。可选：editing/review/compact/debug。")
    result: dict[str, str] = {}
    for fmt in formats[normalized]:
        if fmt == "voice_activity":
            activities = adapt_voice_activities(voice_activities, player_names=player_names)
            result[fmt] = render_current_voice_activity_srt(activities)
        else:
            result[fmt] = render_current_srt(cues, fmt, preset=normalized, bilingual_format=bilingual_format)
    return result


def export_current_subtitle_scopes(
    timeline: DraftCommsTimeline | ReviewedCommsTimeline,
    preset: str,
    *,
    player_names: Mapping[str, str] | None = None,
    team_numbers: Mapping[str, int | None] | None = None,
    voice_activities: Iterable[VoiceActivityCue] = (),
    bilingual_format: str = "label",
) -> dict[str, object]:
    """Return one full-demo export and the same export split by round."""
    if isinstance(timeline, DraftCommsTimeline):
        cues = adapt_draft_timeline(timeline, player_names=player_names, team_numbers=team_numbers)
    elif isinstance(timeline, ReviewedCommsTimeline):
        cues = adapt_reviewed_timeline(timeline, player_names=player_names, team_numbers=team_numbers)
    else:
        raise TypeError("timeline 必须是 DraftCommsTimeline 或 ReviewedCommsTimeline。")
    full = export_current_subtitle_preset(
        timeline,
        preset,
        player_names=player_names,
        team_numbers=team_numbers,
        voice_activities=voice_activities,
        bilingual_format=bilingual_format,
    )
    rounds = {
        round_id: export_current_subtitle_preset(
            timeline,
            preset,
            player_names=player_names,
            team_numbers=team_numbers,
            voice_activities=voice_activities,
            bilingual_format=bilingual_format,
            round_id=round_id,
        )
        for round_id in dict.fromkeys(cue.round_id for cue in cues)
    }
    return {"full": full, "rounds": rounds}


@dataclass(frozen=True, slots=True)
class CurrentSubtitleExportReport:
    job_id: str
    source: str
    preset: str
    artifacts: tuple[FinalArtifactEntry, ...]
    job: object


def _next_timestamp(clock, previous: str) -> str:
    try:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("clock must return an aware datetime")
        parsed = datetime.strptime(previous, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        current = value.astimezone(timezone.utc)
        if current <= parsed:
            current = parsed + timedelta(microseconds=1)
        return current.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (OverflowError, TypeError, ValueError) as exc:
        raise SubtitlePortError(
            "pipeline_clock_invalid",
            "当前 Job 时钟返回值无效。",
            "请使用带时区的 UTC 时钟后重试。",
            "job.updated_at",
        ) from exc


def _preset_formats(preset: str) -> tuple[str, ...]:
    values = {
        "editing": ("compact", "zh", "bilingual"),
        "review": ("bilingual", "original", "debug"),
        "compact": ("compact",),
        "debug": ("debug", "voice_activity", "original"),
    }
    try:
        return values[preset.strip().lower()]
    except KeyError as exc:
        raise SubtitlePortError(
            "pipeline_subtitle_preset_invalid",
            "字幕导出预设无效。",
            "请使用 editing、review、compact 或 debug。",
            "subtitle.preset",
        ) from exc


def _timeline_cues(
    timeline: DraftCommsTimeline | ReviewedCommsTimeline,
    *,
    player_names: Mapping[str, str],
    team_numbers: Mapping[str, int | None],
) -> tuple[CurrentSubtitleCue, ...]:
    if isinstance(timeline, DraftCommsTimeline):
        return adapt_draft_timeline(
            timeline, player_names=player_names, team_numbers=team_numbers
        )
    if isinstance(timeline, ReviewedCommsTimeline):
        return adapt_reviewed_timeline(
            timeline, player_names=player_names, team_numbers=team_numbers
        )
    raise TypeError("timeline 必须是 DraftCommsTimeline 或 ReviewedCommsTimeline。")


def _scope_label(
    export_scope: str,
    selected_player_id: str | None,
    selected_team_number: int | None,
) -> str:
    if export_scope == "pov_player":
        return f"player-{selected_player_id}"
    if export_scope == "pov_team":
        return f"team-{selected_team_number}"
    return "combined"


def _filter_current_cues(
    cues: Iterable[CurrentSubtitleCue],
    *,
    export_scope: str,
    selected_player_id: str | None,
    selected_team_number: int | None,
) -> tuple[CurrentSubtitleCue, ...]:
    if export_scope == "pov_player":
        values = [cue for cue in cues if cue.player_id == selected_player_id]
    elif export_scope == "pov_team":
        values = [cue for cue in cues if cue.team_number == selected_team_number]
    else:
        values = list(cues)
    return tuple(sorted(values, key=lambda cue: (cue.start_us, cue.end_us, cue.cue_id)))


def _filter_current_activities(
    activities: Iterable[CurrentVoiceActivity],
    *,
    team_numbers: Mapping[str, int | None],
    export_scope: str,
    selected_player_id: str | None,
    selected_team_number: int | None,
) -> tuple[CurrentVoiceActivity, ...]:
    if export_scope == "pov_player":
        values = [activity for activity in activities if activity.player_id == selected_player_id]
    elif export_scope == "pov_team":
        values = [
            activity
            for activity in activities
            if team_numbers.get(activity.player_id) == selected_team_number
        ]
    else:
        values = list(activities)
    return tuple(sorted(values, key=lambda item: (item.start_us, item.end_us, item.activity_id)))


def _render_current_exports(
    cues: Sequence[CurrentSubtitleCue],
    activities: Sequence[CurrentVoiceActivity],
    preset: str,
    *,
    bilingual_format: str,
) -> dict[str, str]:
    normalized = preset.strip().lower()
    result: dict[str, str] = {}
    for fmt in _preset_formats(normalized):
        if fmt == "voice_activity":
            result[fmt] = render_current_voice_activity_srt(
                activities, preset=normalized
            )
        else:
            result[fmt] = render_current_srt(
                cues,
                fmt,
                preset=normalized,
                bilingual_format=bilingual_format,
            )
    return result


def _round_activities(
    activities: Sequence[CurrentVoiceActivity],
    round_start_us: int,
    round_end_us: int,
) -> tuple[CurrentVoiceActivity, ...]:
    return tuple(
        activity
        for activity in activities
        if activity.start_us < round_end_us and activity.end_us > round_start_us
    )


def _rebase_cues(
    cues: Iterable[CurrentSubtitleCue], round_start_us: int, round_end_us: int
) -> tuple[CurrentSubtitleCue, ...]:
    result: list[CurrentSubtitleCue] = []
    for cue in cues:
        start_us = max(round_start_us, cue.start_us)
        end_us = min(round_end_us, cue.end_us)
        if end_us <= start_us:
            continue
        result.append(
            CurrentSubtitleCue(
                cue.cue_id,
                cue.round_id,
                cue.player_id,
                cue.player_name,
                cue.team_number,
                start_us - round_start_us,
                end_us - round_start_us,
                cue.original_text,
                cue.translated_text,
            )
        )
    return tuple(result)


def _rebase_activities(
    activities: Iterable[CurrentVoiceActivity], round_start_us: int, round_end_us: int
) -> tuple[CurrentVoiceActivity, ...]:
    result: list[CurrentVoiceActivity] = []
    for activity in activities:
        start_us = max(round_start_us, activity.start_us)
        end_us = min(round_end_us, activity.end_us)
        if end_us <= start_us:
            continue
        result.append(
            CurrentVoiceActivity(
                activity.activity_id,
                activity.player_id,
                activity.player_name,
                start_us - round_start_us,
                end_us - round_start_us,
                activity.packet_count,
            )
        )
    return tuple(result)


def _artifact_slug(value: str) -> str:
    normalized = "".join(
        char if char.isascii() and (char.isalnum() or char == "-") else "-"
        for char in value.lower()
    )
    normalized = "-".join(part for part in normalized.split("-") if part)
    return normalized[:48] or "export"


class CurrentJobSubtitleApplicationService:
    """Export current Draft/Reviewed timelines through the legacy strategies."""

    def __init__(self, repository: object, *, claim_lease_us: int = 60_000_000) -> None:
        required_methods = (
            "load_job",
            "load_language_graph",
            "load_draft_timeline",
            "load_reviewed_timeline",
            "load_voice_activities",
            "acquire_write",
            "publish_final_artifacts",
        )
        if any(not callable(getattr(repository, name, None)) for name in required_methods):
            raise TypeError("repository 不符合当前字幕导出 Job 接口。")
        if not callable(getattr(repository, "clock", None)):
            raise TypeError("repository 必须提供可调用的 clock。")
        if type(claim_lease_us) is not int or claim_lease_us <= 0:
            raise ValueError("claim_lease_us 必须为正整数。")
        self.repository = repository
        self.claim_lease_us = claim_lease_us

    def export(
        self,
        job_id: str,
        *,
        source: str = "draft",
        preset: str = "editing",
        export_scope: str = "all",
        selected_player_id: str | None = None,
        selected_team_number: int | None = None,
        bilingual_format: str = "label",
    ) -> CurrentSubtitleExportReport:
        normalized_source = source.strip().lower()
        if normalized_source not in {"draft", "reviewed"}:
            raise SubtitlePortError(
                "pipeline_subtitle_source_invalid",
                "字幕来源时间线无效。",
                "请使用 draft 或 reviewed。",
                "subtitle.source",
            )
        normalized_scope = export_scope.strip().lower()
        if normalized_scope not in {"all", "pov_player", "pov_team"}:
            raise SubtitlePortError(
                "pipeline_subtitle_scope_invalid",
                "字幕导出范围无效。",
                "请使用 all、pov_player 或 pov_team。",
                "subtitle.export_scope",
            )

        opened = self.repository.load_job(job_id)
        initial_manifest_fingerprint = opened.manifest.content_fingerprint()
        timeline = (
            self.repository.load_draft_timeline(job_id)
            if normalized_source == "draft"
            else self.repository.load_reviewed_timeline(job_id)
        )
        language = self.repository.load_language_graph(job_id)
        player_names = {
            player.player_id: player.display_name
            for player in language.timeline.descriptor.players
        }
        team_numbers = {
            player.player_id: player.team_number
            for player in language.timeline.descriptor.players
        }
        if normalized_scope == "pov_player":
            selected_player_id = selected_player_id or opened.manifest.target_player_id
            if not selected_player_id:
                raise SubtitlePortError(
                    "pipeline_subtitle_scope_invalid",
                    "POV 玩家范围缺少玩家标识。",
                    "请传入 selected_player_id 或先在 Job 中设置目标玩家。",
                    "subtitle.selected_player_id",
                )
        if normalized_scope == "pov_team" and selected_team_number is None:
            if selected_player_id or opened.manifest.target_player_id:
                player_id = selected_player_id or opened.manifest.target_player_id
                selected_team_number = team_numbers.get(player_id)
            if selected_team_number is None:
                raise SubtitlePortError(
                    "pipeline_subtitle_scope_invalid",
                    "POV 队伍范围缺少队伍标识。",
                    "请传入 selected_team_number 或设置目标玩家。",
                    "subtitle.selected_team_number",
                )
        cues = _filter_current_cues(
            _timeline_cues(
                timeline,
                player_names=player_names,
                team_numbers=team_numbers,
            ),
            export_scope=normalized_scope,
            selected_player_id=selected_player_id,
            selected_team_number=selected_team_number,
        )
        activities = _filter_current_activities(
            adapt_voice_activities(
                self.repository.load_voice_activities(job_id),
                player_names=player_names,
            ),
            team_numbers=team_numbers,
            export_scope=normalized_scope,
            selected_player_id=selected_player_id,
            selected_team_number=selected_team_number,
        )
        normalized_preset = preset.strip().lower()
        full_exports = _render_current_exports(
            cues,
            activities,
            normalized_preset,
            bilingual_format=bilingual_format,
        )
        round_values = {
            round_value.round_id: round_value
            for round_value in language.timeline.rounds.rounds
        }
        round_exports: dict[str, dict[str, str]] = {}
        for round_id, round_value in round_values.items():
            round_cues = _rebase_cues(
                (cue for cue in cues if cue.round_id == round_id),
                round_value.time_range.start_us,
                round_value.time_range.end_us,
            )
            round_activities = _rebase_activities(
                _round_activities(
                    activities,
                    round_value.time_range.start_us,
                    round_value.time_range.end_us,
                ),
                round_value.time_range.start_us,
                round_value.time_range.end_us,
            )
            round_exports[round_id] = _render_current_exports(
                round_cues,
                round_activities,
                normalized_preset,
                bilingual_format=bilingual_format,
            )

        timeline_fingerprint = content_fingerprint(timeline.to_dict())[:16]
        scope_label = _artifact_slug(
            _scope_label(normalized_scope, selected_player_id, selected_team_number)
        )
        payloads: dict[str, bytes] = {}
        entries: list[FinalArtifactEntry] = []

        def add_export(relative_path: str, fmt: str, text: str, round_id: str | None) -> None:
            payload = text.encode("utf-8")
            artifact_id = _artifact_slug(
                f"subtitle-{normalized_source}-{normalized_preset}-{scope_label}-"
                f"{round_id or 'full'}-{fmt}-{timeline_fingerprint}"
            )
            entry = FinalArtifactEntry(
                artifact_id,
                FinalArtifactKind.SUBTITLE,
                relative_path,
                hashlib.sha256(payload).hexdigest(),
                round_id,
                FinalArtifactTimebase.ROUND_LOCAL
                if round_id is not None
                else FinalArtifactTimebase.DEMO_GLOBAL,
            )
            entries.append(entry)
            payloads[relative_path] = payload

        for fmt, text in full_exports.items():
            add_export(
                f"final/subtitles/{normalized_source}.{normalized_preset}.{scope_label}.full.{fmt}.{timeline_fingerprint}.srt",
                fmt,
                text,
                None,
            )
        for round_id, exports in round_exports.items():
            for fmt, text in exports.items():
                add_export(
                    f"final/subtitles/{normalized_source}.{normalized_preset}.{scope_label}.round-{round_id}.{fmt}.{timeline_fingerprint}.srt",
                    fmt,
                    text,
                    round_id,
                )

        with self.repository.acquire_write(
            job_id, lease_us=self.claim_lease_us
        ) as session:
            current = self.repository.load_job(job_id)
            if current.manifest.content_fingerprint() != initial_manifest_fingerprint:
                raise SubtitlePortError(
                    "pipeline_job_changed",
                    "字幕导出期间 Job 已发生变化。",
                    "请重新打开 Job 后重试。",
                    "job.json",
                )
            current_by_id = {item.artifact_id: item for item in current.manifest.final_artifacts}
            merged_artifacts = tuple(
                current_by_id.get(item.artifact_id, item)
                for item in (*current.manifest.final_artifacts, *entries)
            )
            # The expression above preserves the current order and appends only
            # genuinely new entries; deterministic IDs make re-export idempotent.
            deduplicated: list[FinalArtifactEntry] = []
            seen_ids: set[str] = set()
            for item in merged_artifacts:
                if item.artifact_id not in seen_ids:
                    deduplicated.append(item)
                    seen_ids.add(item.artifact_id)
            updated_at = _next_timestamp(self.repository.clock, current.manifest.updated_at)
            if (
                normalized_source == "reviewed"
                and current.manifest.phase is JobPhase.FINAL_TIMELINE_READY
            ):
                candidate = advance_job_phase(
                    current.manifest,
                    JobPhase.SUBTITLES_EXPORTED,
                    at=updated_at,
                )
                candidate = replace(candidate, final_artifacts=tuple(deduplicated))
            else:
                candidate = replace(
                    current.manifest,
                    updated_at=updated_at,
                    final_artifacts=tuple(deduplicated),
                )
            self.repository.publish_final_artifacts(
                job_id,
                tuple(entries),
                payloads,
                current.manifest.content_fingerprint(),
                candidate,
                session.claim,
            )
        return CurrentSubtitleExportReport(
            job_id,
            normalized_source,
            normalized_preset,
            tuple(entries),
            self.repository.load_job(job_id),
        )
