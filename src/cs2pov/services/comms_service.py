from __future__ import annotations

import html
import math
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from cs2pov.domain.models import Round, TranslationSegment, round_from_dict, translation_from_dict
from cs2pov.application.workspace_runtime import WorkspaceRuntime, WorkspaceRuntimeResolver
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore, default_state_file
from cs2pov.services.player_alias_service import apply_player_aliases
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_json, read_jsonl, write_json


COMMS_SCHEMA_VERSION = 1
DEFAULT_ROUND_CLOCK_START = "1:55"
DEFAULT_ROUND_CLOCK_END = "0:00"
DEFAULT_FREEZE_SECONDS = 0.0
TIME_DISPLAY_VALUES = {"none", "elapsed", "round_clock"}


@dataclass(slots=True)
class CommsRenderOptions:
    width: int = 1920
    height: int = 1080
    panel_width: int = 460
    panel_height: int = 720
    right_margin: int = 16
    y: int | None = None
    max_messages: int = 6
    fps: int = 15
    round_clock_start: str = DEFAULT_ROUND_CLOCK_START
    round_clock_end: str = DEFAULT_ROUND_CLOCK_END
    freeze_seconds: float = DEFAULT_FREEZE_SECONDS
    time_display: str = "none"
    font_path: str | None = None
    font_size_zh: int = 24
    font_size_en: int = 17
    font_size_meta: int = 17
    card_spacing: int = 10
    fade_seconds: float = 0.35
    show_outer_panel: bool = False


class CommsService:
    """Build editable per-round comms review files and render POV overlay assets.

    v0.9.x intentionally keeps this as a late-stage export service.  It reads
    already translated segments and round metadata; it does not re-run demo
    parsing, ASR, or LLM calls.
    """

    def build_review(
        self,
        store: ArtifactStore,
        selected_team_number: int | None,
        selected_pov_steamid: str | None,
        export_scope: str,
        rounds: set[int] | None = None,
        round_clock_start: str = DEFAULT_ROUND_CLOCK_START,
        round_clock_end: str = DEFAULT_ROUND_CLOCK_END,
        freeze_seconds: float = DEFAULT_FREEZE_SECONDS,
        time_display: str = "none",
        runtime: WorkspaceRuntime | None = None,
        warning_stream=None,
    ) -> dict[str, str]:
        runtime = _resolve_write_runtime(runtime)
        _warn_external_job(store.job_dir, runtime, warning_stream=warning_stream)
        store.ensure_dirs()
        comms_final_dir = store.final_dir / "comms_feed"
        comms_review_dir = store.review_dir / "comms_rounds"
        comms_final_dir.mkdir(parents=True, exist_ok=True)
        comms_review_dir.mkdir(parents=True, exist_ok=True)

        round_rows = _load_rounds(store)
        translations = self._load_translations(store, selected_team_number, selected_pov_steamid, export_scope)
        if rounds is not None:
            translations = [seg for seg in translations if seg.round_number in rounds]
            round_rows = [r for r in round_rows if r.round_number in rounds]

        feed = _build_feed_doc(
            store=store,
            rounds=round_rows,
            translations=translations,
            selected_team_number=selected_team_number,
            selected_pov_steamid=selected_pov_steamid,
            export_scope=export_scope,
            round_clock_start=round_clock_start,
            round_clock_end=round_clock_end,
            freeze_seconds=freeze_seconds,
            time_display=time_display,
        )

        feed_json_path = comms_final_dir / "comms_feed.json"
        feed_md_path = comms_final_dir / "comms_feed.md"
        feed_html_path = comms_final_dir / "comms_feed.html"
        write_json(feed_json_path, feed)
        feed_md_path.write_text(_render_feed_markdown(feed), encoding="utf-8")
        feed_html_path.write_text(_render_feed_html(feed), encoding="utf-8")

        written_rounds: list[Path] = []
        for round_doc in feed["rounds"]:
            round_path = comms_review_dir / f"round_{int(round_doc['round']):02d}.yaml"
            _write_yaml(round_path, _round_review_doc(feed, round_doc))
            written_rounds.append(round_path)

        index_path = comms_review_dir / "README_COMMS_REVIEW.md"
        index_path.write_text(_render_review_readme(feed, written_rounds), encoding="utf-8")

        outputs = {
            "comms_feed_json": str(feed_json_path),
            "comms_feed_md": str(feed_md_path),
            "comms_feed_html": str(feed_html_path),
            "comms_review_dir": str(comms_review_dir),
            "comms_review_readme": str(index_path),
        }
        return outputs

    def render(
        self,
        store: ArtifactStore,
        rounds: set[int] | None = None,
        formats: Iterable[str] = ("preview", "green"),
        options: CommsRenderOptions | None = None,
        temp_root: Path | None = None,
        subprocess_env: Mapping[str, str] | None = None,
        runtime: WorkspaceRuntime | None = None,
        warning_stream=None,
    ) -> dict[str, str]:
        runtime = _resolve_write_runtime(runtime)
        _warn_external_job(store.job_dir, runtime, warning_stream=warning_stream)
        store.ensure_dirs()
        options = options or CommsRenderOptions()
        review_dir = store.review_dir / "comms_rounds"
        if not review_dir.exists():
            raise FileNotFoundError("找不到 review/comms_rounds。请先运行 cs2pov comms build-review。")
        round_files = sorted(review_dir.glob("round_*.yaml"))
        if rounds is not None:
            round_files = [p for p in round_files if _round_number_from_path(p) in rounds]
        if not round_files:
            raise FileNotFoundError("没有匹配的 round_XX.yaml 可渲染。")

        out_dir = store.final_dir / "comms_overlay"
        out_dir.mkdir(parents=True, exist_ok=True)
        normalized_formats = tuple(_normalize_formats(formats))
        outputs: dict[str, str] = {}
        # Rendering must never inherit the machine's system temp directory.
        # The CLI supplies runtime.paths.temp_dir; the job-local fallback keeps
        # direct service callers isolated without changing global environment.
        temp_base = Path(temp_root) if temp_root is not None else runtime.paths.temp_dir
        task_dir = temp_base / f"comms_{uuid.uuid4().hex}"
        task_dir.mkdir(parents=True, exist_ok=False)
        try:
            for round_file in round_files:
                doc = _read_yaml(round_file)
                round_no = int(doc.get("round") or _round_number_from_path(round_file) or 0)
                for fmt in normalized_formats:
                    out_path = _render_round_video(
                        round_file, doc, out_dir, fmt, options, temp_root=task_dir,
                        subprocess_env=subprocess_env if subprocess_env is not None else runtime.subprocess_environment(),
                    )
                    outputs[f"round_{round_no:02d}_{fmt}"] = str(out_path)
            return outputs
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def _load_translations(
        self,
        store: ArtifactStore,
        selected_team_number: int | None,
        selected_pov_steamid: str | None,
        export_scope: str,
    ) -> list[TranslationSegment]:
        rows = read_jsonl(store.translations_path)
        translations = [translation_from_dict(row) for row in rows]
        translations = apply_player_aliases(store, _filter_segments(translations, selected_team_number, selected_pov_steamid, export_scope))
        return sorted(translations, key=lambda seg: (seg.round_number or 9999, seg.start_time, seg.end_time, seg.player_name))


