from __future__ import annotations

import argparse
from pathlib import Path

from cs2pov.domain.models import PipelineConfig
from cs2pov.pipeline.engine import PipelineEngine
from cs2pov.application.job_runtime import JobRuntime
from cs2pov.application.workspace_runtime import WorkspaceRuntimeResolver
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore, default_state_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real-demo smoke acceptance test.")
    parser.add_argument("--demo", required=True)
    parser.add_argument("--output", default=None, help="旧版外部输出根目录；省略则使用当前工作区 jobs")
    parser.add_argument("--whisper-model", default="tiny")
    parser.add_argument("--team", type=int)
    parser.add_argument("--skip-translation", action="store_true")
    parser.add_argument("--dry-run-translation", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=0, help="Limit translated round contexts. Default 0 means no limit; use 1/5 for cheap LLM smoke tests.")
    parser.add_argument("--min-round-duration", type=float, default=10.0, help="Filter pseudo-rounds shorter than this many seconds. Default 10.")
    parser.add_argument("--whisper-vad", action=argparse.BooleanOptionalAction, default=True, help="Enable/disable faster-whisper VAD. v0.1.4 default true based on real-demo feedback.")
    parser.add_argument("--transcription-mode", choices=["round", "activity", "player"], default="round", help="round=default per-round player chunks; activity=per voice activity; player=legacy full compact WAV.")
    parser.add_argument("--activity-padding", type=float, default=0.06)
    parser.add_argument("--include-unrecognized-voice", action="store_true", help="Add [未识别语音] placeholders for unmatched voice activity cues.")
    parser.add_argument("--unrecognized-min-duration", type=float, default=0.35)
    parser.add_argument("--filter-hallucinations", action=argparse.BooleanOptionalAction, default=True, help="Filter pure-punctuation Whisper hallucinations. Default true.")
    parser.add_argument("--max-subtitle-segment-seconds", type=float, default=10.0, help="Rebase ASR cues longer than this many seconds to voice-activity clusters. Use 0 to disable.")
    parser.add_argument("--voice-cluster-gap", type=float, default=1.0, help="Merge voice activity bursts with gaps below this value when rebasing long cues.")
    args = parser.parse_args()

    max_rounds = None if args.max_rounds == 0 else args.max_rounds
    if max_rounds is not None:
        print(f"[ACCEPTANCE] max_rounds={max_rounds}：只验证前 {max_rounds} 个含语音回合的 round context。完整验证请传 --max-rounds 0。")
    else:
        print("[ACCEPTANCE] max_rounds=0：完整构建所有有效回合上下文。")
    print(f"[ACCEPTANCE] min_round_duration={args.min_round_duration}s：短于该阈值的疑似暂停/重开 round_start 会被过滤。")
    print(f"[ACCEPTANCE] whisper_vad={args.whisper_vad}：v0.1.4 默认开启；可用 --no-whisper-vad 对照。")
    print(f"[ACCEPTANCE] transcription_mode={args.transcription_mode}：默认 round，避免整名玩家 compact WAV 导致超长字幕合并。")
    if args.include_unrecognized_voice:
        print(f"[ACCEPTANCE] include_unrecognized_voice=True：会为 >= {args.unrecognized_min_duration}s 且未匹配转录的语音活动补 [未识别语音]。")
    print(f"[ACCEPTANCE] filter_hallucinations={args.filter_hallucinations}：默认过滤纯标点/空白 Whisper 幻觉。")
    print(f"[ACCEPTANCE] max_subtitle_segment_seconds={args.max_subtitle_segment_seconds}s：超过该时长的字幕 cue 会重贴到 voice activity 簇。")
    if args.skip_translation:
        print("[ACCEPTANCE] 已启用 --skip-translation：不会调用 LLM，中文字幕会使用原文占位。")

    runtime = WorkspaceRuntimeResolver(JsonWorkspaceSelectionStore(default_state_file())).resolve_for_write()
    output_root = args.output or str(runtime.paths.jobs_dir)
    cfg = PipelineConfig(
        output_root=output_root,
        whisper_model=args.whisper_model,
        selected_team_number=args.team,
        export_scope="pov_team" if args.team else "all",
        skip_translation=args.skip_translation,
        dry_run_translation=args.dry_run_translation,
        max_rounds=max_rounds,
        min_round_duration_seconds=args.min_round_duration,
        whisper_vad_filter=args.whisper_vad,
        transcription_mode=args.transcription_mode,
        activity_padding_seconds=args.activity_padding,
        include_unrecognized_voice=args.include_unrecognized_voice,
        unrecognized_min_duration_seconds=args.unrecognized_min_duration,
        filter_hallucinations=args.filter_hallucinations,
        max_subtitle_segment_seconds=args.max_subtitle_segment_seconds,
        voice_cluster_gap_seconds=args.voice_cluster_gap,
    )
    policy = JobRuntime.from_config(runtime, cfg, output_root=args.output)
    store = PipelineEngine(cfg, runtime=runtime, job_runtime=policy).run(Path(args.demo))
    print(f"ACCEPTANCE_JOB={store.job_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
