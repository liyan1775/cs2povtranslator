from __future__ import annotations

from pathlib import Path

from cs2pov.domain.models import PipelineConfig, STAGE_ORDER, StageName, StageStatus, Round
from cs2pov.pipeline.manifest import PipelineManifest
from cs2pov.pipeline.progress import ProgressSink
from cs2pov.services.demo_service import DemoService
from cs2pov.services.round_service import RoundService
from cs2pov.services.subtitle_service import SubtitleService
from cs2pov.services.transcription_service import TranscriptionService
from cs2pov.services.translation_service import TranslationService
from cs2pov.services.voice_service import VoiceService
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_json, write_json
from cs2pov.services.player_alias_service import save_player_aliases
from cs2pov.application.job_runtime import JobRuntime, JobRuntimeError
from cs2pov.application.workspace_runtime import WorkspaceRuntime


class PipelineEngine:
    def __init__(
        self,
        config: PipelineConfig,
        store: ArtifactStore | None = None,
        progress: ProgressSink | None = None,
        manifest: PipelineManifest | None = None,
        *,
        runtime: WorkspaceRuntime | None = None,
        job_runtime: JobRuntime | None = None,
    ):
        if runtime is None:
            raise JobRuntimeError(
                "workspace_runtime_required",
                "创建或恢复 Job 前必须显式解析当前工作区。",
                "请先选择健康工作区，再运行任务。",
            )
        if job_runtime is not None and job_runtime.runtime != runtime:
            raise JobRuntimeError(
                "workspace_runtime_mismatch",
                "Job 路径与临时资源不属于同一个工作区运行时。",
                "请使用同一份 WorkspaceRuntime 解析 Job 路径和缓存目录。",
            )
        policy = job_runtime
        if runtime is not None and policy is None:
            policy = JobRuntime.from_config(runtime, config)
        self.config = policy.adapt_config(config) if policy is not None else config
        if store is not None and runtime is not None:
            # Existing Job data stays in place, while new model/audio scratch
            # follows the current immutable workspace runtime.
            store = ArtifactStore(
                store.job_dir,
                audio_cache_root=runtime.paths.audio_cache_dir,
                keep_temp_audio=self.config.keep_temp_audio,
            )
        self.store = store or policy.create_store(self.config)  # type: ignore[union-attr]
        self.progress = progress or ProgressSink(self.store.progress_log_path, verbose=True)
        self.manifest = manifest or (
            policy.create_manifest(self.store.job_dir.name, self.config) if policy is not None
            else PipelineManifest.create(self.store.job_dir.name, self.config)
        )
        self.manifest.config = self.config
        self.manifest.job_id = self.store.job_dir.name
        self.manifest.save(self.store.manifest_path)
        self.demo_service = DemoService()
        self.voice_service = VoiceService()
        self.round_service = RoundService()
        self.transcription_service = TranscriptionService()
        self.translation_service = TranslationService()
        self.subtitle_service = SubtitleService()
        self.demo_path: Path | None = None

    def run(self, input_path: Path, from_stage: StageName | None = None, to_stage: StageName | None = None) -> ArtifactStore:
        stages = _slice_stages(from_stage, to_stage)
        for stage in stages:
            self._run_stage(stage, Path(input_path))
        self.progress.emit("done", f"任务完成。Job 目录：{self.store.job_dir}")
        return self.store

    def _run_stage(self, stage: StageName, input_path: Path) -> None:
        self.manifest.set_stage(stage, StageStatus.RUNNING)
        self.manifest.save(self.store.manifest_path)
        try:
            if stage == StageName.PREPARE_INPUT:
                self.progress.emit(stage, "准备输入 demo。支持 .dem 和 .dem.zst。")
                self.demo_path = self.demo_service.prepare_input(input_path, self.store)
                self.manifest.set_artifact("demo_path", self.demo_path)
            elif stage == StageName.INSPECT_DEMO:
                self.progress.emit(stage, "读取 demo header、地图名和玩家列表。")
                demo_path = self._require_demo_path()
                info = self.demo_service.inspect(demo_path, input_path, self.store)
                if not self.config.map_name:
                    self.config.map_name = info.map_name
                if info.map_name and not self.config.job_id:
                    self._rename_auto_job_dir(info.map_name)
                    # The directory moved after demo_info.json was written; refresh paths in manifest and demo_info.
                    self.manifest.set_artifact("demo_path", self._require_demo_path())
                    info.demo_path = str(self.demo_path)
                    write_json(self.store.demo_info_path, info)
                self.manifest.demo.update({"map_name": info.map_name, "server_name": info.server_name, "players": len(info.players)})
                self.manifest.set_artifact("demo_info", self.store.demo_info_path)
            elif stage == StageName.EXTRACT_VOICE:
                self.progress.emit(stage, "解析 demo 语音包并解码为每个玩家的 compact WAV。")
                demo_path = self._require_demo_path()
                players = self.voice_service.extract(demo_path, self.store, tick_rate=self._tick_rate())
                self.progress.emit(stage, f"检测到 {len(players)} 名玩家有语音。")
                if self.store.player_stats_path.exists():
                    self.progress.emit(stage, "已尝试解析玩家 K-D-A，便于确认职业选手小号/临时昵称。")
                    self.manifest.set_artifact("player_stats", self.store.player_stats_path)
                self.manifest.set_artifact("voice_manifest", self.store.voice_manifest_path)
            elif stage == StageName.BUILD_VOICE_ACTIVITY:
                self.progress.emit(stage, "根据语音包时间戳生成 voice activity 时间轴。")
                cues = self.voice_service.build_activity(self.store)
                self.progress.emit(stage, f"生成 {len(cues)} 条语音活动片段。")
                self.manifest.set_artifact("voice_activity", self.store.voice_activity_path)
            elif stage == StageName.PARSE_ROUNDS:
                self.progress.emit(stage, "解析 demo 回合边界。若没有 round_start 事件，才会降级为单回合。")
                demo_path = self._require_demo_path()
                rounds = self.round_service.parse_rounds(
                    demo_path,
                    self.store,
                    tick_rate=self._tick_rate(),
                    min_duration_seconds=self.config.min_round_duration_seconds,
                )
                self._emit_round_parse_summary(stage, rounds)
                self.manifest.set_artifact("rounds", self.store.rounds_path)
                if self.store.raw_rounds_path.exists():
                    self.manifest.set_artifact("rounds_raw", self.store.raw_rounds_path)
            elif stage == StageName.TRANSCRIBE:
                self.progress.emit(stage, f"使用 faster-whisper 档位 {self.config.transcription_profile} / 模型 {self.config.whisper_model} 转录。设备：{self.config.whisper_device}；compute_type={self.config.whisper_compute_type}；语言：{self.config.asr_language}；模式：{self.config.transcription_mode}；VAD：{'ON' if self.config.whisper_vad_filter else 'OFF'}。")
                segs = self.transcription_service.transcribe_all(
                    self.store,
                    model_name=self.config.whisper_model,
                    device=self.config.whisper_device,
                    compute_type=self.config.whisper_compute_type,
                    cache_dir=self.config.whisper_cache_dir,
                    language=self.config.asr_language,
                    selected_team_number=self.config.selected_team_number,
                    vad_filter=self.config.whisper_vad_filter,
                    include_unrecognized_voice=self.config.include_unrecognized_voice,
                    unrecognized_min_duration_seconds=self.config.unrecognized_min_duration_seconds,
                    transcription_mode=self.config.transcription_mode,
                    max_rounds=self.config.max_rounds,
                    activity_padding_seconds=self.config.activity_padding_seconds,
                    keep_temp_audio=self.config.keep_temp_audio,
                    filter_hallucinations=self.config.filter_hallucinations,
                    max_subtitle_segment_seconds=self.config.max_subtitle_segment_seconds,
                    voice_cluster_gap_seconds=self.config.voice_cluster_gap_seconds,
                    progress_callback=lambda message: self.progress.emit(stage, message),
                )
                self.progress.emit(stage, f"得到 {len(segs)} 条转录片段。")
                if self.store.transcription_coverage_path.exists():
                    coverage = read_json(self.store.transcription_coverage_path)
                    self.progress.emit(stage, f"转录覆盖参考：voice_activity={coverage.get('voice_activity_cues')}，>= {coverage.get('unrecognized_min_duration_seconds')}s 的语音={coverage.get('voice_activity_cues_ge_min_duration')}，未匹配={coverage.get('unmatched_voice_cues_ge_min_duration')}，补位={coverage.get('unrecognized_placeholders_added')}，过滤幻觉={coverage.get('filtered_hallucination_segments')}，长 cue 重贴={coverage.get('long_segments_rebased_to_voice_activity')}，最长字幕片段={coverage.get('longest_transcript_segment_seconds')}s。")
                    self.manifest.set_artifact("transcription_coverage", self.store.transcription_coverage_path)
                self.manifest.set_artifact("transcripts", self.store.transcripts_path)
            elif stage == StageName.BUILD_ROUND_CONTEXTS:
                if self.config.max_rounds is not None:
                    self.progress.emit(stage, f"当前设置 max_rounds={self.config.max_rounds}，只构建前 {self.config.max_rounds} 个含语音的回合上下文。", "warning")
                self.progress.emit(stage, "把转录片段归入对应回合，为 LLM 提供上下文。")
                contexts = self.round_service.build_contexts(self.store, self.config.selected_team_number, self.config.max_rounds)
                self.progress.emit(stage, f"构建 {len(contexts)} 个 round contexts。")
                self.manifest.set_artifact("round_contexts", self.store.round_contexts_path)
            elif stage == StageName.TRANSLATE:
                self.progress.emit(stage, "按回合批量翻译，再回填到字幕片段。")
                translations = self.translation_service.translate_rounds(
                    self.store,
                    base_url=self.config.llm_base_url,
                    api_key=self.config.llm_api_key,
                    model=self.config.llm_model,
                    map_name=self.config.map_name,
                    timeout_seconds=self.config.llm_timeout_seconds,
                    dry_run=self.config.dry_run_translation,
                    skip_translation=self.config.skip_translation,
                    glossary_enabled=self.config.glossary_enabled,
                    progress_callback=lambda message: self.progress.emit(stage, message),
                )
                self.progress.emit(stage, f"得到 {len(translations)} 条翻译片段。")
                if self.store.glossary_used_path.exists():
                    self.manifest.set_artifact("glossary_used", self.store.glossary_used_path)
                if self.store.glossary_warnings_path.exists():
                    self.manifest.set_artifact("glossary_warnings", self.store.glossary_warnings_path)
                self.manifest.set_artifact("translations", self.store.translations_path)
            elif stage == StageName.EXPORT_SUBTITLES:
                self.progress.emit(stage, "按字幕策略导出双语/中文/紧凑/调试 SRT。")
                if self.config.player_aliases:
                    save_player_aliases(self.store, self.config.player_aliases, source="pipeline_config")
                    self.manifest.set_artifact("player_aliases", self.store.player_aliases_path)
                    self.progress.emit(stage, f"已应用 {len(self.config.player_aliases)} 条玩家显示名映射。")
                outputs = self.subtitle_service.export(
                    self.store,
                    selected_team_number=self.config.selected_team_number,
                    selected_pov_steamid=self.config.selected_pov_steamid,
                    export_scope=self.config.export_scope,
                    bilingual_format=self.config.subtitle_bilingual_format,
                    preset=self.config.subtitle_export_preset,
                    overlap_policy=self.config.subtitle_overlap_policy,
                    max_duration_seconds=self.config.max_subtitle_segment_seconds,
                    min_duration_seconds=self.config.subtitle_min_duration_seconds,
                )
                for key, value in outputs.items():
                    self.manifest.set_artifact(key, Path(value))
                    self.progress.emit(stage, f"输出 {key}: {value}")
            self.manifest.config = self.config
            self.manifest.set_stage(stage, StageStatus.COMPLETED)
            self.manifest.save(self.store.manifest_path)
        except Exception as exc:
            self.manifest.set_stage(stage, StageStatus.FAILED)
            self.manifest.save(self.store.manifest_path)
            self.progress.exception(stage, exc, self.store.error_log_path)
            raise

    def _rename_auto_job_dir(self, map_name: str) -> None:
        old_dir = self.store.job_dir
        old_demo_name = self.demo_path.name if self.demo_path else None
        new_store = self.store.rename_suffix(map_name)
        if new_store.job_dir == old_dir:
            return
        self.store = new_store
        if old_demo_name:
            self.demo_path = self.store.input_dir / old_demo_name
        self.progress.log_path = self.store.progress_log_path
        self.manifest.job_id = self.store.job_dir.name
        self.progress.emit("inspect_demo", f"已根据地图重命名 Job 目录：{old_dir.name} -> {self.store.job_dir.name}")

    def _emit_round_parse_summary(self, stage: StageName, rounds: list[Round]) -> None:
        if not rounds:
            self.progress.emit(stage, "没有生成任何回合信息。", "warning")
            return
        sources = {r.source for r in rounds}
        if all(src.startswith("fallback") for src in sources):
            self.progress.emit(stage, f"未读取到可靠 round_start 事件，已降级为 {len(rounds)} 个时间段。", "warning")
        else:
            self.progress.emit(stage, f"成功解析 {len(rounds)} 个有效回合/时间段。来源：{', '.join(sorted(sources))}。")
            if all(r.winner_team is None for r in rounds):
                self.progress.emit(stage, "提示：当前回合边界主要来自 round_start，并已按最短时长清洗；winner_team 暂为空，后续可接入 round_end/击杀/炸弹事件增强。")
            self.progress.emit(stage, f"回合清洗阈值：min_round_duration_seconds={self.config.min_round_duration_seconds:.1f}s。原始候选见 artifacts/rounds_raw.json。")

    def _require_demo_path(self) -> Path:
        if self.demo_path and self.demo_path.exists():
            return self.demo_path
        existing = self.manifest.artifacts.get("demo_path")
        if existing:
            candidate = Path(existing)
            if not candidate.exists() and self.store.input_dir.exists():
                moved = self.store.input_dir / candidate.name
                if moved.exists():
                    candidate = moved
            self.demo_path = candidate
            return self.demo_path
        candidates = list(self.store.input_dir.glob("*.dem"))
        if candidates:
            self.demo_path = candidates[0]
            return self.demo_path
        raise RuntimeError("找不到已准备好的 .dem 文件。请从 prepare_input 阶段开始运行。")

    def _tick_rate(self) -> float:
        try:
            data = read_json(self.store.demo_info_path)
            return float(data.get("tick_rate", 64.0))
        except Exception:
            return 64.0


def _slice_stages(from_stage: StageName | None, to_stage: StageName | None) -> list[StageName]:
    stages = STAGE_ORDER[:]
    if from_stage is not None:
        stages = stages[stages.index(from_stage):]
    if to_stage is not None:
        stages = stages[: stages.index(to_stage) + 1]
    return stages