def _load_rounds(store: ArtifactStore) -> list[Round]:
    if not store.rounds_path.exists():
        return []
    try:
        data = read_json(store.rounds_path)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[Round] = []
    for row in data:
        try:
            out.append(round_from_dict(row))
        except Exception:
            continue
    return sorted(out, key=lambda r: r.round_number)


def _build_feed_doc(
    *,
    store: ArtifactStore,
    rounds: list[Round],
    translations: list[TranslationSegment],
    selected_team_number: int | None,
    selected_pov_steamid: str | None,
    export_scope: str,
    round_clock_start: str,
    round_clock_end: str,
    freeze_seconds: float,
    time_display: str,
) -> dict[str, Any]:
    round_by_no = {r.round_number: r for r in rounds}
    msgs_by_round: dict[int, list[TranslationSegment]] = {}
    for seg in translations:
        round_no = int(seg.round_number or 0)
        if round_no <= 0:
            round_no = _infer_round_number(seg, rounds)
        msgs_by_round.setdefault(round_no, []).append(seg)

    all_round_numbers = sorted(msgs_by_round)
    # Keep the review folder focused on editable comms. Rounds with no selected
    # team/player messages do not need empty overlay assets.

    start_clock_seconds = parse_clock(round_clock_start)
    end_clock_seconds = parse_clock(round_clock_end)
    freeze_seconds = max(0.0, float(freeze_seconds or 0.0))
    time_display = _normalize_time_display(time_display)
    live_duration = max(1.0, start_clock_seconds - end_clock_seconds)
    default_duration = freeze_seconds + live_duration

    feed_rounds: list[dict[str, Any]] = []
    for round_no in all_round_numbers:
        r = round_by_no.get(round_no)
        round_start = r.start_time if r else min((s.start_time for s in msgs_by_round.get(round_no, [])), default=0.0)
        round_end = r.end_time if r else max((s.end_time for s in msgs_by_round.get(round_no, [])), default=round_start + default_duration)
        # CS2 round_start marks the beginning of freeze/preparation time, not
        # the moment the 1:55 live clock starts.  v0.9.6 used a fixed 115s
        # duration and subtracted elapsed time immediately, which made first
        # messages appear as if the round clock had already started.
        # For overlay clips that are placed at the start of each POV round, keep
        # the full actual round window and display a separate preparation label
        # before the live clock begins.
        if r:
            duration = max(1.0, round_end - round_start)
        else:
            duration = default_duration
        messages: list[dict[str, Any]] = []
        for idx, seg in enumerate(sorted(msgs_by_round.get(round_no, []), key=lambda s: (s.start_time, s.end_time, s.player_name)), start=1):
            show_seconds = max(0.0, seg.start_time - round_start)
            messages.append({
                "id": seg.id or f"r{round_no:02d}_m{idx:03d}",
                "show_at": format_comms_clock(show_seconds, freeze_seconds, start_clock_seconds),
                "show_at_seconds": round(show_seconds, 3),
                "phase": comms_phase(show_seconds, freeze_seconds, duration, start_clock_seconds),
                "duration_seconds": round(max(0.1, seg.end_time - seg.start_time), 3),
                "speaker": seg.player_name,
                "steamid": seg.steamid,
                "team_number": seg.team_number,
                "source": seg.original_text.strip(),
                "zh": seg.translated_text.strip(),
                "enabled": True,
                "warnings": list(seg.warnings or []),
                "note": "",
            })
        feed_rounds.append({
            "round": round_no,
            "round_clock_start": round_clock_start,
            "round_clock_end": round_clock_end,
            "freeze_seconds": round(freeze_seconds, 3),
            "time_display": time_display,
            "duration_seconds": round(duration, 3),
            "demo_start_time": round(round_start, 3),
            "demo_end_time": round(round_end, 3),
            "message_count": len(messages),
            "messages": messages,
        })

    return {
        "schema_version": COMMS_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job_id": store.job_dir.name,
        "job_dir": "[job-local]",
        "selected_team_number": selected_team_number,
        "selected_pov_steamid": selected_pov_steamid,
        "export_scope": export_scope,
        "purpose": "CS2 POV Comms Overlay：按回合组织、可人工校对、可渲染到剪映的双语队内通讯流。",
        "time_display": time_display,
        "rounds": feed_rounds,
    }


