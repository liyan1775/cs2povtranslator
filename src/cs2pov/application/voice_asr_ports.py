from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path
from typing import Protocol
import wave

from cs2pov.adapters.demoparser_adapter import DemoparserAdapter
from cs2pov.adapters.whisper_adapter import FasterWhisperAdapter
from cs2pov.application.pipeline_ports import (
    PipelinePortError,
    _next_timestamp,
)
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invocation import (
    ModelCapability,
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.job import JobPhase
from cs2pov.domain.job_state import advance_job_phase
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.timeline import DemoTimeline
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.validation import (
    validate_transcript_against_timeline,
    validate_voice_activity_against_timeline,
)
from cs2pov.domain.voice import VoiceActivityCue


@dataclass(frozen=True, slots=True)
class VoicePacket:
    source_start: int
    source_end: int
    demo_range: TimeRange


@dataclass(frozen=True, slots=True)
class VoiceStream:
    player_id: str
    display_name: str
    team_number: int | None
    sample_rate: int
    audio_path: Path
    packets: tuple[VoicePacket, ...]


@dataclass(frozen=True, slots=True)
class VoiceExtractionResult:
    streams: tuple[VoiceStream, ...]


@dataclass(frozen=True, slots=True)
class ASRWindow:
    activity_id: str
    player_id: str
    audio_path: Path
    scratch_dir: Path
    sample_rate: int
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class ASRSegment:
    source_start: int
    source_end: int
    text: str
    language: str
    confidence: float | None


class VoiceExtractorPort(Protocol):
    def extract(
        self,
        demo_path: Path,
        scratch_dir: Path,
        *,
        tick_rate: Fraction,
    ) -> VoiceExtractionResult:
        """Extract compact player streams into a temporary workspace cache."""


class ASRPort(Protocol):
    def transcribe(self, window: ASRWindow) -> tuple[ASRSegment, ...]:
        """Return source sample spans in the compact stream's clock."""


class LegacyVoiceExtractorPort:
    """Adapt the existing Opus extraction output to typed in-memory streams."""

    def __init__(self, adapter: object | None = None) -> None:
        self.adapter = adapter or DemoparserAdapter()
        if not callable(getattr(self.adapter, "extract_voice", None)):
            raise TypeError("adapter 必须提供 extract_voice 方法。")

    def extract(
        self,
        demo_path: Path,
        scratch_dir: Path,
        *,
        tick_rate: Fraction,
    ) -> VoiceExtractionResult:
        if not isinstance(demo_path, Path) or not demo_path.is_file():
            raise PipelinePortError(
                "pipeline_input_invalid",
                "找不到可读取的 Demo 文件。",
                "请检查 Demo 路径后重试。",
                "demo_path",
            )
        if not isinstance(scratch_dir, Path):
            raise PipelinePortError(
                "pipeline_input_invalid",
                "语音缓存目录类型无效。",
                "请提供工作区缓存目录后重试。",
                "scratch_dir",
            )
        if not isinstance(tick_rate, Fraction) or tick_rate <= 0:
            raise PipelinePortError(
                "pipeline_metadata_invalid",
                "Demo tick rate 无效。",
                "请先生成有效的 Demo 时间线。",
                "demo.tick_rate",
            )
        voice_dir = scratch_dir / "voice"
        voice_dir.mkdir(parents=True, exist_ok=True)
        try:
            manifest = self.adapter.extract_voice(
                demo_path,
                voice_dir,
                tick_rate=float(tick_rate),
            )
            return _streams_from_legacy_manifest(manifest, voice_dir, tick_rate)
        except PipelinePortError:
            raise
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            raise PipelinePortError(
                "pipeline_voice_extract_failed",
                "无法把旧版语音提取结果转换为当前版本数据。",
                "请检查语音解码器、Demo 和工作区缓存后重试。",
                "voice",
            ) from exc


class LegacyFasterWhisperPort:
    """Run faster-whisper on one compact activity window."""

    def __init__(
        self,
        *,
        model_name: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "auto",
        vad_filter: bool = True,
        cache_dir: str | None = None,
        adapter_factory=FasterWhisperAdapter,
        keep_temp_audio: bool = False,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._adapter_kwargs = {
            "model_name": model_name,
            "device": device,
            "compute_type": compute_type,
            "language": language,
            "vad_filter": vad_filter,
            "cache_dir": cache_dir,
        }
        self._adapter = None
        self.keep_temp_audio = bool(keep_temp_audio)

    def transcribe(self, window: ASRWindow) -> tuple[ASRSegment, ...]:
        if not window.audio_path.is_file():
            raise PipelinePortError(
                "pipeline_asr_input_invalid",
                "ASR 音频输入不存在。",
                "请重新提取语音或检查工作区缓存。",
                "voice/audio",
            )
        target = _write_asr_slice(window)
        try:
            if self._adapter is None:
                self._adapter = self._adapter_factory(**self._adapter_kwargs)
            raw_segments = self._adapter.transcribe(target)
            if not isinstance(raw_segments, (list, tuple)):
                raise PipelinePortError(
                    "pipeline_asr_result_invalid",
                    "ASR 适配器返回的数据格式无效。",
                    "请检查 faster-whisper 适配器版本后重试。",
                    "transcript",
                )
            result: list[ASRSegment] = []
            for raw in raw_segments:
                if not isinstance(raw, dict):
                    raise PipelinePortError(
                        "pipeline_asr_result_invalid",
                        "ASR 片段格式无效。",
                        "请检查 faster-whisper 适配器输出后重试。",
                        "transcript",
                    )
                start = _seconds_to_samples(raw.get("start"), window.sample_rate, ceil=False)
                end = _seconds_to_samples(raw.get("end"), window.sample_rate, ceil=True)
                start = max(window.source_start, min(start + window.source_start, window.source_end))
                end = max(window.source_start, min(end + window.source_start, window.source_end))
                if end <= start:
                    raise PipelinePortError(
                        "pipeline_asr_result_invalid",
                        "ASR 片段没有有效的音频范围。",
                        "请检查 faster-whisper 适配器输出后重试。",
                        "transcript",
                    )
                text = raw.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    continue
                language = raw.get("language") or "und"
                confidence = raw.get("confidence")
                if confidence is not None:
                    confidence = float(confidence)
                    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                        raise PipelinePortError(
                            "pipeline_asr_result_invalid",
                            "ASR 置信度无效。",
                            "请检查 faster-whisper 适配器输出后重试。",
                            "transcript.confidence",
                        )
                result.append(
                    ASRSegment(start, end, text.strip(), str(language), confidence)
                )
            return tuple(result)
        except PipelinePortError:
            raise
        except (OSError, TypeError, ValueError, RuntimeError, OverflowError) as exc:
            raise PipelinePortError(
                "pipeline_asr_failed",
                "ASR 处理失败。",
                "请检查模型缓存、音频输入和 faster-whisper 配置后重试。",
                "transcript",
            ) from exc
        finally:
            if not self.keep_temp_audio:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass


@dataclass(frozen=True, slots=True)
class VoiceAsrRunReport:
    job: object
    completed_round_ids: tuple[str, ...]
    failed_round_ids: tuple[str, ...]
    failed_unassigned: bool
    errors: tuple[tuple[str, str], ...]


class CurrentJobVoiceAsrApplicationService:
    """Project legacy voice/ASR outputs into the current Job graph."""

    def __init__(
        self,
        repository: object,
        extractor: VoiceExtractorPort | None = None,
        asr: ASRPort | None = None,
        *,
        claim_lease_us: int = 60_000_000,
    ) -> None:
        required_methods = (
            "load_job",
            "load_demo_timeline",
            "load_voice_activities",
            "acquire_write",
            "save_demo_timeline",
            "save_voice_activities",
            "register_model_configuration",
            "save_task_invocations",
            "save_transcript_round",
            "save_unassigned_transcript",
            "replace_manifest",
            "load_language_graph",
        )
        if any(not callable(getattr(repository, name, None)) for name in required_methods):
            raise TypeError("repository 不符合当前语音/ASR Job 接口。")
        if not callable(getattr(repository, "clock", None)):
            raise TypeError("repository 必须提供可调用的 clock。")
        if type(claim_lease_us) is not int or claim_lease_us <= 0:
            raise ValueError("claim_lease_us 必须为正整数。")
        self.repository = repository
        self.extractor = extractor or LegacyVoiceExtractorPort()
        self.asr = asr or LegacyFasterWhisperPort()
        self.claim_lease_us = claim_lease_us

    def run(
        self,
        job_id: str,
        demo_path: Path,
        asr_configuration: ModelConfigurationSnapshot,
        scratch_dir: Path,
    ) -> VoiceAsrRunReport:
        if not isinstance(asr_configuration, ModelConfigurationSnapshot):
            raise TypeError("asr_configuration 必须是 ModelConfigurationSnapshot。")
        if asr_configuration.capability is not ModelCapability.ASR:
            raise PipelinePortError(
                "pipeline_configuration_invalid",
                "当前配置不是 ASR 配置。",
                "请使用 capability=asr 的模型配置快照。",
                "models/snapshot",
            )
        opened = self.repository.load_job(job_id)
        if opened.manifest.phase not in {JobPhase.TIMELINE_READY, JobPhase.VOICE_READY}:
            raise PipelinePortError(
                "pipeline_phase_invalid",
                "当前 Job 不允许执行语音和 ASR 阶段。",
                "请从时间线就绪或语音就绪阶段继续。",
                "job.phase",
            )
        if not isinstance(scratch_dir, Path):
            raise PipelinePortError(
                "pipeline_input_invalid",
                "语音缓存目录类型无效。",
                "请提供工作区缓存目录后重试。",
                "scratch_dir",
            )
        timeline = self.repository.load_demo_timeline(job_id)
        extraction = self.extractor.extract(
            demo_path,
            scratch_dir,
            tick_rate=Fraction(
                timeline.descriptor.tick_rate_numerator,
                timeline.descriptor.tick_rate_denominator,
            ),
        )
        if type(extraction) is not VoiceExtractionResult:
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "语音提取端口返回的数据无效。",
                "请检查语音提取适配器后重试。",
                "voice",
            )

        initial_phase = opened.manifest.phase
        if initial_phase is JobPhase.TIMELINE_READY:
            projected_timeline, activities = build_voice_projection(timeline, extraction)
        else:
            projected_timeline = timeline
            activities = self.repository.load_voice_activities(job_id)
            try:
                for activity in activities:
                    validate_voice_activity_against_timeline(activity, timeline)
            except DomainSchemaError as exc:
                raise PipelinePortError(
                    "pipeline_voice_graph_invalid",
                    "已有语音活动与 Job 时间线不一致。",
                    "请恢复一致的语音活动和时间锚点后重试。",
                    "voice/activities.jsonl",
                ) from exc

        streams = {stream.player_id: stream for stream in extraction.streams}
        windows = _windows_for_activities(activities, projected_timeline, streams, scratch_dir)
        activity_results: dict[str, tuple[tuple[TranscriptCue, ...], ModelInvocationRecord | None]] = {}
        errors: list[tuple[str, str]] = []
        for activity, window, round_id in windows:
            try:
                raw_segments = self.asr.transcribe(window)
                cues, invocation = _convert_asr_activity(
                    activity,
                    round_id,
                    raw_segments,
                    projected_timeline,
                    activities,
                    asr_configuration,
                )
                activity_results[activity.activity_id] = (cues, invocation)
            except (PipelinePortError, DomainSchemaError, OSError, TypeError, ValueError, RuntimeError) as exc:
                code = exc.code if isinstance(exc, PipelinePortError) else "pipeline_asr_result_invalid"
                errors.append((activity.activity_id, code))

        failed_activity_ids = {activity_id for activity_id, _ in errors}
        failed_round_ids = {
            round_id
            for activity, _, round_id in windows
            if activity.activity_id in failed_activity_ids and round_id is not None
        }
        failed_unassigned = any(
            activity.activity_id in failed_activity_ids and round_id is None
            for activity, _, round_id in windows
        )
        round_values = {round_value.round_id for round_value in projected_timeline.rounds.rounds}
        round_cues: dict[str, list[TranscriptCue]] = {round_id: [] for round_id in round_values}
        round_invocations: dict[str, list[ModelInvocationRecord]] = {round_id: [] for round_id in round_values}
        unassigned_cues: list[TranscriptCue] = []
        unassigned_invocations: list[ModelInvocationRecord] = []
        for activity, _, round_id in windows:
            if activity.activity_id in failed_activity_ids:
                continue
            cues, invocation = activity_results[activity.activity_id]
            if round_id is None:
                unassigned_cues.extend(cues)
                if invocation is not None:
                    unassigned_invocations.append(invocation)
            elif round_id not in failed_round_ids:
                round_cues[round_id].extend(cues)
                if invocation is not None:
                    round_invocations[round_id].append(invocation)

        with self.repository.acquire_write(job_id, lease_us=self.claim_lease_us) as session:
            current = self.repository.load_job(job_id)
            if current.manifest.phase is not initial_phase:
                raise PipelinePortError(
                    "pipeline_job_changed",
                    "Job 在语音处理期间发生了变化。",
                    "请重新打开 Job 后重试。",
                    "job.json",
                )
            if initial_phase is JobPhase.TIMELINE_READY:
                self.repository.save_demo_timeline(job_id, projected_timeline, session.claim)
                self.repository.save_voice_activities(job_id, tuple(activities), session.claim)
                current = self.repository.load_job(job_id)
                voice_ready = advance_job_phase(
                    current.manifest,
                    JobPhase.VOICE_READY,
                    at=_next_timestamp(self.repository.clock, current.manifest.updated_at),
                )
                self.repository.replace_manifest(
                    job_id,
                    current.manifest.content_fingerprint(),
                    voice_ready,
                    session.claim,
                )
            else:
                current_activities = self.repository.load_voice_activities(job_id)
                if current_activities != tuple(activities):
                    raise PipelinePortError(
                        "pipeline_job_changed",
                        "已有语音活动在处理期间发生了变化。",
                        "请重新打开 Job 后重试。",
                        "voice/activities.jsonl",
                    )
            self.repository.register_model_configuration(
                job_id,
                asr_configuration,
                self.repository.load_job(job_id).manifest.content_fingerprint(),
                session.claim,
            )
            for round_value in projected_timeline.rounds.rounds:
                round_id = round_value.round_id
                if round_id in failed_round_ids:
                    continue
                for invocation in sorted(round_invocations[round_id], key=lambda item: item.invocation_id):
                    self.repository.save_task_invocations(
                        job_id,
                        invocation.task_id,
                        (invocation,),
                        session.claim,
                    )
                cues = tuple(sorted(round_cues[round_id], key=lambda item: (item.time_range.start_us, item.time_range.end_us, item.cue_id)))
                self.repository.save_transcript_round(job_id, round_id, cues, session.claim)
            if not failed_unassigned:
                for invocation in sorted(unassigned_invocations, key=lambda item: item.invocation_id):
                    self.repository.save_task_invocations(
                        job_id,
                        invocation.task_id,
                        (invocation,),
                        session.claim,
                    )
            self.repository.save_unassigned_transcript(
                job_id,
                () if failed_unassigned else tuple(sorted(unassigned_cues, key=lambda item: (item.time_range.start_us, item.time_range.end_us, item.cue_id))),
                session.claim,
            )
            self.repository.load_language_graph(job_id)
            if not failed_round_ids and not failed_unassigned:
                current = self.repository.load_job(job_id)
                transcribed = advance_job_phase(
                    current.manifest,
                    JobPhase.TRANSCRIBED,
                    at=_next_timestamp(self.repository.clock, current.manifest.updated_at),
                )
                self.repository.replace_manifest(
                    job_id,
                    current.manifest.content_fingerprint(),
                    transcribed,
                    session.claim,
                )
        completed_round_ids = tuple(
            round_value.round_id
            for round_value in projected_timeline.rounds.rounds
            if round_value.round_id not in failed_round_ids
        )
        return VoiceAsrRunReport(
            self.repository.load_job(job_id),
            completed_round_ids,
            tuple(sorted(failed_round_ids)),
            failed_unassigned,
            tuple(sorted(errors)),
        )


def build_voice_projection(
    timeline: DemoTimeline,
    extraction: VoiceExtractionResult,
) -> tuple[DemoTimeline, tuple[VoiceActivityCue, ...]]:
    if not isinstance(timeline, DemoTimeline) or type(extraction) is not VoiceExtractionResult:
        raise PipelinePortError(
            "pipeline_voice_result_invalid",
            "语音投影输入无效。",
            "请检查当前时间线和语音提取结果后重试。",
            "voice",
        )
    if any(anchor.source_clock is SourceClock.COMPACT_AUDIO_SAMPLE for anchor in timeline.anchors):
        raise PipelinePortError(
            "pipeline_voice_already_projected",
            "当前时间线已经包含语音时间锚点。",
            "请从已有语音阶段继续，避免覆盖已发布的语音结果。",
            "timeline/time_anchors.jsonl",
        )
    players = {player.player_id for player in timeline.descriptor.players}
    streams = sorted(extraction.streams, key=lambda stream: stream.player_id)
    if len({stream.player_id for stream in streams}) != len(streams):
        raise PipelinePortError(
            "pipeline_voice_result_invalid",
            "语音提取结果包含重复玩家流。",
            "请检查语音提取适配器输出后重试。",
            "voice",
        )
    anchors: list[TimeAnchor] = []
    activities: list[VoiceActivityCue] = []
    one_tick_us = _ceil_fraction(
        Fraction(1_000_000 * timeline.descriptor.tick_rate_denominator, timeline.descriptor.tick_rate_numerator)
    )
    for stream in streams:
        if not isinstance(stream.player_id, str) or stream.player_id not in players:
            raise PipelinePortError(
                "pipeline_player_reference_invalid",
                "语音提取结果引用了时间线之外的玩家。",
                "请检查 Demo 玩家身份和语音提取结果。",
                "voice/player_id",
            )
        if type(stream.sample_rate) is not int or stream.sample_rate <= 0:
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "语音采样率无效。",
                "请检查语音提取适配器输出后重试。",
                "voice/sample_rate",
            )
        if not isinstance(stream.packets, (tuple, list)):
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "语音包集合格式无效。",
                "请检查语音提取适配器输出后重试。",
                "voice/packets",
            )
        packets = tuple(sorted(stream.packets, key=lambda packet: (packet.source_start, packet.source_end)))
        if packets != stream.packets:
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "语音包顺序不是规范顺序。",
                "请检查语音提取适配器输出后重试。",
                "voice/packets",
            )
        groups: list[list[VoicePacket]] = []
        for index, packet in enumerate(packets):
            if type(packet.source_start) is not int or type(packet.source_end) is not int or packet.source_end <= packet.source_start:
                raise PipelinePortError(
                    "pipeline_voice_result_invalid",
                    "语音包来源样本范围无效。",
                    "请检查语音提取适配器输出后重试。",
                    f"voice/packets[{index}]",
                )
            if not isinstance(packet.demo_range, TimeRange):
                raise PipelinePortError(
                    "pipeline_voice_result_invalid",
                    "语音包 Demo 时间范围无效。",
                    "请检查语音提取适配器输出后重试。",
                    f"voice/packets[{index}]",
                )
            if index and packet.source_start < packets[index - 1].source_end:
                raise PipelinePortError(
                    "pipeline_voice_result_invalid",
                    "同一玩家的语音包来源范围重叠。",
                    "请检查语音提取适配器输出后重试。",
                    "voice/packets",
                )
            anchor_id = f"anchor-audio-{stream.player_id}-{index + 1:05d}"
            try:
                anchors.append(
                    TimeAnchor(
                        anchor_id,
                        SourceClock.COMPACT_AUDIO_SAMPLE,
                        stream.player_id,
                        packet.source_start,
                        packet.source_end,
                        packet.demo_range,
                        one_tick_us,
                        "legacy-pyogg-v1",
                    )
                )
            except DomainSchemaError as exc:
                raise PipelinePortError(
                    "pipeline_voice_result_invalid",
                    "语音包不能转换为当前版本时间锚点。",
                    "请检查语音包范围和 Demo 时间后重试。",
                    f"voice/packets[{index}]",
                ) from exc
            if not groups or groups[-1][-1].demo_range.end_us != packet.demo_range.start_us:
                groups.append([packet])
            else:
                groups[-1].append(packet)
        for group_index, group in enumerate(groups, 1):
            first = group[0]
            last = group[-1]
            activity = VoiceActivityCue(
                f"activity-{stream.player_id}-{group_index:05d}",
                stream.player_id,
                TimeRange(first.demo_range.start_us, last.demo_range.end_us),
                len(group),
                tuple(
                    f"anchor-audio-{stream.player_id}-{packets.index(packet) + 1:05d}"
                    for packet in group
                ),
                one_tick_us,
            )
            activities.append(activity)
    try:
        projected = DemoTimeline(timeline.descriptor, timeline.rounds, tuple(timeline.anchors) + tuple(anchors))
        for activity in activities:
            validate_voice_activity_against_timeline(activity, projected)
    except DomainSchemaError as exc:
        raise PipelinePortError(
            "pipeline_voice_graph_invalid",
            "语音时间锚点或活动无法闭合到当前时间线。",
            "请检查语音包范围、Demo 时间轴和玩家映射后重试。",
            "voice",
        ) from exc
    return projected, tuple(sorted(activities, key=lambda item: (item.time_range.start_us, item.time_range.end_us, item.activity_id)))


