"""Web UI routes for CS2 POV Translator.

14 routes covering the full user flow:
  import → progress → preview + edit → glossary CRUD → export

Uses HTMX for partial updates (progress polling, message lazy-load,
inline editing, glossary CRUD). All state is file-based (progress.json,
translated.jsonl, glossary YAML) — no database.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from cs2tl.config import default_cache_dir, default_dictionary_dir

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_JINJA_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))


def _render(template_name: str, context: dict) -> HTMLResponse:
    """Render a Jinja2 template and return an HTMLResponse."""
    template = _JINJA_ENV.get_template(template_name)
    return HTMLResponse(template.render(context))

# In-memory job registry: {job_id: {demo_path, pid, cache_dir}}
# v0.1: single-user, in-memory is fine. v0.2: consider SQLite or file-based.
_jobs: dict[str, dict] = {}

# Total pipeline stages (matches CLI's 7-stage pipeline)
TOTAL_STAGES = 7

STAGE_LABELS = {
    "extract": "提取语音",
    "transcribe": "语音转写",
    "dictionary": "加载词典",
    "rounds": "识别回合",
    "players": "识别球员",
    "translate": "LLM 翻译",
    "subtitles": "生成字幕",
}


# ---------------------------------------------------------------------------
# Route 1-2: Import page
# ---------------------------------------------------------------------------

@router.get("/", response_class=RedirectResponse)
async def index():
    """Redirect root to import page."""
    return RedirectResponse("/import")


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    """Import page — the starting point. No empty state needed."""
    return _render("import.html.j2", {
        "request": request,
        "active_tab": "import",
        "job_id": None,
    })


# ---------------------------------------------------------------------------
# Route 3: Start pipeline
# ---------------------------------------------------------------------------

@router.post("/import", response_class=RedirectResponse)
async def start_pipeline(demo: UploadFile = Form(...)):
    """Accept a demo file upload and start the CLI translation pipeline.

    1. Validate file extension (.dem or .dem.zst).
    2. Save to a job-specific cache directory.
    3. Launch CLI subprocess (D2 decision).
    4. Redirect to progress page.
    """
    if not demo.filename:
        raise HTTPException(400, "请选择一个文件")

    if not (demo.filename.endswith(".dem") or demo.filename.endswith(".dem.zst")):
        raise HTTPException(400, "请上传 .dem 或 .dem.zst 文件")

    job_id = uuid.uuid4().hex[:8]
    cache_dir = Path(default_cache_dir()) / job_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    demo_path = cache_dir / demo.filename
    content = await demo.read()
    demo_path.write_bytes(content)

    logger.info("Job %s: saved demo to %s (%d bytes)", job_id, demo_path, len(content))

    # Quick parse: extract player info for the first relief point
    # (fast — only reads demo header, not the full voice data)
    demo_info = _quick_parse_demo_info(str(demo_path))

    # Launch pipeline in a background thread (v0.1 single-user:
    # simpler than subprocess — no PATH issues, no path mismatch).
    output_dir = cache_dir / "subtitles"
    _jobs[job_id] = {
        "demo_path": str(demo_path),
        "pid": 0,  # no subprocess
        "cache_dir": str(cache_dir),
        "demo_info": demo_info,
    }

    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, str(demo_path), str(output_dir), str(cache_dir)),
        daemon=True,
    )
    thread.start()

    logger.info("Job %s: started pipeline thread for %s", job_id, demo.filename)

    return RedirectResponse(f"/progress/{job_id}", status_code=302)


# ---------------------------------------------------------------------------
# Route 4-5: Progress page + HTMX polling
# ---------------------------------------------------------------------------

@router.get("/progress/{job_id}", response_class=HTMLResponse)
async def progress_page(request: Request, job_id: str):
    """Progress page — 7-stage checklist with HTMX polling every 5 seconds."""
    if job_id not in _jobs:
        raise HTTPException(404, "任务不存在或已过期")

    return _render("progress.html.j2", {
        "request": request,
        "active_tab": "progress",
        "job_id": job_id,
        "demo_info": _jobs[job_id].get("demo_info"),
    })


@router.get("/progress/{job_id}/status", response_class=HTMLResponse)
async def progress_status(job_id: str):
    """HTMX polling endpoint — reads progress.json and returns an HTML fragment.

    Called every 5 seconds by HTMX. Returns a <div> with the current stage
    checklist. When the pipeline completes or errors, includes an HX-Trigger
    header so the frontend can auto-redirect.
    """
    if job_id not in _jobs:
        return HTMLResponse(
            '<div id="progress-panel" class="error">任务不存在或已过期</div>'
        )

    cache_dir = Path(_jobs[job_id]["cache_dir"])
    progress_file = cache_dir / "progress.json"

    if not progress_file.exists():
        # Pipeline hasn't started writing yet
        return HTMLResponse(_render_progress_fragment(None))

    try:
        data = json.loads(progress_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return HTMLResponse(_render_progress_fragment(None))

    return HTMLResponse(_render_progress_fragment(data))


def _render_progress_fragment(data: dict | None) -> str:
    """Render the 7-stage checklist as an HTML fragment."""
    stages = [
        ("extract", "提取语音"),
        ("transcribe", "语音转写"),
        ("dictionary", "加载词典"),
        ("rounds", "识别回合"),
        ("players", "识别球员"),
        ("translate", "LLM 翻译"),
        ("subtitles", "生成字幕"),
    ]

    if data is None:
        current_stage = ""
        done = 0
        error = None
        desc = "正在启动管线..."
    else:
        current_stage = data.get("stage", "")
        done = data.get("done", 0)
        error = data.get("error")
        desc = data.get("stage_desc", "")

    stage_keys = [s[0] for s in stages]
    try:
        current_idx = stage_keys.index(current_stage) if current_stage in stage_keys else -1
    except ValueError:
        current_idx = -1

    items = []
    for i, (key, label) in enumerate(stages):
        if error and i == current_idx:
            cls = "error"
            icon = "❌"
        elif i < done:
            cls = "done"
            icon = "✅"
        elif i == done and not error:
            cls = "current"
            icon = "⏳"
        else:
            cls = "pending"
            icon = "⬜"

        extra = ""
        if i == done and not error and desc:
            extra = f' <span class="stage-detail">{desc}</span>'

        items.append(
            f'<li class="stage-{cls}">{icon} {label}{extra}</li>'
        )

    if error:
        items.append(
            f'<li class="stage-error-detail">'
            f'<p>{error}</p>'
            f'<p class="hint">管线已中断。请检查后重试，或返回导入页重新开始。</p>'
            f'</li>'
        )

    return '<ul id="progress-list" class="stage-list">\n' + "\n".join(items) + "\n</ul>"


# ---------------------------------------------------------------------------
# Route 6-7: Preview page + inline edit
# ---------------------------------------------------------------------------

@router.get("/preview/{job_id}", response_class=HTMLResponse)
async def preview_page(
    request: Request,
    job_id: str,
    team: str = "2",
    offset: int = 0,
    limit: int = 50,
):
    """Preview page — chat-style message flow with lazy loading (D9 decision).

    Query params:
        team:  "2" or "3"
        offset: starting message index
        limit:  messages per batch (default 50)
    """
    if job_id not in _jobs:
        raise HTTPException(404, "任务不存在")

    cache_dir = Path(_jobs[job_id]["cache_dir"])
    demo_name = Path(_jobs[job_id]["demo_path"]).stem
    translated_file = cache_dir / f"{demo_name}.translated.jsonl"

    segments = _load_translated(translated_file, team)
    total = len(segments)
    batch = segments[offset:offset + limit]
    has_more = offset + limit < total

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return HTMLResponse(_render_messages(batch))

    # Count by team for the sidebar
    team_2_count = sum(
        1 for s in _load_translated(translated_file, "2")
    )
    team_3_count = sum(
        1 for s in _load_translated(translated_file, "3")
    )

    return _render("preview.html.j2", {
        "request": request,
        "active_tab": "preview",
        "job_id": job_id,
        "team": team,
        "messages_html": _render_messages(batch),
        "has_more": has_more,
        "next_offset": offset + limit,
        "total": total,
        "team_2_count": team_2_count,
        "team_3_count": team_3_count,
    })


@router.post("/preview/{job_id}/edit/{seg_index}", response_class=HTMLResponse)
async def edit_segment(
    job_id: str,
    seg_index: int,
    translated_text: str = Form(...),
):
    """Edit a single translated segment (HTMX inline edit).

    Writes the edit to a separate edited.jsonl file. Export reads edited
    versions preferentially.
    """
    if job_id not in _jobs:
        raise HTTPException(404)

    cache_dir = Path(_jobs[job_id]["cache_dir"])
    edited_file = cache_dir / "translated_edited.jsonl"

    # Read all segments, update the target, write back
    demo_name = Path(_jobs[job_id]["demo_path"]).stem
    original_file = cache_dir / f"{demo_name}.translated.jsonl"

    all_segs = _read_all_segments(original_file)
    if seg_index < 0 or seg_index >= len(all_segs):
        raise HTTPException(404, "片段不存在")

    all_segs[seg_index]["translated_text"] = translated_text
    all_segs[seg_index]["edited"] = True

    # Write edited file (overwrites each time — last write wins)
    with open(edited_file, "w", encoding="utf-8") as f:
        for seg in all_segs:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")

    logger.info("Job %s: edited segment %d", job_id, seg_index)

    # Return updated message HTML
    seg = all_segs[seg_index]
    return HTMLResponse(_render_one_message(seg, seg_index))


# ---------------------------------------------------------------------------
# Route 8-12: Glossary CRUD
# ---------------------------------------------------------------------------

@router.get("/glossary", response_class=HTMLResponse)
async def glossary_page(request: Request, search: str = ""):
    """Glossary CRUD page (D10 decision — full CRUD editor)."""
    terms = _load_glossary_terms()
    if search:
        q = search.lower()
        terms = [
            t for t in terms
            if q in t.get("en", "").lower() or q in t.get("zh", "")
        ]
    return _render("glossary.html.j2", {
        "request": request,
        "active_tab": "glossary",
        "job_id": None,
        "terms": terms,
        "search": search,
        "total": len(terms),
    })


@router.post("/glossary/add", response_class=HTMLResponse)
async def glossary_add(
    en: str = Form(...),
    zh: str = Form(...),
    aliases: str = Form(""),
    category: str = Form("utility"),
):
    """Add a new term to common/glossary.yml."""
    terms = _load_glossary_terms()
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    new_term = {
        "en": en.strip(),
        "zh": zh.strip(),
        "aliases": alias_list,
        "category": category,
        "source": "user",
    }
    terms.append(new_term)
    _save_glossary_terms(terms)
    logger.info("Glossary: added term '%s' → '%s'", en, zh)

    # Redirect to refresh the glossary page
    resp = RedirectResponse("/glossary", status_code=302)
    resp.headers["HX-Redirect"] = "/glossary"
    return resp


@router.post("/glossary/update/{term_id}", response_class=HTMLResponse)
async def glossary_update(
    term_id: int,
    zh: str = Form(...),
):
    """Update a term's Chinese translation."""
    terms = _load_glossary_terms()
    if term_id < 0 or term_id >= len(terms):
        raise HTTPException(404, "术语不存在")
    if terms[term_id].get("source") != "user":
        raise HTTPException(403, "系统术语不可修改")
    terms[term_id]["zh"] = zh.strip()
    _save_glossary_terms(terms)
    logger.info("Glossary: updated term %d", term_id)
    return HTMLResponse(
        f'<span hx-get="/glossary" hx-trigger="load" hx-target="#term-table" hx-swap="innerHTML"></span>'
    )