def _round_review_doc(feed: dict[str, Any], round_doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": COMMS_SCHEMA_VERSION,
        "job_id": feed.get("job_id"),
        "round": round_doc["round"],
        "round_clock_start": round_doc.get("round_clock_start", DEFAULT_ROUND_CLOCK_START),
        "round_clock_end": round_doc.get("round_clock_end", DEFAULT_ROUND_CLOCK_END),
        "freeze_seconds": round_doc.get("freeze_seconds", DEFAULT_FREEZE_SECONDS),
        "time_display": round_doc.get("time_display", feed.get("time_display", "none")),
        "duration_seconds": round_doc.get("duration_seconds"),
        "render_hint": {
            "preset": "pov-float-right",
            "position": "right-middle",
            "note": "人工主要改 zh/source/speaker/enabled；show_at_seconds 只用于内部播放时序，默认不在画面显示时间。",
        },
        "messages": round_doc.get("messages", []),
    }


def _infer_round_number(seg: TranslationSegment, rounds: list[Round]) -> int:
    for r in rounds:
        if r.start_time <= seg.start_time <= r.end_time:
            return r.round_number
    return 0


def _filter_segments(items: list[TranslationSegment], team_number: int | None, pov_steamid: str | None, export_scope: str) -> list[TranslationSegment]:
    if export_scope == "all":
        return items
    if export_scope == "pov_player" and pov_steamid:
        return [x for x in items if x.steamid == pov_steamid]
    if team_number is not None:
        return [x for x in items if x.team_number == team_number]
    return items


def parse_clock(value: str | int | float | None) -> int:
    if value is None:
        return parse_clock(DEFAULT_ROUND_CLOCK_START)
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    text = str(value).strip()
    if not text:
        return 0
    if ":" not in text:
        try:
            return int(round(float(text)))
        except ValueError:
            return 0
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return 0
    return 0