def _streams_from_legacy_manifest(
    manifest: object,
    voice_dir: Path,
    tick_rate: Fraction,
) -> VoiceExtractionResult:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("players"), list):
        raise PipelinePortError(
            "pipeline_voice_result_invalid",
            "旧版语音提取结果缺少玩家列表。",
            "请检查语音提取适配器输出后重试。",
            "voice/manifest",
        )
    sample_rate = manifest.get("sample_rate", 24_000)
    if type(sample_rate) is not int or sample_rate <= 0:
        raise PipelinePortError(
            "pipeline_voice_result_invalid",
            "旧版语音提取结果的采样率无效。",
            "请检查语音提取适配器输出后重试。",
            "voice/sample_rate",
        )
    streams: list[VoiceStream] = []
    for index, row in enumerate(manifest["players"]):
        if not isinstance(row, dict):
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "旧版语音玩家记录无效。",
                "请检查语音提取适配器输出后重试。",
                f"voice/players[{index}]",
            )
        player_id = row.get("steamid")
        if not isinstance(player_id, str) or not player_id.strip():
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "语音玩家缺少稳定身份。",
                "请检查 Demo 玩家信息后重试。",
                f"voice/players[{index}]",
            )
        audio_path = _safe_voice_path(row.get("wav_path"), voice_dir, "wav_path")
        packet_path = _safe_voice_path(row.get("packet_info_path"), voice_dir, "packet_info_path")
        import json

        packets_payload = json.loads(packet_path.read_text(encoding="utf-8"))
        if not isinstance(packets_payload, list):
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "语音包清单格式无效。",
                "请检查语音提取适配器输出后重试。",
                "voice/packets",
            )
        packets: list[VoicePacket] = []
        for packet_index, packet in enumerate(packets_payload):
            if not isinstance(packet, dict):
                raise PipelinePortError(
                    "pipeline_voice_result_invalid",
                    "语音包记录无效。",
                    "请检查语音提取适配器输出后重试。",
                    f"voice/packets[{packet_index}]",
                )
            try:
                start = _seconds_to_samples(packet["wav_offset"], sample_rate, ceil=False)
                end = _seconds_to_samples(
                    Fraction(str(packet["wav_offset"])) + Fraction(str(packet["duration"])),
                    sample_rate,
                    ceil=True,
                )
                demo_start = _seconds_to_us(packet["demo_start"], ceil=False)
                demo_end = _seconds_to_us(packet["demo_end"], ceil=True)
                packets.append(VoicePacket(start, end, TimeRange(demo_start, demo_end)))
            except (DomainSchemaError, KeyError, TypeError, ValueError, OverflowError) as exc:
                raise PipelinePortError(
                    "pipeline_voice_result_invalid",
                    "语音包时间或来源范围无效。",
                    "请检查语音提取适配器输出后重试。",
                    f"voice/packets[{packet_index}]",
                ) from exc
        streams.append(
            VoiceStream(
                player_id.strip(),
                str(row.get("name") or player_id).strip(),
                row.get("team_number"),
                sample_rate,
                audio_path,
                tuple(packets),
            )
        )
    return VoiceExtractionResult(tuple(sorted(streams, key=lambda stream: stream.player_id)))