@router.delete("/glossary/delete/{term_id}", response_class=HTMLResponse)
async def glossary_delete(term_id: int):
    """Delete a user-added term from the glossary.

    System terms (from map callout dictionaries) cannot be deleted.
    """
    terms = _load_glossary_terms()
    if term_id < 0 or term_id >= len(terms):
        raise HTTPException(404, "术语不存在")

    if terms[term_id].get("source") != "user":
        raise HTTPException(403, "系统术语不可删除")

    deleted = terms.pop(term_id)
    _save_glossary_terms(terms)
    logger.info("Glossary: deleted term '%s'", deleted.get("en", ""))
    # Return empty — HTMX removes the row from DOM
    return HTMLResponse("")


@router.post("/glossary/save", response_class=HTMLResponse)
async def glossary_save():
    """Git commit + push the glossary changes.

    Returns success/error HTML for HTMX swap.
    """
    dict_dir = _get_dictionary_path()
    try:
        result = subprocess.run(
            ["git", "add", "common/glossary.yml"],
            cwd=str(dict_dir),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())

        result = subprocess.run(
            ["git", "commit", "-m", "dict: web update"],
            cwd=str(dict_dir),
            capture_output=True, text=True, timeout=30,
        )
        # Non-zero exit for "nothing to commit" is OK
        committed = result.returncode == 0

        result = subprocess.run(
            ["git", "push"],
            cwd=str(dict_dir),
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())

        if committed:
            return HTMLResponse(
                '<span style="color: #4ade80;">✅ 已保存并推送</span>'
            )
        else:
            return HTMLResponse(
                '<span style="color: var(--color-text-secondary);">无变更需要推送</span>'
            )
    except Exception as e:
        import html
        logger.error("Glossary save failed: %s", e)
        return HTMLResponse(
            f'<span style="color: var(--color-accent);">❌ 推送失败：{html.escape(str(e))}，请检查网络后重试</span>'
        )