def format_clock(seconds: int | float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_elapsed(seconds: int | float) -> str:
    seconds = max(0, int(round(float(seconds))))
    return f"+{seconds // 60}:{seconds % 60:02d}"


def _normalize_time_display(value: Any) -> str:
    text = str(value or "none").strip().lower().replace("-", "_")
    if text in {"round", "clock", "roundclock"}:
        text = "round_clock"
    if text not in TIME_DISPLAY_VALUES:
        return "none"
    return text


def format_comms_clock(elapsed_seconds: float, freeze_seconds: float, round_start_clock_seconds: int | float) -> str:
    """Format the time shown on Comms Overlay cards.

    CS2 demos generally expose round_start at freeze/preparation start.  The
    on-screen live round clock (for example 1:55) begins only after freezetime.
    Therefore a message that happens 2 seconds after round_start should not be
    labelled 1:53; it should be labelled as preparation time.
    """
    elapsed = max(0.0, float(elapsed_seconds))
    freeze = max(0.0, float(freeze_seconds or 0.0))
    if freeze > 0 and elapsed < freeze:
        remaining = max(0.0, freeze - elapsed)
        return f"准备 {format_clock(remaining)}"
    live_elapsed = max(0.0, elapsed - freeze)
    return format_clock(max(0.0, float(round_start_clock_seconds) - live_elapsed))


def comms_phase(elapsed_seconds: float, freeze_seconds: float, duration_seconds: float, round_start_clock_seconds: int | float) -> str:
    elapsed = max(0.0, float(elapsed_seconds))
    freeze = max(0.0, float(freeze_seconds or 0.0))
    live_duration = max(0.0, float(round_start_clock_seconds))
    if freeze > 0 and elapsed < freeze:
        return "freeze"
    if elapsed > freeze + live_duration:
        return "post_round"
    return "live"


def parse_comms_clock_to_elapsed(value: Any, freeze_seconds: float, round_start_clock_seconds: int | float) -> float:
    """Parse an editable card time back to overlay seconds.

    Supports normal live clock strings like 1:32 and preparation labels like
    准备 0:03 / prep 0:03 / freeze 0:03.
    """
    text = str(value or "").strip()
    freeze = max(0.0, float(freeze_seconds or 0.0))
    lower = text.lower()
    if lower.startswith(("准备", "prep", "freeze")):
        import re
        match = re.search(r"(\d+:\d+|\d+(?:\.\d+)?)", text)
        remaining = parse_clock(match.group(1)) if match else 0
        return max(0.0, freeze - remaining)
    return max(0.0, freeze + float(round_start_clock_seconds) - parse_clock(text))


def _render_feed_markdown(feed: dict[str, Any]) -> str:
    lines = [
        "# CS2 POV 通讯流",
        "",
        f"Job: `{feed.get('job_id')}`",
        f"生成时间: {feed.get('generated_at')}",
        f"导出范围: {feed.get('export_scope')}",
        "",
        "> 这是给人工校对和剪辑前快速查看的静态通讯流。真正用于剪映的素材请由 `cs2pov comms render` 从 review/comms_rounds/round_XX.yaml 渲染。",
        "> v0.9.8 默认不展示回合倒计时：不同平台和不同回合的准备期不稳定，时间仅保留为内部 `show_at_seconds` 渲染时序。",
        "",
    ]
    for r in feed.get("rounds", []):
        lines.append(f"## Round {r.get('round')}｜{r.get('message_count', 0)} 条")
        lines.append("")
        if not r.get("messages"):
            lines.append("_本回合没有通讯消息。_")
            lines.append("")
            continue
        for m in r["messages"]:
            lines.append(f"- **{m.get('speaker')}**")
            lines.append(f"  - 中：{m.get('zh')}")
            lines.append(f"  - EN：{m.get('source')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_feed_html(feed: dict[str, Any]) -> str:
    parts = [
        "<!doctype html>",
        "<html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>CS2 POV 通讯流</title>",
        "<style>",
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;margin:0;background:#111;color:#eee;line-height:1.55}",
        "main{max-width:980px;margin:0 auto;padding:32px 20px 80px}",
        ".meta{color:#aaa}.round{border:1px solid #333;border-radius:14px;padding:18px;margin:20px 0;background:#1a1a1a}",
        ".msg{border-left:3px solid #666;padding:10px 14px;margin:12px 0;background:#202020;border-radius:8px}.head{font-weight:700}.zh{font-size:18px}.en{color:#aaa;font-size:14px}",
        "</style></head><body><main>",
        "<h1>CS2 POV 通讯流</h1>",
        f"<p class='meta'>Job: {html.escape(str(feed.get('job_id')))} ｜ 生成时间: {html.escape(str(feed.get('generated_at')))} ｜ 范围: {html.escape(str(feed.get('export_scope')))}</p>",
        "<p class='meta'>用于快速校对内容。v0.9.8 默认不展示回合倒计时；剪映素材请由 review/comms_rounds/round_XX.yaml 渲染。</p>",
    ]
    for r in feed.get("rounds", []):
        parts.append(f"<section class='round'><h2>Round {int(r.get('round', 0))} <span class='meta'>({int(r.get('message_count', 0))} 条)</span></h2>")
        for m in r.get("messages", []):
            parts.append("<div class='msg'>")
            parts.append(f"<div class='head'>{html.escape(str(m.get('speaker')))}</div>")
            parts.append(f"<div class='zh'>{html.escape(str(m.get('zh')))}</div>")
            parts.append(f"<div class='en'>{html.escape(str(m.get('source')))}</div>")
            parts.append("</div>")
        if not r.get("messages"):
            parts.append("<p class='meta'>本回合没有通讯消息。</p>")
        parts.append("</section>")
    parts.append("</main></body></html>\n")
    return "\n".join(parts)


def _render_review_readme(feed: dict[str, Any], written_rounds: list[Path]) -> str:
    lines = [
        "# Comms Overlay 人工校对文件",
        "",
        "这里的 `round_XX.yaml` 是 Comms Overlay 的关键中间产物。",
        "",
        "推荐流程：",
        "",
        "1. 打开对应回合 YAML，先人工修正 `zh` / `source` / `speaker`。",
        "2. 不想显示的句子改成 `enabled: false`。",
        "3. 保存后运行 `cs2pov comms render <job_dir> --rounds XX`。",
        "4. 把生成的 `final/comms_overlay/round_XX_*` 导入剪映，叠到对应回合视频上。",
        "",
        "可编辑字段：",
        "",
        "- `show_at_seconds`: 内部播放时序，决定这条消息在 overlay 第几秒出现；默认不显示在画面里。",
        "- `show_at`: 旧版/实验倒计时辅助字段；v0.9.8 默认不渲染，除非使用 `--time-display round-clock`。",
        "- `time_display`: 默认 `none`；可实验设置为 `elapsed` 或 `round_clock`，但正式成片不建议展示不可靠倒计时。",
        "- `speaker`: 显示的选手名。",
        "- `zh`: 中文主视觉文本。",
        "- `source`: 英文/原文辅助核对文本。",
        "- `enabled`: false 表示不渲染这一条。",
        "",
        f"已生成回合数：{len(written_rounds)}",
        "",
    ]
    for p in written_rounds:
        lines.append(f"- {p.name}")
    return "\n".join(lines).rstrip() + "\n"


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)
    except Exception:
        import json
        text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except Exception:
        import json
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"YAML 格式不正确：{path}")
    return data


