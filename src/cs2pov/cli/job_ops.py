from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from cs2pov.domain.models import PipelineConfig, StageName, StageStatus
from cs2pov.domain.subtitle import policy_from_preset
from cs2pov.pipeline.engine import PipelineEngine
from cs2pov.pipeline.manifest import PipelineManifest, REDACTED_SECRET
from cs2pov.services.subtitle_service import SubtitleService
from cs2pov.services.translation_service import TranslationService
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.config_store import load_config, mask_config_for_display
from cs2pov.storage.jsonl import read_json, read_jsonl, write_json


def resolve_job_dir(path: Path) -> Path | None:
    """Resolve either a job directory or an output root to the latest job."""
    path = path.expanduser().resolve()
    if (path / "manifest.json").exists():
        return path
    if not path.exists() or not path.is_dir():
        return None
    jobs = [p for p in path.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    if not jobs:
        return None
    # Directory mtimes can be equal on coarse filesystems.  The canonical
    # name tie-breaker keeps read-only "latest job" selection deterministic.
    return max(jobs, key=lambda p: (p.stat().st_mtime_ns, p.name.casefold(), p.name))


def inspect_job(path: Path) -> dict[str, Any]:
    job_dir = resolve_job_dir(path)
    if job_dir is None:
        raise FileNotFoundError(f"找不到 Job 目录：{path}")
    store = ArtifactStore(job_dir)
    manifest = _safe_json(store.manifest_path)
    demo_info = _safe_json(store.demo_info_path)
    coverage = _safe_json(store.transcription_coverage_path)
    glossary_used = _safe_json(store.glossary_used_path)
    glossary_warnings = _safe_json(store.glossary_warnings_path)
    rounds = _safe_json(store.rounds_path, default=[])
    voice_manifest = _safe_json(store.voice_manifest_path)
    player_aliases = _safe_json(store.player_aliases_path)
    translations = read_jsonl(store.translations_path)
    transcripts = read_jsonl(store.transcripts_path)
    contexts = read_jsonl(store.round_contexts_path)
    subtitle_files = sorted(
        [p for folder in [store.final_dir, store.review_dir, store.debug_dir] if folder.exists() for p in folder.glob("*.srt")]
    )
    comms_files = sorted(
        [
            p
            for folder in [store.final_dir / "comms_feed", store.review_dir / "comms_rounds", store.final_dir / "comms_overlay"]
            if folder.exists()
            for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in {".json", ".md", ".html", ".yaml", ".yml", ".png", ".mp4", ".mov"}
        ]
    )
    stages = manifest.get("stages", {}) if isinstance(manifest, dict) else {}
    failed_stages = [name for name, status in stages.items() if status == StageStatus.FAILED.value]
    pending_stages = [name for name, status in stages.items() if status == StageStatus.PENDING.value]
    cfg = manifest.get("config", {}) if isinstance(manifest, dict) else {}
    has_secret_leak = _contains_secret(manifest)
    return {
        "job_dir": str(job_dir),
        "job_id": manifest.get("job_id", job_dir.name) if isinstance(manifest, dict) else job_dir.name,
        "map_name": (demo_info or {}).get("map_name") or cfg.get("map_name"),
        "server_name": (demo_info or {}).get("server_name"),
        "selected_team_number": cfg.get("selected_team_number"),
        "selected_pov_steamid": cfg.get("selected_pov_steamid"),
        "export_scope": cfg.get("export_scope"),
        "whisper_model": cfg.get("whisper_model"),
        "transcription_mode": cfg.get("transcription_mode"),
        "llm_model": cfg.get("llm_model"),
        "stages": stages,
        "failed_stages": failed_stages,
        "pending_stages": pending_stages,
        "rounds": len(rounds) if isinstance(rounds, list) else 0,
        "players_with_voice": len((voice_manifest or {}).get("players", [])) if isinstance(voice_manifest, dict) else 0,
        "player_alias_count": len((player_aliases or {}).get("aliases", {})) if isinstance(player_aliases, dict) else 0,
        "transcript_segments": len(transcripts),
        "round_contexts": len(contexts),
        "translation_segments": len(translations),
        "coverage": coverage if isinstance(coverage, dict) else {},
        "glossary_used": glossary_used if isinstance(glossary_used, dict) else {},
        "glossary_warnings": glossary_warnings if isinstance(glossary_warnings, dict) else {},
        "subtitle_files": [p.relative_to(job_dir).as_posix() for p in subtitle_files],
        "comms_files": [p.relative_to(job_dir).as_posix() for p in comms_files],
        "has_secret_leak": has_secret_leak,
        "recommended_next_commands": _recommended_next_commands(job_dir, failed_stages, pending_stages, len(translations), len(transcripts), [p.relative_to(job_dir).as_posix() for p in comms_files]),
    }


def print_job_inspection(summary: dict[str, Any]) -> None:
    print("CS2 POV Translator Job 诊断")
    print("=" * 72)
    print(f"Job:        {summary['job_dir']}")
    print(f"地图:       {summary.get('map_name') or '[未知]'}")
    print(f"服务器:     {summary.get('server_name') or '[未知]'}")
    print(f"选择队伍:   {summary.get('selected_team_number') or '[未设置]'}")
    print(f"导出范围:   {summary.get('export_scope') or '[未设置]'}")
    print(f"Whisper:    {summary.get('whisper_model') or '[未知]'} / {summary.get('transcription_mode') or '[未知]'}")
    print(f"LLM:        {summary.get('llm_model') or '[未配置]'}")
    if summary.get("has_secret_leak"):
        print("\n[警告] manifest 中疑似包含明文 API key，请立即轮换 key 并重新打包反馈。")
    print("\n阶段状态：")
    for name, status in summary.get("stages", {}).items():
        marker = "OK" if status == "completed" else ("FAIL" if status == "failed" else "...")
        print(f"  {marker:<4} {name:<22} {status}")
    print("\n产物统计：")
    print(f"  players_with_voice: {summary.get('players_with_voice')}")
    print(f"  player_alias_count: {summary.get('player_alias_count')}")
    print(f"  rounds:             {summary.get('rounds')}")
    print(f"  transcript_segments:{summary.get('transcript_segments')}")
    print(f"  round_contexts:     {summary.get('round_contexts')}")
    print(f"  translation_segments:{summary.get('translation_segments')}")
    cov = summary.get("coverage") or {}
    if cov:
        print("\n转录覆盖参考：")
        for key in [
            "coverage_ratio_before_postprocess",
            "coverage_ratio_after_postprocess",
            "longest_transcript_segment_seconds",
            "long_transcript_segments_gt_30s",
            "filtered_hallucination_segments_after_rebase",
        ]:
            if key in cov:
                print(f"  {key}: {cov[key]}")
    glossary_used = summary.get("glossary_used") or {}
    if glossary_used:
        print("\n地图词典：")
        print(f"  enabled: {glossary_used.get('enabled')}")
        print(f"  supported: {glossary_used.get('supported')}")
        print(f"  term_count: {glossary_used.get('term_count')}")
        print(f"  matched_term_count: {glossary_used.get('matched_term_count')}")
        gw = summary.get("glossary_warnings") or {}
        if gw:
            print(f"  warning_count: {gw.get('warning_count')}")

    print("\n字幕文件：")
    files = summary.get("subtitle_files") or []
    if files:
        for f in files:
            print(f"  - {f}")
    else:
        print("  [尚未导出 SRT]")
    comms_files = summary.get("comms_files") or []
    print("\nComms Overlay / 通讯流文件：")
    if comms_files:
        for f in comms_files[:16]:
            print(f"  - {f}")
        if len(comms_files) > 16:
            print(f"  ... 还有 {len(comms_files) - 16} 个文件")
    else:
        print("  [尚未生成 Comms Feed；可运行 cs2pov comms build-review]")
    print("\n建议下一步：")
    for cmd in summary.get("recommended_next_commands", []):
        print(f"  {cmd}")


def export_job(
    path: Path,
    fmt: str = "all",
    team_number: int | None = None,
    pov_steamid: str | None = None,
    export_scope: str | None = None,
    bilingual_format: str | None = None,
    preset: str | None = None,
    overlap_policy: str | None = None,
    max_duration_seconds: float | None = None,
    min_duration_seconds: float | None = None,
) -> dict[str, str]:
    job_dir = _require_job(path)
    store = ArtifactStore(job_dir)
    cfg = _load_job_config_with_runtime_secrets(job_dir)
    if team_number is not None:
        cfg.selected_team_number = team_number
    if pov_steamid is not None:
        cfg.selected_pov_steamid = pov_steamid
    if export_scope is not None:
        cfg.export_scope = export_scope
    if bilingual_format is not None:
        cfg.subtitle_bilingual_format = bilingual_format
    if preset is not None:
        cfg.subtitle_export_preset = preset
    if overlap_policy is not None:
        cfg.subtitle_overlap_policy = overlap_policy
    if min_duration_seconds is not None:
        cfg.subtitle_min_duration_seconds = min_duration_seconds
    if max_duration_seconds is not None:
        cfg.max_subtitle_segment_seconds = max_duration_seconds
    service = SubtitleService()
    if preset:
        outputs = service.export_preset(
            store, preset, cfg.selected_team_number, cfg.selected_pov_steamid, cfg.export_scope, cfg.subtitle_bilingual_format,
            overlap_policy=overlap_policy, max_duration_seconds=max_duration_seconds, min_duration_seconds=min_duration_seconds,
        )
    elif fmt == "all":
        outputs = service.export(
            store, cfg.selected_team_number, cfg.selected_pov_steamid, cfg.export_scope, cfg.subtitle_bilingual_format,
            preset=cfg.subtitle_export_preset, overlap_policy=cfg.subtitle_overlap_policy,
            max_duration_seconds=cfg.max_subtitle_segment_seconds, min_duration_seconds=cfg.subtitle_min_duration_seconds,
        )
    else:
        if fmt in {"debug", "voice"}:
            export_policy = policy_from_preset("debug")
        else:
            export_policy = policy_from_preset(
                preset or cfg.subtitle_export_preset,
                overlap_policy=cfg.subtitle_overlap_policy,
                max_duration_seconds=cfg.max_subtitle_segment_seconds,
                min_duration_seconds=cfg.subtitle_min_duration_seconds,
            )
        outputs = service.export_format(
            store, fmt, cfg.selected_team_number, cfg.selected_pov_steamid, cfg.export_scope, cfg.subtitle_bilingual_format,
            policy=export_policy,
        )
    _update_manifest_config_and_artifacts(store, cfg, outputs)
    return outputs


def retranslate_job(
    path: Path,
    dry_run: bool = False,
    skip_translation: bool = False,
    model: str | None = None,
    base_url: str | None = None,
    export_after: bool = True,
) -> dict[str, str]:
    job_dir = _require_job(path)
    store = ArtifactStore(job_dir)
    cfg = _load_job_config_with_runtime_secrets(job_dir)
    runtime = load_config()
    cfg.llm_base_url = base_url or runtime.get("llm_base_url") or cfg.llm_base_url
    cfg.llm_api_key = runtime.get("llm_api_key") or cfg.llm_api_key
    cfg.llm_model = model or runtime.get("llm_model") or cfg.llm_model
    cfg.dry_run_translation = dry_run
    cfg.skip_translation = skip_translation
    TranslationService().translate_rounds(
        store,
        base_url=cfg.llm_base_url,
        api_key=cfg.llm_api_key,
        model=cfg.llm_model,
        map_name=cfg.map_name,
        timeout_seconds=cfg.llm_timeout_seconds,
        dry_run=dry_run,
        skip_translation=skip_translation,
        glossary_enabled=cfg.glossary_enabled,
    )
    outputs: dict[str, str] = {"translations": str(store.translations_path)}
    if export_after:
        outputs.update(SubtitleService().export(
            store, cfg.selected_team_number, cfg.selected_pov_steamid, cfg.export_scope, cfg.subtitle_bilingual_format,
            preset=cfg.subtitle_export_preset, overlap_policy=cfg.subtitle_overlap_policy,
            max_duration_seconds=cfg.max_subtitle_segment_seconds, min_duration_seconds=cfg.subtitle_min_duration_seconds,
        ))
    _update_manifest_config_and_artifacts(store, cfg, outputs)
    return outputs


def resume_job(path: Path, from_stage: StageName, to_stage: StageName | None = None, demo_path: Path | None = None) -> Path:
    job_dir = _require_job(path)
    store = ArtifactStore(job_dir)
    manifest = PipelineManifest.load(store.manifest_path)
    cfg = _merge_runtime_config(manifest.config)
    cfg.output_root = str(job_dir.parent)
    cfg.job_id = job_dir.name
    manifest.config = cfg
    engine = PipelineEngine(cfg, store=store, manifest=manifest)
    engine.demo_path = _resolve_demo_for_resume(store, manifest, demo_path, from_stage)
    input_path = engine.demo_path or Path(".")
    engine.run(input_path, from_stage=from_stage, to_stage=to_stage)
    return store.job_dir


def _require_job(path: Path) -> Path:
    job_dir = resolve_job_dir(path)
    if job_dir is None:
        raise FileNotFoundError(f"找不到 Job 目录：{path}")
    return job_dir


def _load_job_config_with_runtime_secrets(job_dir: Path) -> PipelineConfig:
    manifest = PipelineManifest.load(job_dir / "manifest.json")
    return _merge_runtime_config(manifest.config)


def _merge_runtime_config(cfg: PipelineConfig) -> PipelineConfig:
    runtime = load_config()
    # Manifest is shareable and redacted. Pull secrets/default LLM settings from local config.
    if runtime.get("llm_api_key"):
        cfg.llm_api_key = runtime.get("llm_api_key")
    if runtime.get("llm_base_url"):
        cfg.llm_base_url = runtime.get("llm_base_url")
    if runtime.get("llm_model"):
        cfg.llm_model = runtime.get("llm_model")
    return cfg


def _resolve_demo_for_resume(store: ArtifactStore, manifest: PipelineManifest, demo_path: Path | None, from_stage: StageName) -> Path | None:
    if demo_path:
        return demo_path.expanduser().resolve()
    artifact = manifest.artifacts.get("demo_path")
    if artifact:
        p = Path(artifact)
        if p.exists():
            return p
        moved = store.input_dir / p.name
        if moved.exists():
            return moved
    candidates = list(store.input_dir.glob("*.dem")) + list(store.input_dir.glob("*.dem.zst"))
    if candidates:
        return candidates[0]
    # Late stages do not need the demo file.
    if from_stage in {StageName.TRANSLATE, StageName.EXPORT_SUBTITLES}:
        return None
    raise FileNotFoundError("恢复到该阶段需要原始 .dem/.dem.zst，但 Job input/ 中没有找到；请用 --demo 指定。")


def _update_manifest_config_and_artifacts(store: ArtifactStore, cfg: PipelineConfig, outputs: dict[str, str]) -> None:
    try:
        manifest = PipelineManifest.load(store.manifest_path)
    except Exception:
        manifest = PipelineManifest.create(store.job_dir.name, cfg)
    manifest.config = cfg
    for key, value in outputs.items():
        if key == "translations":
            manifest.set_artifact("translations", Path(value))
        elif value:
            manifest.set_artifact(key, Path(value))
    if store.glossary_used_path.exists():
        manifest.set_artifact("glossary_used", store.glossary_used_path)
    if store.glossary_warnings_path.exists():
        manifest.set_artifact("glossary_warnings", store.glossary_warnings_path)
    if store.player_aliases_path.exists():
        manifest.set_artifact("player_aliases", store.player_aliases_path)
    if store.player_stats_path.exists():
        manifest.set_artifact("player_stats", store.player_stats_path)
    manifest.save(store.manifest_path)


def _safe_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        if path.exists():
            return read_json(path)
    except Exception:
        return default
    return default


def _contains_secret(value: Any) -> bool:
    text = ""
    try:
        import json
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    return "sk-" in text or "api_key\": \"" in text and REDACTED_SECRET not in text


def _recommended_next_commands(job_dir: Path, failed: list[str], pending: list[str], translations: int, transcripts: int, comms_files: list[str] | None = None) -> list[str]:
    q = f'"{job_dir}"'
    if failed:
        return [f"cs2pov resume {q} --from-stage {failed[0]}", f"cs2pov feedback {q}"]
    if translations == 0 and transcripts > 0:
        return [f"cs2pov retranslate {q}", f"cs2pov export {q} --format all"]
    if pending:
        return [f"cs2pov resume {q} --from-stage {pending[0]}"]
    comms_files = comms_files or []
    has_comms_review = any(path.startswith("review/comms_rounds/") and path.endswith((".yaml", ".yml")) for path in comms_files)
    has_comms_overlay = any(path.startswith("final/comms_overlay/") and path.endswith((".mp4", ".mov", ".png")) for path in comms_files)
    if translations > 0 and not has_comms_review:
        return [f"cs2pov comms build-review {q} --rounds 1-3", f"cs2pov feedback {q}"]
    if has_comms_review and not has_comms_overlay:
        return [f"cs2pov comms render {q} --rounds 1-3 --formats preview,green", f"cs2pov feedback {q}"]
    return [f"cs2pov comms render {q} --rounds 1-3 --formats preview,green", f"cs2pov export {q} --format all", f"cs2pov feedback {q}"]
