from __future__ import annotations

from pathlib import Path
from typing import Any

from cs2pov.cli.job_ops import inspect_job
from cs2pov.storage.artifact_store import ArtifactStore


def build_output_explanation(path: Path) -> dict[str, Any]:
    summary = inspect_job(path)
    job_dir = Path(summary["job_dir"])
    store = ArtifactStore(job_dir)
    subtitle_files = _normalize_relative_paths(summary.get("subtitle_files") or [])
    comms_files = _normalize_relative_paths(summary.get("comms_files") or [])
    return {
        "summary": summary,
        "sections": [
            {
                "name": "final/",
                "role": "给剪辑使用的最终产物。v0.9.8 默认最重要的是 Comms Feed 静态报告；SRT 作为可选字幕资产保留。",
                "files": [p for p in subtitle_files if p.startswith("final/")] + [p for p in comms_files if p.startswith("final/comms_feed")],
            },
            {
                "name": "review/",
                "role": "校对用文件。用于检查 Whisper 原文、只看中文翻译、对比字幕问题；v0.9.8 的 review/comms_rounds/round_XX.yaml 可人工修改后重新渲染 overlay。",
                "files": [p for p in subtitle_files if p.startswith("review/")] + [p for p in comms_files if p.startswith("review/comms_rounds")],
            },
            {
                "name": "final/comms_overlay/",
                "role": "v0.9.8 生成的剪映 overlay 素材：preview 用于校对，green 用于色度抠图，alpha.mov 用于透明通道兼容性测试。",
                "files": [p for p in comms_files if p.startswith("final/comms_overlay")],
            },
            {
                "name": "debug/",
                "role": "开发者排查用文件。普通剪辑不需要导入这些文件。",
                "files": [p for p in subtitle_files if p.startswith("debug/")],
            },
            {
                "name": "artifacts/",
                "role": "中间产物：转录、回合上下文、翻译 JSONL、覆盖率。用于 resume/retranslate/export。",
                "files": _existing_artifacts(store),
            },
        ],
    }


def print_output_explanation(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("CS2 POV Translator 输出文件说明")
    print("=" * 72)
    print(f"Job:  {summary['job_dir']}")
    print(f"地图: {summary.get('map_name') or '[未知]'}")
    print(f"队伍: Team {summary.get('selected_team_number') or '[未设置]'}")
    print("\n你最可能需要的文件：")
    final_files = [f for f in _normalize_relative_paths(summary.get("subtitle_files", [])) if f.startswith("final/")]
    comms_files = _normalize_relative_paths(summary.get("comms_files", []))
    primary_comms = [f for f in comms_files if f.startswith("review/comms_rounds/") or f.startswith("final/comms_feed/") or f.startswith("final/comms_overlay/")]
    if primary_comms:
        print("  [默认主功能] Comms Feed / Overlay：")
        for f in primary_comms[:12]:
            if f.endswith(".yaml"):
                print(f"  {f}  ← 主校对文件：人工修改后渲染对应回合 overlay")
            elif f.endswith("_green.mp4"):
                print(f"  {f}  ← 推荐导入剪映的绿幕 overlay，导入后色度抠图")
            elif f.endswith("_preview.mp4") or f.endswith("preview_state.png"):
                print(f"  {f}  ← 预览排版/错字")
            elif f.endswith("_alpha.mov"):
                print(f"  {f}  ← 透明通道素材，需测试剪映兼容性")
            else:
                print(f"  {f}")
    else:
        print("  [还没有 Comms Feed。v0.9.8 主流程建议运行 cs2pov comms build-review <job_dir>]")
    if final_files:
        for f in final_files:
            if f.endswith(".compact.srt"):
                print(f"  {f}  ← 紧凑双语字幕，适合剪辑导入和快速预览")
            elif f.endswith(".bilingual.srt"):
                print(f"  {f}  ← 可选双语字幕，保留原文和中文；当前主推荐导入剪映的是 Comms Overlay")
            elif f.endswith(".zh.srt"):
                print(f"  {f}  ← 只中文字幕，可在不需要原文时使用")
            elif f.endswith(".zh_clean.srt"):
                print(f"  {f}  ← 纯中文无玩家名前缀，适合极简风格，可选")
            else:
                print(f"  {f}")
    else:
        print("  [还没有 final/ 字幕。可运行 cs2pov export <job_dir> --format all]")
    if comms_files:
        print("\nComms Feed / Overlay：")
        for f in comms_files[:10]:
            if f.endswith(".yaml"):
                print(f"  {f}  ← 可人工修改后重新渲染对应回合")
            elif f.endswith("_green.mp4"):
                print(f"  {f}  ← 绿幕兜底素材，剪映可尝试色度抠图")
            elif f.endswith("_alpha.mov"):
                print(f"  {f}  ← 透明通道素材，需本地测试剪映兼容性")
            elif f.endswith("_preview.mp4") or f.endswith("preview_state.png"):
                print(f"  {f}  ← 排版/错字预览，不建议最终叠加")
            else:
                print(f"  {f}")
    print("\n目录说明：")
    for section in report["sections"]:
        print(f"\n{section['name']}")
        print(f"  {section['role']}")
        files = section.get("files") or []
        if files:
            for f in files[:12]:
                print(f"  - {f}")
            if len(files) > 12:
                print(f"  ... 还有 {len(files) - 12} 个文件")
        else:
            print("  [暂无相关文件]")
    print("\n常见下一步：")
    q = f'"{summary["job_dir"]}"'
    print(f"  [主功能] 校对通讯流：打开 review/comms_rounds/round_XX.yaml")
    print(f"  [主功能] 渲染 overlay：cs2pov comms render {q} --rounds 1-3 --formats preview,green")
    print(f"  重新生成通讯流校对文件：cs2pov comms build-review {q} --rounds 1-3")
    print(f"  可选 SRT 导出：cs2pov export {q} --preset editing")
    print(f"  重新翻译：      cs2pov retranslate {q}")
    print(f"  打包反馈：      cs2pov feedback {q}")


def _normalize_relative_paths(paths: list[str]) -> list[str]:
    """Normalize stored relative paths for cross-platform display and filtering."""
    return [str(p).replace("\\", "/") for p in paths]


def _existing_artifacts(store: ArtifactStore) -> list[str]:
    names = [
        ("artifacts/demo_info.json", store.demo_info_path),
        ("artifacts/rounds.json", store.rounds_path),
        ("artifacts/transcription_coverage.json", store.transcription_coverage_path),
        ("artifacts/transcript_segments.jsonl", store.transcripts_path),
        ("artifacts/round_contexts.jsonl", store.round_contexts_path),
        ("artifacts/translated_segments.jsonl", store.translations_path),
        ("artifacts/glossary_used.json", store.glossary_used_path),
        ("artifacts/glossary_warnings.json", store.glossary_warnings_path),
    ]
    return [name for name, path in names if path.exists()]