def _normalize_formats(formats: Iterable[str]) -> list[str]:
    allowed = {"preview", "green", "alpha", "png"}
    out: list[str] = []
    for item in formats:
        for raw in str(item).split(","):
            fmt = raw.strip().lower()
            if not fmt:
                continue
            if fmt not in allowed:
                raise ValueError(f"未知 comms render 格式：{fmt}。可选：preview/green/alpha/png。")
            if fmt not in out:
                out.append(fmt)
    return out or ["preview", "green"]


def _round_number_from_path(path: Path) -> int | None:
    import re
    match = re.search(r"round_(\d+)", path.stem)
    return int(match.group(1)) if match else None


def _render_round_video(
    round_file: Path,
    doc: dict[str, Any],
    out_dir: Path,
    fmt: str,
    options: CommsRenderOptions,
    *,
    temp_root: Path,
    subprocess_env: Mapping[str, str] | None = None,
) -> Path:
    if fmt == "png":
        return _render_round_png_state(round_file, doc, out_dir, options)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg。请先安装 ffmpeg，或只导出 --formats png 检查单帧排版。")

    round_no = int(doc.get("round") or _round_number_from_path(round_file) or 0)
    suffix = {"preview": "preview.mp4", "green": "green.mp4", "alpha": "alpha.mov"}[fmt]
    out_path = out_dir / f"round_{round_no:02d}_overlay_{suffix}"
    messages = _enabled_messages(doc)
    duration = _round_duration(doc, options)
    state_times = _state_times(messages, duration, options)

    tmp = temp_root / f"round_{round_no:02d}_{uuid.uuid4().hex}"
    tmp.mkdir(parents=True, exist_ok=False)
    try:
        image_paths: list[Path] = []
        concat_lines: list[str] = []
        for idx, start in enumerate(state_times):
            end = state_times[idx + 1] if idx + 1 < len(state_times) else duration
            if end <= start:
                continue
            img = tmp / f"state_{idx:03d}.png"
            _draw_overlay_state(doc, messages, t=start + 0.001, mode=fmt, options=options, out_path=img)
            image_paths.append(img)
            concat_lines.append(f"file '{img.as_posix()}'")
            concat_lines.append(f"duration {end - start:.3f}")
        if image_paths:
            concat_lines.append(f"file '{image_paths[-1].as_posix()}'")
        concat_path = tmp / "concat.txt"
        concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-r", str(options.fps)]
        if fmt == "alpha":
            cmd += ["-c:v", "qtrle", "-pix_fmt", "argb", str(out_path)]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
        env = dict(subprocess_env or {})
        env.update({"TMP": str(temp_root), "TEMP": str(temp_root), "TMPDIR": str(temp_root)})
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 渲染失败：{proc.stderr[-1200:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path


def _resolve_write_runtime(runtime: WorkspaceRuntime | None) -> WorkspaceRuntime:
    return runtime or WorkspaceRuntimeResolver(JsonWorkspaceSelectionStore(default_state_file())).resolve_for_write()


def _warn_external_job(job_dir: Path, runtime: WorkspaceRuntime, *, warning_stream=None) -> None:
    try:
        job_dir.resolve().relative_to(runtime.paths.jobs_dir.resolve())
    except ValueError:
        import sys
        print("警告：正在原位置修改外部旧 Job；不会自动迁移 Job 路径。", file=warning_stream if warning_stream is not None else sys.stdout)


def _render_round_png_state(round_file: Path, doc: dict[str, Any], out_dir: Path, options: CommsRenderOptions) -> Path:
    round_no = int(doc.get("round") or _round_number_from_path(round_file) or 0)
    out_path = out_dir / f"round_{round_no:02d}_overlay_preview_state.png"
    messages = _enabled_messages(doc)
    t = min(_round_duration(doc, options), max((float(m.get("show_at_seconds", parse_comms_clock_to_elapsed(m.get("show_at"), _freeze_seconds(doc, options), parse_clock(str(doc.get("round_clock_start", options.round_clock_start))))) or 0.0) for m in messages), default=0.0) + 0.1)
    _draw_overlay_state(doc, messages, t=t, mode="preview", options=options, out_path=out_path)
    return out_path


def _round_duration(doc: dict[str, Any], options: CommsRenderOptions) -> float:
    raw = doc.get("duration_seconds")
    try:
        if raw is not None:
            value = float(raw)
            if value > 0:
                return value
    except (TypeError, ValueError):
        pass
    live_duration = max(1.0, parse_clock(doc.get("round_clock_start", options.round_clock_start)) - parse_clock(doc.get("round_clock_end", options.round_clock_end)))
    return max(1.0, _freeze_seconds(doc, options) + live_duration)


def _freeze_seconds(doc: dict[str, Any], options: CommsRenderOptions) -> float:
    raw = doc.get("freeze_seconds", options.freeze_seconds)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return max(0.0, float(options.freeze_seconds))


def _enabled_messages(doc: dict[str, Any]) -> list[dict[str, Any]]:
    start_clock = parse_clock(doc.get("round_clock_start", DEFAULT_ROUND_CLOCK_START))
    freeze_seconds = _freeze_seconds(doc, CommsRenderOptions())
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(doc.get("messages") or [], start=1):
        if row.get("enabled") is False:
            continue
        item = dict(row)
        if item.get("show_at_seconds") is None:
            item["show_at_seconds"] = parse_comms_clock_to_elapsed(item.get("show_at"), freeze_seconds, start_clock)
        try:
            item["show_at_seconds"] = max(0.0, float(item.get("show_at_seconds", 0.0)))
        except (TypeError, ValueError):
            item["show_at_seconds"] = parse_comms_clock_to_elapsed(item.get("show_at"), freeze_seconds, start_clock)
        item.setdefault("id", f"m{idx:03d}")
        out.append(item)
    return sorted(out, key=lambda m: (float(m.get("show_at_seconds", 0.0)), str(m.get("speaker", ""))))


def _state_times(messages: list[dict[str, Any]], duration: float, options: CommsRenderOptions) -> list[float]:
    """Return key times for efficient video rendering.

    v0.9.1 adds a tiny fade-in transition without switching to expensive full
    frame-by-frame rendering.  Around every new message we add a few extra
    states, so the card fades in instead of popping in completely cold.
    """
    times = {0.0, float(duration)}
    fade = max(0.0, float(options.fade_seconds))
    steps = (0.0, 0.12, 0.24, fade) if fade > 0 else (0.0,)
    for msg in messages:
        t = float(msg.get("show_at_seconds", 0.0))
        for offset in steps:
            value = round(t + offset, 3)
            if 0 <= value <= duration:
                times.add(value)
    return sorted(times)


def _draw_overlay_state(doc: dict[str, Any], messages: list[dict[str, Any]], t: float, mode: str, options: CommsRenderOptions, out_path: Path) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        raise RuntimeError("渲染 PNG/视频需要 Pillow。请运行 pip install Pillow，或安装项目的 [comms] 依赖。") from exc

    transparent = mode == "alpha"
    if mode == "green":
        image = Image.new("RGBA", (options.width, options.height), (0, 255, 0, 255))
    elif mode == "preview":
        image = Image.new("RGBA", (options.width, options.height), (28, 28, 28, 255))
    else:
        image = Image.new("RGBA", (options.width, options.height), (0, 0, 0, 0 if transparent else 255))
    draw = ImageDraw.Draw(image, "RGBA")

    panel_w = max(220, int(options.panel_width))
    panel_h = max(220, int(options.panel_height))
    panel_x = max(0, options.width - panel_w - max(0, int(options.right_margin)))
    panel_y = options.y if options.y is not None else int((options.height - panel_h) * 0.50)
    panel_y = max(0, min(panel_y, max(0, options.height - panel_h)))

    font_meta = _load_font(options.font_path, options.font_size_meta)
    font_zh = _load_font(options.font_path, options.font_size_zh)
    font_en = _load_font(options.font_path, options.font_size_en)
    font_title = _load_font(options.font_path, max(options.font_size_zh + 2, 24))

    if options.show_outer_panel:
        panel_alpha = 120 if mode == "alpha" else 190
        draw.rounded_rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + panel_h], radius=22, fill=(0, 0, 0, panel_alpha))
        x = panel_x + 22
        y = panel_y + 18
        content_w = panel_w - 44
        bottom = panel_y + panel_h - 18
    else:
        x = panel_x
        y = panel_y
        content_w = panel_w
        bottom = min(options.height - 24, panel_y + panel_h)

    round_no = doc.get("round", "?")
    _draw_text_with_shadow(draw, (x, y), f"Round {round_no}", font_title, (255, 255, 255, 232))
    header_time = _header_time_text(doc, t, options)
    if header_time:
        clock_x = x + content_w - _text_width(draw, header_time, font_meta)
        _draw_text_with_shadow(draw, (clock_x, y + 5), header_time, font_meta, (230, 230, 230, 205))
    y += _text_height(draw, "Round 00", font_title) + 14

    active = [m for m in messages if float(m.get("show_at_seconds", 0.0)) <= t]
    active = active[-max(1, int(options.max_messages)):]
    visible = _select_visible_messages(draw, active, content_w, y, bottom, font_meta, font_zh, font_en, doc, options)
    if not visible:
        _draw_text_with_shadow(draw, (x + 8, y + 20), "等待本回合通讯...", font_meta, (220, 220, 220, 150))
    for msg in visible:
        alpha = _fade_alpha(msg, t, options)
        y_offset = int((1.0 - alpha) * 10)
        y = _draw_message_card(draw, x, y + y_offset, content_w, msg, font_meta, font_zh, font_en, doc, options, alpha=alpha)
        y += options.card_spacing - y_offset

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if mode in {"preview", "green"}:
        image = image.convert("RGB")
    image.save(out_path)