def _windows_for_activities(
    activities: tuple[VoiceActivityCue, ...],
    timeline: DemoTimeline,
    streams: dict[str, VoiceStream],
    scratch_dir: Path,
) -> tuple[tuple[VoiceActivityCue, ASRWindow, str | None], ...]:
    anchors = {anchor.anchor_id: anchor for anchor in timeline.anchors}
    windows: list[tuple[VoiceActivityCue, ASRWindow, str | None]] = []
    for activity in activities:
        stream = streams.get(activity.player_id)
        if stream is None:
            raise PipelinePortError(
                "pipeline_voice_result_invalid",
                "已有语音活动缺少对应的音频流。",
                "请重新提取语音后重试。",
                f"voice/{activity.activity_id}",
            )
        selected = [anchors[anchor_id] for anchor_id in activity.anchor_ids if anchor_id in anchors]
        if len(selected) != len(activity.anchor_ids):
            raise PipelinePortError(
                "pipeline_voice_graph_invalid",
                "语音活动引用了不存在的时间锚点。",
                "请恢复一致的时间线和语音活动后重试。",
                f"voice/{activity.activity_id}",
            )
        source_start = selected[0].source_start
        source_end = selected[-1].source_end
        round_value = next(
            (
                round_item
                for round_item in timeline.rounds.rounds
                if round_item.time_range.start_us <= activity.time_range.start_us
                and activity.time_range.end_us <= round_item.time_range.end_us
            ),
            None,
        )
        windows.append(
            (
                activity,
                ASRWindow(
                    activity.activity_id,
                    activity.player_id,
                    stream.audio_path,
                    scratch_dir / "asr",
                    stream.sample_rate,
                    source_start,
                    source_end,
                ),
                round_value.round_id if round_value is not None else None,
            )
        )
    return tuple(windows)


