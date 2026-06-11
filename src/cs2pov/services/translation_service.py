from __future__ import annotations

import json
from typing import Any

from cs2pov.adapters.llm_adapter import OpenAICompatibleLLM, LLMAdapterError
from cs2pov.domain.models import RoundContext, TranslationSegment, transcript_from_dict
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.services.transcription_service import UNRECOGNIZED_TEXT
from cs2pov.services.dictionary_service import (
    build_glossary_used_report,
    build_glossary_warning_report,
    format_glossary_for_prompt,
    validate_translation_terms,
)
from cs2pov.storage.jsonl import read_jsonl, write_json, write_jsonl


SYSTEM_PROMPT = """你是一个熟悉 CS2、FPS 报点和中文电竞字幕的翻译助手。
任务：把 CS2 队内语音转成适合 POV 视频剪辑的中文字幕。
要求：
1. 原文可能是英语、俄语、夹杂缩写、报点、脏话、残缺短句。
2. 不要逐字硬翻，优先让中国 CS2 玩家看懂。
3. 地图报点尽量使用中文玩家常见说法；不确定时保留英文报点。
4. 若 payload 中提供 glossary，请优先遵守 glossary 的 zh 字段；若 glossary 标记 medium/low confidence 且上下文不确定，可以保留英文并给出自然中文。
5. 不要翻译玩家名、SteamID、队名、武器皮肤名。
6. 保持简短，适合字幕显示。
7. 必须返回 JSON：{"translations":[{"id":"...","translated_text":"..."}]}。
"""


class TranslationService:
    def translate_rounds(
        self,
        store: ArtifactStore,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        map_name: str | None,
        timeout_seconds: int = 60,
        dry_run: bool = False,
        skip_translation: bool = False,
        glossary_enabled: bool = True,
        progress_callback=None,
    ) -> list[TranslationSegment]:
        rows = read_jsonl(store.round_contexts_path)
        contexts = [_context_from_row(row) for row in rows]
        all_texts = [seg.original_text for ctx in contexts for seg in ctx.segments]
        glossary_payload = format_glossary_for_prompt(map_name, all_texts) if glossary_enabled else []
        write_json(store.glossary_used_path, build_glossary_used_report(map_name, all_texts) | {"enabled": bool(glossary_enabled), "prompt_terms": glossary_payload})

        results: list[TranslationSegment] = []
        glossary_warnings: list[dict[str, Any]] = []
        llm = None
        if not skip_translation and not dry_run and base_url and api_key and model:
            llm = OpenAICompatibleLLM(base_url=base_url, api_key=api_key, model=model, timeout_seconds=timeout_seconds)

        for idx, ctx in enumerate(contexts, 1):
            if progress_callback:
                progress_callback(f"翻译中... Round {ctx.round_number}（{idx}/{len(contexts)}）")
            fixed = {seg.id: UNRECOGNIZED_TEXT for seg in ctx.segments if seg.original_text.strip() == UNRECOGNIZED_TEXT or seg.id.startswith("unrec_")}
            translatable = [seg for seg in ctx.segments if seg.id not in fixed]
            if llm is None:
                reason = "dry_run" if dry_run else ("skipped" if skip_translation else "unconfigured")
                translated = {seg.id: _fallback_translation(seg.original_text, reason=reason) for seg in translatable}
            else:
                translated = self._translate_one_round(
                    llm,
                    RoundContext(ctx.round_number, ctx.start_time, ctx.end_time, translatable),
                    map_name,
                    glossary_payload,
                ) if translatable else {}
            translated.update(fixed)
            for seg in ctx.segments:
                text = translated.get(seg.id) or _fallback_translation(seg.original_text, reason="llm_failed")
                warnings: list[str] = []
                if text.startswith("[未翻译："):
                    warnings.append("translation_unavailable")
                if llm is None:
                    warnings.append("translation_skipped_or_dry_run")
                term_warnings = validate_translation_terms(seg.original_text, text, map_name) if glossary_enabled else []
                if term_warnings:
                    warnings.append("glossary_term_not_reflected")
                    for warning in term_warnings:
                        warning = dict(warning)
                        warning["segment_id"] = seg.id
                        warning["player_name"] = seg.player_name
                        warning["round_number"] = seg.round_number
                        glossary_warnings.append(warning)
                results.append(TranslationSegment(
                    id=seg.id,
                    steamid=seg.steamid,
                    player_name=seg.player_name,
                    team_number=seg.team_number,
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    original_text=seg.original_text,
                    translated_text=text,
                    round_number=seg.round_number,
                    warnings=warnings,
                ))
        results.sort(key=lambda s: (s.start_time, s.end_time, s.player_name))
        write_jsonl(store.translations_path, results)
        write_json(store.glossary_warnings_path, build_glossary_warning_report(map_name, glossary_warnings) | {"enabled": bool(glossary_enabled)})
        return results

    def _translate_one_round(self, llm: OpenAICompatibleLLM, ctx: RoundContext, map_name: str | None, glossary_payload: list[dict[str, Any]]) -> dict[str, str]:
        payload = {
            "map_name": map_name,
            "glossary_policy": {
                "enabled": bool(glossary_payload),
                "note": "glossary 包含 global CS2 通用术语和地图报点；若 ASR 把普通词误识别成术语，不要硬套。",
            },
            "glossary": glossary_payload,
            "round_number": ctx.round_number,
            "segments": [
                {"id": s.id, "player": s.player_name, "time": round(s.start_time, 2), "text": s.original_text}
                for s in ctx.segments
            ],
        }
        user_prompt = "请翻译这个回合内的队内语音，按 id 返回翻译。优先遵守 glossary 的推荐译法和 avoid 禁忌误译，但不要为了术语牺牲自然字幕。\n" + json.dumps(payload, ensure_ascii=False)
        for _attempt in range(2):
            try:
                data = llm.chat_json(SYSTEM_PROMPT, user_prompt)
                items = data.get("translations", []) if isinstance(data, dict) else []
                translated = {str(item.get("id")): str(item.get("translated_text", "")).strip() for item in items if item.get("id")}
                return translated
            except LLMAdapterError:
                pass
        return {s.id: _fallback_translation(s.original_text, reason="llm_failed") for s in ctx.segments}


def _context_from_row(row: dict[str, Any]) -> RoundContext:
    from cs2pov.domain.models import RoundContext
    return RoundContext(
        round_number=int(row["round_number"]),
        start_time=float(row["start_time"]),
        end_time=float(row["end_time"]),
        segments=[transcript_from_dict(x) for x in row.get("segments", [])],
    )


def _fallback_translation(text: str, reason: str = "unconfigured") -> str:
    if reason == "dry_run":
        return f"[演示翻译] {text}"
    if reason == "skipped":
        return "[未翻译：已跳过翻译]"
    if reason == "llm_failed":
        return "[未翻译：LLM 调用失败，请稍后重试该回合]"
    return "[未翻译：未配置 LLM]"