def _clock_at_time(doc: dict[str, Any], t: float, options: CommsRenderOptions) -> str:
    start = parse_clock(doc.get("round_clock_start", options.round_clock_start))
    return format_comms_clock(t, _freeze_seconds(doc, options), start)


def _time_display_for_doc(doc: dict[str, Any], options: CommsRenderOptions) -> str:
    # CLI options intentionally win over YAML.  v0.9.8 defaults to no visible
    # time because CS2 freezetime / POV clip boundaries vary by platform and
    # even by round.  show_at_seconds remains the internal playback timestamp.
    return _normalize_time_display(getattr(options, "time_display", None) or doc.get("time_display", "none"))


def _header_time_text(doc: dict[str, Any], t: float, options: CommsRenderOptions) -> str:
    display = _time_display_for_doc(doc, options)
    if display == "elapsed":
        return format_elapsed(t)
    if display == "round_clock":
        return _clock_at_time(doc, t, options)
    return ""


def _message_meta(msg: dict[str, Any], doc: dict[str, Any], options: CommsRenderOptions) -> str:
    speaker = str(msg.get("speaker") or "").strip()
    display = _time_display_for_doc(doc, options)
    if display == "elapsed":
        prefix = format_elapsed(float(msg.get("show_at_seconds", 0.0)))
    elif display == "round_clock":
        prefix = str(msg.get("show_at") or "").strip()
    else:
        prefix = ""
    if prefix and speaker:
        return f"{prefix}  {speaker}"
    return speaker or prefix