def _convert_asr_activity(
    activity: VoiceActivityCue,
    round_id: str | None,
    raw_segments: object,
    timeline: DemoTimeline,
    activities: tuple[VoiceActivityCue, ...],
    configuration: ModelConfigurationSnapshot,
) -> tuple[tuple[TranscriptCue, ...], ModelInvocationRecord | None]:
    if not isinstance(raw_segments, (tuple, list)):
        raise PipelinePortError(
            "pipeline_asr_result_invalid",
            "ASR 端口返回的数据格式无效。",
            "请检查 ASR 适配器输出后重试。",
            "transcript",
        )
    request_payload = {
        "activity_id": activity.activity_id,
        "player_id": activity.player_id,
        "round_id": round_id,
        "source_start": min(anchor.source_start for anchor in timeline.anchors if anchor.anchor_id in activity.anchor_ids),
        "source_end": max(anchor.source_end for anchor in timeline.anchors if anchor.anchor_id in activity.anchor_ids),
        "configuration_snapshot_id": configuration.snapshot_id,
    }
    invocation_id = f"asr-invocation-{activity.activity_id}"
    task_id = f"asr-{activity.activity_id}"
    cues: list[TranscriptCue] = []
    anchor_values = tuple(timeline.anchors)
    for index, segment in enumerate(raw_segments, 1):
        if type(segment) is not ASRSegment:
            raise PipelinePortError(
                "pipeline_asr_result_invalid",
                "ASR 片段类型无效。",
                "请检查 ASR 适配器输出后重试。",
                "transcript",
            )
        try:
            cue = TranscriptCue.from_source_span(
                f"cue-{activity.activity_id}-{index:05d}",
                activity.player_id,
                round_id,
                SourceClock.COMPACT_AUDIO_SAMPLE,
                activity.player_id,
                segment.source_start,
                segment.source_end,
                anchor_values,
                segment.text,
                segment.language or "und",
                segment.confidence,
                (activity.activity_id,),
                invocation_id,
            )
        except DomainSchemaError as exc:
            raise PipelinePortError(
                "pipeline_asr_result_invalid",
                "ASR 片段无法闭合到当前 Job 的语音和时间锚点。",
                "请检查 ASR 时间范围；跨静音或不连续来源必须拆分后重试。",
                "transcript",
            ) from exc
        cues.append(cue)
    if not cues:
        return (), None
    response_payload = {
        "activity_id": activity.activity_id,
        "transcript_cues": [cue.to_dict() for cue in cues],
    }
    invocation = ModelInvocationRecord.from_payloads(
        invocation_id,
        configuration.snapshot_id,
        task_id,
        request_payload,
        response_payload,
    )
    for cue in cues:
        validate_transcript_against_timeline(cue, timeline, activities, (configuration,), (invocation,))
    return tuple(cues), invocation


