from __future__ import annotations

from cs2pov.domain.models import TranslationSegment, TranscriptSegment, VoiceActivityCue, translation_from_dict, transcript_from_dict
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
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_jsonl
from cs2pov.services.player_alias_service import apply_player_aliases


class SubtitleService:
    def export(
        self,
        store: ArtifactStore,
        selected_team_number: int | None,
        selected_pov_steamid: str | None,
        export_scope: str,
        bilingual_format: str = "label",
        preset: str | None = None,
        overlap_policy: str | None = None,
        max_duration_seconds: float | None = None,
        min_duration_seconds: float | None = None,
    ) -> dict[str, str]:
        outputs: dict[str, str] = {}
        policy = policy_from_preset(preset or "review", overlap_policy=overlap_policy, max_duration_seconds=max_duration_seconds, min_duration_seconds=min_duration_seconds)
        outputs.update(self.export_format(store, "bilingual", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
        outputs.update(self.export_format(store, "original", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
        outputs.update(self.export_format(store, "zh", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
        outputs.update(self.export_format(store, "compact", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
        outputs.update(self.export_format(store, "debug", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy_from_preset("debug")))
        outputs.update(self.export_format(store, "voice", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy_from_preset("debug")))
        return outputs

    def export_preset(
        self,
        store: ArtifactStore,
        preset: str,
        selected_team_number: int | None,
        selected_pov_steamid: str | None,
        export_scope: str,
        bilingual_format: str = "label",
        overlap_policy: str | None = None,
        max_duration_seconds: float | None = None,
        min_duration_seconds: float | None = None,
    ) -> dict[str, str]:
        preset = preset.strip().lower()
        policy = policy_from_preset(preset, overlap_policy=overlap_policy, max_duration_seconds=max_duration_seconds, min_duration_seconds=min_duration_seconds)
        outputs: dict[str, str] = {}
        if preset == "editing":
            # Practical editing exports: bilingual-first for the user's preferred POV workflow,
            # plus compact bilingual and Chinese-only fallback exports.
            outputs.update(self.export_format(store, "compact", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            outputs.update(self.export_format(store, "zh", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            outputs.update(self.export_format(store, "bilingual", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            return outputs
        if preset == "review":
            outputs.update(self.export_format(store, "bilingual", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            outputs.update(self.export_format(store, "original", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            outputs.update(self.export_format(store, "debug", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy_from_preset("debug")))
            return outputs
        if preset == "debug":
            outputs.update(self.export_format(store, "debug", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            outputs.update(self.export_format(store, "voice", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            outputs.update(self.export_format(store, "original", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            return outputs
        if preset == "compact":
            outputs.update(self.export_format(store, "compact", selected_team_number, selected_pov_steamid, export_scope, bilingual_format, policy=policy))
            return outputs
        raise ValueError(f"未知导出预设：{preset}。可选：editing/review/compact/debug。")

    def export_format(
        self,
        store: ArtifactStore,
        fmt: str,
        selected_team_number: int | None,
        selected_pov_steamid: str | None,
        export_scope: str,
        bilingual_format: str = "label",
        policy: SubtitlePolicy | None = None,
    ) -> dict[str, str]:
        fmt = fmt.lower().strip()
        label = _label(selected_team_number, selected_pov_steamid, export_scope)
        if fmt == "bilingual":
            translations = apply_player_aliases(store, _filter([translation_from_dict(row) for row in read_jsonl(store.translations_path)], selected_team_number, selected_pov_steamid, export_scope))
            path = store.final_dir / f"{label}.bilingual.srt"
            path.write_text(render_srt(translations, lambda seg: bilingual_text(seg, style=bilingual_format), policy=policy), encoding="utf-8")
            return {"bilingual_srt": str(path)}
        if fmt == "compact":
            translations = apply_player_aliases(store, _filter([translation_from_dict(row) for row in read_jsonl(store.translations_path)], selected_team_number, selected_pov_steamid, export_scope))
            path = store.final_dir / f"{label}.compact.srt"
            compact_policy = policy or policy_from_preset("compact")
            path.write_text(render_srt(translations, lambda seg: compact_bilingual_text(seg, style=bilingual_format), policy=compact_policy), encoding="utf-8")
            return {"compact_srt": str(path)}
        if fmt == "zh":
            translations = apply_player_aliases(store, _filter([translation_from_dict(row) for row in read_jsonl(store.translations_path)], selected_team_number, selected_pov_steamid, export_scope))
            path = store.final_dir / f"{label}.zh.srt"
            path.write_text(render_srt(translations, zh_text, policy=policy), encoding="utf-8")
            # Keep the historical review copy too, so old workflows do not break.
            review_path = store.review_dir / f"{label}.zh.srt"
            review_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            return {"zh_srt": str(path)}
        if fmt == "zh_clean":
            translations = apply_player_aliases(store, _filter([translation_from_dict(row) for row in read_jsonl(store.translations_path)], selected_team_number, selected_pov_steamid, export_scope))
            path = store.final_dir / f"{label}.zh_clean.srt"
            path.write_text(render_srt(translations, zh_text_no_player, policy=policy), encoding="utf-8")
            return {"zh_clean_srt": str(path)}
        if fmt == "original":
            transcripts = apply_player_aliases(store, _filter([transcript_from_dict(row) for row in read_jsonl(store.transcripts_path)], selected_team_number, selected_pov_steamid, export_scope))
            path = store.review_dir / f"{label}.original.srt"
            path.write_text(render_srt(transcripts, original_text, policy=policy), encoding="utf-8")
            return {"original_srt": str(path)}
        if fmt == "debug":
            translations = apply_player_aliases(store, _filter([translation_from_dict(row) for row in read_jsonl(store.translations_path)], selected_team_number, selected_pov_steamid, export_scope))
            path = store.debug_dir / f"{label}.debug.srt"
            path.write_text(render_srt(translations, debug_translation_text, policy=policy), encoding="utf-8")
            return {"debug_srt": str(path)}
        if fmt in {"voice", "voice_activity"}:
            voice_cues = apply_player_aliases(store, _filter([_voice_from_row(row) for row in read_jsonl(store.voice_activity_path)], selected_team_number, selected_pov_steamid, export_scope))
            path = store.debug_dir / f"{label}.voice_activity.srt"
            path.write_text(render_srt(voice_cues, voice_activity_text, policy=policy), encoding="utf-8")
            return {"voice_activity_srt": str(path)}
        raise ValueError(f"未知导出格式：{fmt}。可选：all/bilingual/compact/zh/zh_clean/original/debug/voice。")


def _label(selected_team_number: int | None, selected_pov_steamid: str | None, export_scope: str) -> str:
    if export_scope == "pov_player" and selected_pov_steamid:
        return f"player_{selected_pov_steamid}"
    if export_scope == "all" or selected_team_number is None:
        return "combined"
    return f"team_{selected_team_number}"


def _filter(items, team_number, pov_steamid, export_scope):
    if export_scope == "all":
        return sorted(items, key=lambda x: (x.start_time, x.end_time))
    if export_scope == "pov_player" and pov_steamid:
        return sorted([x for x in items if x.steamid == pov_steamid], key=lambda x: (x.start_time, x.end_time))
    if team_number is not None:
        return sorted([x for x in items if x.team_number == team_number], key=lambda x: (x.start_time, x.end_time))
    return sorted(items, key=lambda x: (x.start_time, x.end_time))


def _voice_from_row(row):
    return VoiceActivityCue(
        id=str(row["id"]), steamid=str(row["steamid"]), player_name=str(row["player_name"]),
        team_number=row.get("team_number"), start_time=float(row["start_time"]), end_time=float(row["end_time"]),
        packet_count=int(row.get("packet_count", 0)),
    )