def _fade_alpha(msg: dict[str, Any], t: float, options: CommsRenderOptions) -> float:
    fade = max(0.0, float(options.fade_seconds))
    if fade <= 0:
        return 1.0
    age = t - float(msg.get("show_at_seconds", 0.0))
    return max(0.0, min(1.0, age / fade))


def _select_visible_messages(
    draw: Any,
    messages: list[dict[str, Any]],
    width: int,
    start_y: int,
    bottom: int,
    font_meta: Any,
    font_zh: Any,
    font_en: Any,
    doc: dict[str, Any],
    options: CommsRenderOptions,
) -> list[dict[str, Any]]:
    """Keep the newest readable cards and never draw past the overlay area.

    v0.9.0 drew a card and only then checked the panel bottom, so a tall last
    card could leak outside the large outer panel.  v0.9.1 measures first and
    drops older cards when needed.  This is closer to a live chat feed: newest
    comms win, older comms disappear cleanly.
    """
    selected: list[dict[str, Any]] = []
    used = 0
    max_h = max(1, bottom - start_y)
    for msg in reversed(messages):
        h = _measure_message_card(draw, width, msg, font_meta, font_zh, font_en, doc, options) + options.card_spacing
        if selected and used + h > max_h:
            break
        if not selected and h > max_h:
            # The card content is already capped to a few lines, so this should
            # be rare.  Still keep the newest message rather than output an
            # empty overlay.
            selected.append(msg)
            break
        selected.append(msg)
        used += h
    return list(reversed(selected))


