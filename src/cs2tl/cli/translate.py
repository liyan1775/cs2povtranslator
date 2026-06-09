"""cs2tl translate — the main translation pipeline command.

Orchestrates the 7-stage pipeline:
  extract → transcribe → dictionary → rounds → players → translate → subtitles

Respects --from/--to-stage for partial re-runs.
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

from cs2tl.transcriber import PartialSegment

import typer
from rich.console import Console

logger = logging.getLogger(__name__)

from cs2tl.cli.progress import PipelineProgress
from cs2tl.config import load_config, resolve_paths
from cs2tl.dictionary import DictionaryManager
from cs2tl.errors import (
    CS2tlError,
    exit_with_error,
    invalid_map_name,
)
from cs2tl.extractor import run_extraction
from cs2tl.player_resolver import resolve_players
from cs2tl.round_detector import (
    annotate_segments,
    detect_rounds,
    halftime_swap,
)
from cs2tl.subtitles import write_srt
from cs2tl.transcriber import transcribe_all
from cs2tl.translator import translate_all

console = Console()

# P1-8: Known CS2 competitive map whitelist
KNOWN_MAPS = {
    "de_dust2", "de_mirage", "de_inferno", "de_nuke",
    "de_overpass", "de_vertigo", "de_ancient", "de_anubis",
    "de_train", "de_cache", "de_cbble",
}

VALID_STAGES = {"extract", "transcribe", "dictionary", "rounds", "players", "translate", "subtitles"}


def translate_cmd(
    demo: Path = typer.Argument(..., help="Path to CS2 .dem file"),
    map_name: str | None = typer.Option(None, "--map", help="Map name (e.g., de_dust2)"),
    source: str = typer.Option("auto", "--source", help="Source language hint for Whisper"),
    to: str = typer.Option("zh", "--to", help="Target language for translation"),
    output: Path = typer.Option(Path("./subtitles"), "--output", "-o", help="Output directory for SRT files"),
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    from_stage: str | None = typer.Option(None, "--from", help="Resume from stage"),
    to_stage: str | None = typer.Option(None, "--to-stage", help="Stop after stage"),
    no_dictionary: bool = typer.Option(False, "--no-dictionary", help="Disable dictionary term injection"),
    prompt_template: str | None = typer.Option(None, "--prompt-template", help="Custom system prompt template file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Estimate cost without calling LLM API"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress non-error output"),
    machine_readable: bool = typer.Option(
        False, "--machine-readable", hidden=True,
        help="Write progress.json for Web UI consumption",
    ),
) -> None:
    """Translate CS2 Faceit demo voice comms into Chinese SRT subtitles."""
    _setup_logging(verbose, quiet)

    # Validate inputs
    _validate_map_name(map_name)

    if from_stage and from_stage not in VALID_STAGES:
        console.print(f"[red]Invalid --from stage. Valid stages: {', '.join(sorted(VALID_STAGES))}[/red]")
        raise typer.Exit(1)
    if to_stage and to_stage not in VALID_STAGES:
        console.print(f"[red]Invalid --to-stage. Valid stages: {', '.join(sorted(VALID_STAGES))}[/red]")
        raise typer.Exit(1)

    # Load config
    try:
        config = load_config(cli_config_path=config_path)
        config = resolve_paths(config)
    except CS2tlError as e:
        exit_with_error(e)

    demo_name = demo.stem
    cache_dir = Path(config.cache_dir) / demo_name
    cache_dir.mkdir(parents=True, exist_ok=True)

    # When --machine-readable, write progress.json next to the demo file
    # so the Web UI can find it (the Web saves demos to job-specific dirs).
    progress_dir = demo.parent if machine_readable else cache_dir

    output_dir = output
    voices_dir = cache_dir / "voices"
    transcribed_cache = cache_dir / f"{demo_name}.transcribed.jsonl"
    translated_cache = cache_dir / f"{demo_name}.translated.jsonl"

    should_run = _stage_runner(from_stage, to_stage)

    with PipelineProgress(enabled=not quiet) as pp:

        # wav_files is set in stage 1; may be empty list if --from skips extract
        wav_files: list[Path] = []
        voice_packet_info: dict[str, list[dict]] | None = None

        # Stage 1: Extract
        if should_run("extract"):
            task = pp.task_extract()
            try:
                extraction = run_extraction(demo, voices_dir)
                wav_files = extraction.wav_files
                voice_packet_info = extraction.voice_packet_info
                pp.stage_done(task, f"已提取 {len(wav_files)} 名玩家语音")
                if machine_readable:
                    _write_progress("extract", 1, 7, f"已提取 {len(wav_files)} 名玩家语音", cache_dir=progress_dir)
            except CS2tlError as e:
                if e.code == "E1-0003":
                    # P1-4: Zero voice = exit 0 (valid result, not an error)
                    if machine_readable:
                        _write_progress("extract", 1, 7, e.message, error=e.message, cache_dir=progress_dir)
                    pp.stage_failed(task, e.message)
                    console.print(f"[yellow]{e.message}[/yellow]")
                    console.print(e.fix)
                    raise typer.Exit(0)
                pp.stage_failed(task, e.message)
                exit_with_error(e)
        # wav_files stays as [] if extract stage was skipped via --from

        # Stage 2: Transcribe
        if should_run("transcribe"):
            task = pp.task_transcribe(len(wav_files) if wav_files else None)
            try:
                if from_stage in (None, "extract", "transcribe"):
                    partial_segs = transcribe_all(
                        wav_files=wav_files,
                        model_name=config.whisper.model,
                        device=config.whisper.device,
                        cache_path=transcribed_cache,
                    )
                else:
                    # Loading from cache
                    from cs2tl.transcriber import load_cached_transcript
                    partial_segs = load_cached_transcript(transcribed_cache)
                    console.print(f"Loaded {len(partial_segs)} segments from transcription cache")
                pp.stage_done(task, f"转录完成，共 {len(partial_segs)} 段")
                if machine_readable:
                    _write_progress("transcribe", 2, 7, f"转录完成，共 {len(partial_segs)} 段", cache_dir=progress_dir)
            except CS2tlError as e:
                if machine_readable:
                    _write_progress("transcribe", 2, 7, e.message, error=e.message, cache_dir=progress_dir)
                pp.stage_failed(task, e.message)
                exit_with_error(e)

        # Align Whisper's WAV-relative timestamps → demo timestamps
        if voice_packet_info:
            from cs2tl.extractor import align_transcriber_timestamps
            partial_segs = align_transcriber_timestamps(partial_segs, voice_packet_info)
            logger.info("Aligned %d segments to demo timestamps", len(partial_segs))
            # Rewrite transcribed cache with aligned timestamps
            try:
                import dataclasses
                transcribed_cache.write_text(
                    "\n".join(
                        json.dumps(dataclasses.asdict(s), ensure_ascii=False)
                        for s in partial_segs
                    ),
                    encoding="utf-8",
                )
            except Exception:
                pass

        # Stage 3: Dictionary
        if should_run("dictionary"):
            task = pp.task_dictionary()
            try:
                dict_mgr = DictionaryManager(
                    repo_url=config.dictionary.repo_url,
                    local_path=Path(config.dictionary.local_path or ""),
                )
                dict_mgr.load_all()
                pp.stage_done(task, f"词典加载完成: {', '.join(dict_mgr.list_maps())}")
                if machine_readable:
                    _write_progress("dictionary", 3, 7, "词典加载完成", cache_dir=progress_dir)
            except CS2tlError as e:
                if not no_dictionary:
                    console.print(f"[yellow]Dictionary warning: {e.message}[/yellow]")
                    console.print("Continuing without dictionary. Use --no-dictionary to suppress this warning.")
                dict_mgr = None
                pp.stage_done(task, "词典跳过（已禁用）")

        # Stage 4: Rounds
        if should_run("rounds"):
            task = pp.task_rounds()
            try:
                rounds = detect_rounds(demo)
                annotated_segs, clock_offset, clock_warnings = annotate_segments(partial_segs, rounds)
                for w in clock_warnings:
                    console.print(f"[yellow]{w}[/yellow]")
                partial_segs = annotated_segs
                pp.stage_done(task, f"识别 {len(rounds)} 个回合 (offset: {clock_offset:.2f}s)")
                if machine_readable:
                    _write_progress("rounds", 4, 7, f"识别 {len(rounds)} 个回合", cache_dir=progress_dir)
            except CS2tlError as e:
                console.print(f"[yellow]{e.message}[/yellow]")
                rounds = []
                pp.stage_done(task, "回合识别跳过")

        # Stage 5: Players
        if should_run("players"):
            task = pp.task_players(len(wav_files))
            try:
                players = resolve_players(demo, list(wav_files.keys()))
                # Attach team info to segments
                for seg in partial_segs:
                    pid = players.get(getattr(seg, "steam_id", ""))
                    if pid:
                        setattr(seg, "team", pid.team)
                pp.stage_done(task, f"识别 {len(players)} 名球员")
                if machine_readable:
                    _write_progress("players", 5, 7, f"识别 {len(players)} 名球员", cache_dir=progress_dir)
            except CS2tlError as e:
                console.print(f"[yellow]{e.message}[/yellow]")
                players = {}
                pp.stage_done(task, "球员识别跳过")

        # Halftime swap
        if rounds:
            partial_segs = halftime_swap(partial_segs, rounds)

        # Stage 6: Translate
        if should_run("translate"):
            segment_count = len(partial_segs)
            task = pp.task_translate(max(segment_count, 1))
            try:
                # Load custom prompt template if specified
                custom_prompt = None
                if prompt_template:
                    custom_prompt = Path(prompt_template).read_text(encoding="utf-8")

                translated = translate_all(
                    segments=partial_segs,
                    players=players,
                    rounds=rounds,
                    map_name=map_name,
                    dictionary_manager=dict_mgr,
                    llm_config=config.llm,
                    target_language=to,
                    no_dictionary=no_dictionary,
                    prompt_template=custom_prompt,
                    cache_path=translated_cache,
                    dry_run=dry_run,
                )
                if dry_run:
                    pp.stage_done(task, f"Dry run: {segment_count} segments (no API)")
                else:
                    pp.stage_done(task, f"翻译完成，共 {len(translated)} 条")
                if machine_readable:
                    _write_progress("translate", 6, 7, f"翻译完成，共 {len(translated) if not dry_run else segment_count} 条", cache_dir=progress_dir)
            except CS2tlError as e:
                if machine_readable:
                    _write_progress("translate", 6, 7, e.message, error=e.message, cache_dir=progress_dir)
                pp.stage_failed(task, e.message)
                exit_with_error(e)

        # Stage 7: Subtitles
        if should_run("subtitles"):
            if dry_run:
                console.print("[dim]Dry run: skipping SRT generation.[/dim]")
            else:
                task = pp.task_subtitles(2)  # 2 teams
                try:
                    srt_files = write_srt(translated, output_dir, demo_name)
                    pp.stage_done(task, f"字幕生成: {len(srt_files)} 个文件")
                    if machine_readable:
                        _write_progress("subtitles", 7, 7, f"字幕已生成，共 {len(srt_files)} 个文件", cache_dir=progress_dir)
                    console.print(f"\n[green]Done! {len(srt_files)} SRT file(s) written to {output_dir}/[/green]")
                    for team, path in srt_files.items():
                        console.print(f"  {path.name} ({team} team)")
                except CS2tlError as e:
                    if machine_readable:
                        _write_progress("subtitles", 7, 7, e.message, error=e.message, cache_dir=progress_dir)
                    pp.stage_failed(task, e.message)
                    exit_with_error(e)

    if not dry_run and should_run("subtitles"):
        console.print("\n[bold green]Ready for import into 剪映 / Premiere Pro[/bold green]")


def _stage_runner(from_stage: str | None, to_stage: str | None):
    """Return a function that checks whether a given stage should run."""
    stages = ["extract", "transcribe", "dictionary", "rounds", "players", "translate", "subtitles"]

    start_idx = stages.index(from_stage) if from_stage else 0
    end_idx = stages.index(to_stage) + 1 if to_stage else len(stages)

    valid = set(stages[start_idx:end_idx])

    def should_run(stage: str) -> bool:
        return stage in valid

    return should_run


def _validate_map_name(map_name: str | None) -> None:
    """P1-8: Validate map name against known CS2 maps whitelist."""
    if map_name is None:
        return
    # Reject path separators and special characters
    for char in "/\\.":
        if char in map_name:
            raise invalid_map_name(map_name, list(KNOWN_MAPS))
    if map_name.lower() not in {m.lower() for m in KNOWN_MAPS}:
        raise invalid_map_name(map_name, list(KNOWN_MAPS))


def _setup_logging(verbose: bool, quiet: bool) -> None:
    # Fix Unicode encoding on Windows terminals (otherwise Rich spinner chars fail)
    if sys.platform == "win32" and sys.stdout.encoding.lower() in ("gbk", "cp936", "cp1252"):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _write_progress(
    stage: str,
    done: int,
    total: int,
    desc: str,
    error: str | None = None,
    cache_dir: Path | None = None,
) -> None:
    """Write progress.json for Web UI consumption (--machine-readable mode).

    Only writes when cache_dir is provided (set by --machine-readable flag).
    The file is overwritten each call so the Web UI always sees the latest state.
    """
    if cache_dir is None:
        return
    progress = {
        "stage": stage,
        "done": done,
        "total": total,
        "stage_desc": desc,
        "error": error,
    }
    (cache_dir / "progress.json").write_text(
        json.dumps(progress, ensure_ascii=False), encoding="utf-8"
    )