def _write_asr_slice(window: ASRWindow) -> Path:
    if type(window.sample_rate) is not int or window.sample_rate <= 0:
        raise PipelinePortError(
            "pipeline_asr_input_invalid",
            "ASR 音频采样率无效。",
            "请重新提取语音后重试。",
            "voice/sample_rate",
        )
    if type(window.source_start) is not int or type(window.source_end) is not int or window.source_end <= window.source_start:
        raise PipelinePortError(
            "pipeline_asr_input_invalid",
            "ASR 音频来源范围无效。",
            "请重新提取语音后重试。",
            "voice/source_range",
        )
    window.scratch_dir.mkdir(parents=True, exist_ok=True)
    target = window.scratch_dir / f"{window.activity_id}.wav"
    try:
        with wave.open(str(window.audio_path), "rb") as source:
            if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != window.sample_rate:
                raise PipelinePortError(
                    "pipeline_asr_input_invalid",
                    "ASR 音频格式与语音流元数据不一致。",
                    "请重新提取语音后重试。",
                    "voice/audio",
                )
            if window.source_end > source.getnframes():
                raise PipelinePortError(
                    "pipeline_asr_input_invalid",
                    "ASR 音频来源范围超出音频文件。",
                    "请重新提取语音后重试。",
                    "voice/source_range",
                )
            source.setpos(window.source_start)
            frames = source.readframes(window.source_end - window.source_start)
            with wave.open(str(target), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(window.sample_rate)
                output.writeframes(frames)
    except PipelinePortError:
        raise
    except (OSError, wave.Error) as exc:
        raise PipelinePortError(
            "pipeline_asr_input_invalid",
            "无法读取 ASR 音频切片。",
            "请重新提取语音或检查工作区缓存。",
            "voice/audio",
        ) from exc
    return target


def _safe_voice_path(value: object, voice_dir: Path, field: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise PipelinePortError(
            "pipeline_voice_result_invalid",
            "语音文件路径无效。",
            "请检查语音提取适配器输出后重试。",
            f"voice/{field}",
        )
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = voice_dir / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(voice_dir.resolve())
    except (OSError, ValueError) as exc:
        raise PipelinePortError(
            "pipeline_path_escape",
            "语音缓存路径超出受管临时目录。",
            "请检查语音提取适配器输出后重试。",
            f"voice/{field}",
        ) from exc
    if not resolved.is_file():
        raise PipelinePortError(
            "pipeline_voice_result_invalid",
            "语音缓存文件不存在。",
            "请重新提取语音后重试。",
            f"voice/{field}",
        )
    return resolved


def _seconds_to_us(value: object, *, ceil: bool) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)) or not math.isfinite(float(value)):
        raise ValueError("seconds must be finite")
    scaled = Fraction(str(value)) * 1_000_000
    return _ceil_fraction(scaled) if ceil else scaled.numerator // scaled.denominator


def _seconds_to_samples(value: object, sample_rate: int, *, ceil: bool) -> int:
    if isinstance(value, Fraction):
        scaled = value * sample_rate
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("seconds must be finite")
        scaled = Fraction(str(value)) * sample_rate
    return _ceil_fraction(scaled) if ceil else scaled.numerator // scaled.denominator


def _ceil_fraction(value: Fraction) -> int:
    return -((-value.numerator) // value.denominator)