def _message_card_lines(draw: Any, width: int, msg: dict[str, Any], font_zh: Any, font_en: Any) -> tuple[list[str], list[str]]:
    text_width = max(60, width - 28)
    zh_lines = _wrap_text(str(msg.get("zh") or ""), font_zh, text_width, draw, max_lines=2)
    en_lines = _wrap_text(str(msg.get("source") or ""), font_en, text_width, draw, max_lines=2)
    return zh_lines, en_lines


def _measure_message_card(draw: Any, width: int, msg: dict[str, Any], font_meta: Any, font_zh: Any, font_en: Any, doc: dict[str, Any], options: CommsRenderOptions) -> int:
    zh_lines, en_lines = _message_card_lines(draw, width, msg, font_zh, font_en)
    meta_text = _message_meta(msg, doc, options) or "Player"
    meta_h = _text_height(draw, meta_text, font_meta)
    zh_h = _text_height(draw, "中文Hg", font_zh)
    en_h = _text_height(draw, "English Hg", font_en)
    return 12 + meta_h + 5 + len(zh_lines) * (zh_h + 3) + len(en_lines) * (en_h + 2) + 12


def _draw_message_card(
    draw: Any,
    x: int,
    y: int,
    width: int,
    msg: dict[str, Any],
    font_meta: Any,
    font_zh: Any,
    font_en: Any,
    doc: dict[str, Any],
    options: CommsRenderOptions,
    alpha: float = 1.0,
) -> int:
    alpha = max(0.0, min(1.0, alpha))
    zh_lines, en_lines = _message_card_lines(draw, width, msg, font_zh, font_en)
    card_h = _measure_message_card(draw, width, msg, font_meta, font_zh, font_en, doc, options)
    card_alpha = int(165 * alpha)
    draw.rounded_rectangle([x, y, x + width, y + card_h], radius=13, fill=(18, 18, 18, card_alpha))
    meta = _message_meta(msg, doc, options)
    tx = x + 14
    cur = y + 10
    draw.text((tx, cur), meta, fill=(235, 235, 235, int(225 * alpha)), font=font_meta)
    cur += _text_height(draw, meta or "1:32", font_meta) + 5
    for line in zh_lines:
        draw.text((tx, cur), line, fill=(255, 255, 255, int(242 * alpha)), font=font_zh)
        cur += _text_height(draw, line or "中文", font_zh) + 3
    for line in en_lines:
        draw.text((tx, cur), line, fill=(210, 210, 210, int(175 * alpha)), font=font_en)
        cur += _text_height(draw, line or "English", font_en) + 2
    return y + card_h


def _wrap_text(text: str, font: Any, max_width: int, draw: Any, max_lines: int = 2) -> list[str]:
    text = " ".join(str(text).split())
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    # For CJK-heavy strings, wrapping by character is more reliable; for Latin,
    # keep whole words when possible.
    tokens = list(text) if _looks_cjk(text) else text.split(" ")
    sep = "" if _looks_cjk(text) else " "
    for token in tokens:
        candidate = token if not current else current + sep + token
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = token
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and _text_width(draw, lines[-1], font) > max_width:
        lines[-1] = _ellipsize(lines[-1], font, max_width, draw)
    if len(lines) == max_lines and (len("".join(tokens)) > len("".join(lines))):
        lines[-1] = _ellipsize(lines[-1], font, max_width, draw)
    return lines or [""]


def _looks_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _text_width(draw: Any, text: str, font: Any) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0])
    except Exception:
        return len(text) * 12


def _text_height(draw: Any, text: str, font: Any) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return max(1, int(bbox[3] - bbox[1]))
    except Exception:
        return 18


def _draw_text_with_shadow(draw: Any, xy: tuple[int, int], text: str, font: Any, fill: tuple[int, int, int, int]) -> None:
    x, y = xy
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0, min(180, fill[3])), font=font)
    draw.text((x, y), text, fill=fill, font=font)


def _ellipsize(text: str, font: Any, max_width: int, draw: Any) -> str:
    ell = "…"
    while text and _text_width(draw, text + ell, font) > max_width:
        text = text[:-1]
    return text + ell if text else ell


def _load_font(font_path: str | None, size: int) -> Any:
    from PIL import ImageFont

    candidates: list[str] = []
    if font_path:
        candidates.append(font_path)
    candidates.extend([
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ])
    for candidate in candidates:
        try:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()