# ---------------------------------------------------------------------------
# Route 13-14: Export page + SRT download
# ---------------------------------------------------------------------------

@router.get("/export/{job_id}", response_class=HTMLResponse)
async def export_page(request: Request, job_id: str):
    """Export page — third relief point. Shows stats summary + download buttons."""
    if job_id not in _jobs:
        raise HTTPException(404, "任务不存在")

    cache_dir = Path(_jobs[job_id]["cache_dir"])
    demo_name = Path(_jobs[job_id]["demo_path"]).stem
    edited_file = cache_dir / "translated_edited.jsonl"
    original_file = cache_dir / f"{demo_name}.translated.jsonl"

    # Compute stats
    source_file = edited_file if edited_file.exists() else original_file
    segments = _read_all_segments(source_file) if source_file.exists() else []

    total = len(segments)
    translated = sum(1 for s in segments if s.get("translated_text") and not s["translated_text"].startswith("[翻译失败]"))
    failed = total - translated
    edited = sum(1 for s in segments if s.get("edited"))
    # Dict hits: count segments where translated_text differs notably from original
    dict_hits = 0  # would need dictionary lookup — simplified for v0.1

    # Read progress.json for skipped_frames
    progress_file = cache_dir / "progress.json"
    skipped_frames = 0
    if progress_file.exists():
        try:
            pdata = json.loads(progress_file.read_text(encoding="utf-8"))
            # skipped_frames is not in progress.json currently; placeholder
        except Exception:
            pass

    stats = {
        "total": total,
        "translated": translated,
        "dict_hits": dict_hits,
        "edited": edited,
        "failed": failed,
        "skipped_frames": skipped_frames,
        "preview": _build_srt_preview(source_file) if source_file.exists() else "",
    }

    return _render("export.html.j2", {
        "request": request,
        "active_tab": "export",
        "job_id": job_id,
        "stats": stats,
    })


@router.get("/export/{job_id}/download/{team}", response_class=FileResponse)
async def download_srt(job_id: str, team: str):
    """Download the SRT file for a specific team."""
    if job_id not in _jobs:
        raise HTTPException(404, "任务不存在")

    cache_dir = Path(_jobs[job_id]["cache_dir"])
    demo_name = Path(_jobs[job_id]["demo_path"]).stem
    srt_dir = cache_dir / "subtitles"
    srt_path = srt_dir / f"{demo_name}.team_{team}.srt"

    if not srt_path.exists():
        raise HTTPException(404, "SRT 文件不存在，请先完成翻译")

    return FileResponse(
        srt_path,
        media_type="text/plain; charset=utf-8",
        filename=f"team_{team}.srt",
    )


# ---------------------------------------------------------------------------
# Pipeline runner (runs in background thread)
# ---------------------------------------------------------------------------

def _run_pipeline(job_id: str, demo_path: str, output_dir: str, cache_dir: str) -> None:
    """Run the full 7-stage translation pipeline in a background thread.

    Writes progress.json after each stage so the Web UI can poll for updates.
    Errors are caught and written to progress.json — the thread never crashes
    the web server.
    """
    demo = Path(demo_path)
    output = Path(output_dir)
    cache = Path(cache_dir)

    def write_progress(stage: str, done: int, desc: str, error: str | None = None) -> None:
        progress = {
            "stage": stage, "done": done, "total": TOTAL_STAGES,
            "stage_desc": desc, "error": error,
        }
        (cache / "progress.json").write_text(
            json.dumps(progress, ensure_ascii=False), encoding="utf-8"
        )

    try:
        # Stage 1: Extract
        write_progress("extract", 0, "正在提取语音...")
        from cs2tl.extractor import run_extraction
        voices_dir = cache / "voices"
        extraction = run_extraction(demo, voices_dir)
        wav_files = extraction.wav_files
        write_progress("extract", 1, f"已提取 {len(wav_files)} 名玩家语音")

        # Stage 2: Transcribe
        write_progress("transcribe", 1, "正在语音转写...")
        from cs2tl.config import load_config, resolve_paths
        config = load_config()
        config = resolve_paths(config)
        from cs2tl.transcriber import transcribe_all
        transcribed_cache = cache / f"{demo.stem}.transcribed.jsonl"
        partial_segs = transcribe_all(
            wav_files=wav_files,
            model_name=config.whisper.model,
            device=config.whisper.device,
            cache_path=transcribed_cache,
        )
        write_progress("transcribe", 2, f"转录完成，共 {len(partial_segs)} 段")

        # Stage 3: Dictionary
        write_progress("dictionary", 2, "正在加载词典...")
        from cs2tl.dictionary import DictionaryManager
        dict_mgr = DictionaryManager(
            repo_url=config.dictionary.repo_url,
            local_path=Path(config.dictionary.local_path or ""),
        )
        dict_mgr.load_all()
        write_progress("dictionary", 3, "词典加载完成")

        # Stage 4: Rounds
        write_progress("rounds", 3, "正在识别回合...")
        from cs2tl.round_detector import detect_rounds, annotate_segments, halftime_swap
        try:
            rounds = detect_rounds(demo)
            annotated_segs, clock_offset, _ = annotate_segments(partial_segs, rounds)
            partial_segs = annotated_segs
            write_progress("rounds", 4, f"识别 {len(rounds)} 个回合")
        except Exception as e:
            logger.warning("Round detection failed: %s", e)
            rounds = []
            write_progress("rounds", 4, "回合识别跳过（非关键）")

        # Stage 5: Players
        write_progress("players", 4, "正在识别球员...")
        from cs2tl.player_resolver import resolve_players
        players = resolve_players(demo, list(wav_files.keys()))
        for seg in partial_segs:
            pid = players.get(getattr(seg, "steam_id", ""))
            if pid:
                setattr(seg, "team", pid.team)
        write_progress("players", 5, f"识别 {len(players)} 名球员")

        # Halftime swap
        if rounds:
            partial_segs = halftime_swap(partial_segs, rounds)

        # Stage 6: Translate
        write_progress("translate", 5, "正在 LLM 翻译...")
        from cs2tl.translator import translate_all
        translated_cache = cache / f"{demo.stem}.translated.jsonl"
        translated = translate_all(
            segments=partial_segs,
            players=players,
            rounds=rounds,
            map_name=None,
            dictionary_manager=dict_mgr,
            llm_config=config.llm,
            target_language="zh",
            no_dictionary=False,
            prompt_template=None,
            cache_path=translated_cache,
            dry_run=False,
        )
        write_progress("translate", 6, f"翻译完成，共 {len(translated)} 条")

        # Stage 7: Subtitles
        write_progress("subtitles", 6, "正在生成字幕...")
        from cs2tl.subtitles import write_srt
        srt_files = write_srt(translated, output, demo.stem)
        write_progress("subtitles", 7, f"字幕已生成，共 {len(srt_files)} 个文件")

        logger.info("Job %s: pipeline complete — %d segments, %d SRT files",
                     job_id, len(translated), len(srt_files))

    except Exception as e:
        logger.error("Job %s: pipeline failed — %s", job_id, e)
        # Try to write error progress — stage may not be set
        try:
            write_progress("translate", 5, str(e)[:100], error=str(e))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _load_translated(jsonl_path: Path, team: str | None = None) -> list[dict]:
    """Load translated segments from JSONL, optionally filtered by team."""
    if not jsonl_path.exists():
        return []
    segments = _read_all_segments(jsonl_path)
    if team:
        segments = [s for s in segments if str(s.get("team", "")) == team]
    segments.sort(key=lambda s: s.get("start_time", 0))
    return segments


def _read_all_segments(jsonl_path: Path) -> list[dict]:
    """Read all segments from a JSONL file."""
    if not jsonl_path.exists():
        return []
    segments = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                seg = json.loads(line)
                seg["_index"] = i
                segments.append(seg)
            except json.JSONDecodeError:
                continue
    return segments


def _render_messages(segments: list[dict]) -> str:
    """Render a batch of messages as HTML."""
    if not segments:
        return '<div class="empty-state">暂无消息</div>'
    return "\n".join(
        _render_one_message(seg, seg.get("_index", i))
        for i, seg in enumerate(segments)
    )


def _render_one_message(seg: dict, index: int) -> str:
    """Render a single chat message as HTML."""
    player = seg.get("player_name", "unknown")
    start = seg.get("start_time", 0)
    minutes = int(start // 60)
    seconds = int(start % 60)
    ts = f"{minutes:02d}:{seconds:02d}"

    original = seg.get("original_text", "")
    translated = seg.get("translated_text", "")
    edited = seg.get("edited", False)

    edit_marker = ' <span class="edited-mark">✏️</span>' if edited else ""

    return f"""
<div id="msg-{index}" class="chat-message" onclick="openEditor({index}, this)">
  <div class="msg-header">
    <span class="msg-player">{player}</span>
    <span class="msg-time">{ts}</span>{edit_marker}
  </div>
  <div class="msg-original">{original}</div>
  <div class="msg-translated">{translated}</div>
</div>"""


def _get_dictionary_path() -> Path:
    """Resolve the dictionary directory from config, falling back to default."""
    try:
        from cs2tl.config import load_config
        config = load_config()
        lp = config.dictionary.local_path
        if lp and Path(lp).exists():
            return Path(lp)
    except Exception:
        pass
    return default_dictionary_dir()


def _load_glossary_terms() -> list[dict]:
    """Load glossary terms from per-map zones.yml + common/glossary.yml.

    Merges two sources:
      1. Per-map callout dictionaries (zones.yml) — read-only system terms
      2. common/glossary.yml — user-added/edited terms
    User terms override system terms with the same 'en' key.
    """
    import yaml

    dict_dir = _get_dictionary_path()
    seen: set[str] = set()
    terms: list[dict] = []

    # 1. Load per-map callout terms (zones.yml)
    if dict_dir.exists():
        for entry in sorted(dict_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            zones_yml = entry / "zones.yml"
            if not zones_yml.exists():
                continue
            try:
                with open(zones_yml, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    for raw in data.get("terms", []):
                        if not isinstance(raw, dict):
                            continue
                        aliases = raw.get("aliases", [])
                        zh = raw.get("chinese", "")
                        if not aliases or not zh:
                            continue
                        en = aliases[0]  # primary alias as the key
                        if en.lower() in seen:
                            continue
                        seen.add(en.lower())
                        terms.append({
                            "en": en,
                            "zh": zh,
                            "aliases": aliases[1:],
                            "category": raw.get("category", "zone"),
                            "source": entry.name,  # which map
                        })
            except Exception:
                continue

    # 2. Load user glossary (common/glossary.yml) — overrides system terms
    glossary_path = dict_dir / "common" / "glossary.yml"
    if glossary_path.exists():
        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                user_data = yaml.safe_load(f)
            if isinstance(user_data, dict):
                for en, info in user_data.items():
                    if not isinstance(info, dict):
                        continue
                    zh = info.get("zh", "")
                    if not zh:
                        continue
                    # Check if this overrides a system term
                    key = en.lower()
                    if key in seen:
                        # Replace the existing term
                        for i, t in enumerate(terms):
                            if t["en"].lower() == key:
                                terms[i] = {
                                    "en": en,
                                    "zh": zh,
                                    "aliases": info.get("en_aliases", []),
                                    "category": info.get("category", "user"),
                                    "source": "user",
                                }
                                break
                    else:
                        seen.add(key)
                        terms.append({
                            "en": en,
                            "zh": zh,
                            "aliases": info.get("en_aliases", []),
                            "category": info.get("category", "user"),
                            "source": "user",
                        })
        except Exception:
            pass

    return terms


def _save_glossary_terms(terms: list[dict]) -> None:
    """Save user glossary terms back to common/glossary.yml (YAML format).

    Only saves user-added terms (source='user') — never overwrites system
    callout dictionary files.
    """
    import yaml

    dict_dir = _get_dictionary_path()
    common_dir = dict_dir / "common"
    common_dir.mkdir(parents=True, exist_ok=True)

    # Only save user-added/edited terms — never overwrite system callout dicts
    user_terms = [t for t in terms if t.get("source") == "user"]
    data = {}
    for t in user_terms:
        en = t["en"]
        data[en] = {
            "zh": t["zh"],
            "en_aliases": t.get("aliases", []),
            "category": t.get("category", "utility"),
        }

    glossary_path = common_dir / "glossary.yml"
    with open(glossary_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def _render_glossary_row(term: dict, index: int) -> str:
    """Render a single glossary table row as HTML."""
    aliases = ", ".join(term.get("aliases", []))
    source_label = term.get("source", "")
    if source_label == "user":
        source_display = "✏️ 用户"
    else:
        source_display = source_label

    delete_btn = ""
    if term.get("source") == "user":
        delete_btn = (
            f'<button hx-delete="/glossary/delete/{index}"'
            f'        hx-target="#term-{index}" hx-swap="outerHTML"'
            f'        hx-confirm="确定删除 \'{term["en"]}\'？"'
            f'        style="background:transparent;color:var(--color-accent);">🗑</button>'
        )
    else:
        delete_btn = (
            '<span style="color:var(--color-text-secondary);font-size:0.8em;"'
            ' title="系统术语不可删除">🔒</span>'
        )

    return f"""
<tr id="term-{index}">
  <td><strong>{term['en']}</strong></td>
  <td>{term['zh']}</td>
  <td><span class="badge badge-{term.get('category', '')}">{term.get('category', '')}</span></td>
  <td style="color:var(--color-text-secondary);font-size:0.85em;">{source_display}</td>
  <td style="color:var(--color-text-secondary);font-size:0.9em;">{aliases}</td>
  <td>{delete_btn}</td>
</tr>"""


def _build_srt_preview(jsonl_path: Path) -> str:
    """Build a preview of the first 20 SRT entries."""
    segments = _read_all_segments(jsonl_path)[:20]
    lines = []
    for i, seg in enumerate(segments):
        player = seg.get("player_name", "unknown")
        text = seg.get("translated_text", "") or seg.get("original_text", "")
        start = seg.get("start_time", 0)
        end = seg.get("end_time", start + 2.0)
        lines.append(f"{i + 1}")
        lines.append(
            f"{_format_ts(start)} --> {_format_ts(end)}"
        )
        lines.append(f"{player}: {text}")
        lines.append("")
    return "\n".join(lines)


def _format_ts(seconds: float) -> str:
    """Format seconds to SRT timestamp: HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    whole = int(s)
    ms = int((s - whole) * 1000)
    return f"{h:02d}:{m:02d}:{whole:02d},{ms:03d}"


def _quick_parse_demo_info(demo_path: str) -> dict | None:
    """Quickly parse demo metadata for the first relief point (import page).

    Reads player names and teams via demoparser2 — fast (~1-2s) since it
    only reads the demo header, not the full voice data.

    Returns:
        dict with keys: filename, player_count, team_2 (list of names),
        team_3 (list of names), or None if parsing fails.
    """
    import traceback

    demo = Path(demo_path)
    info: dict = {
        "filename": demo.name,
        "player_count": 0,
        "team_2": [],
        "team_3": [],
    }

    try:
        actual_path = demo_path
        tmp_dem = None

        # Handle .zst
        if demo.suffix == ".zst":
            from cs2tl.shared import decompress_zst
            tmp_dem = decompress_zst(demo)
            actual_path = str(tmp_dem)

        from demoparser2 import DemoParser
        parser = DemoParser(actual_path)
        df = parser.parse_player_info()

        for _, row in df.iterrows():
            sid = str(int(row["steamid"]))
            # Filter BOTs
            if len(sid) == 17 and sid.startswith("7656"):
                name = str(row["name"])
                team_num = int(row["team_number"])

                if team_num == 2:
                    info["team_2"].append(name)
                elif team_num == 3:
                    info["team_3"].append(name)

        info["player_count"] = len(info["team_2"]) + len(info["team_3"])
        logger.info(
            "Quick parse: %d players — Team 2: %s | Team 3: %s",
            info["player_count"],
            ", ".join(info["team_2"]) if info["team_2"] else "—",
            ", ".join(info["team_3"]) if info["team_3"] else "—",
        )

        # Cleanup temp file
        if tmp_dem is not None:
            try:
                tmp_dem.unlink()
            except OSError:
                pass

    except Exception:
        logger.warning("Quick demo parse failed, relief point skipped:\n%s",
                       traceback.format_exc())
        return None

    if info["player_count"] == 0:
        return None

    return info
