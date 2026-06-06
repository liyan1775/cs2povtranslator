"""cs2tl translate — the main translation pipeline command.

Orchestrates the 7-stage pipeline:
  extract → transcribe → dictionary → rounds → players → translate → subtitles

Respects --from/--to-stage for partial re-runs.
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

from cs2tl.transcriber import PartialSegment

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

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

    output_dir = output
    voices_dir = cache_dir / "voices"
    transcribed_cache = cache_dir / f"{demo_name}.transcribed.jsonl"
    translated_cache = cache_dir / f"{demo_name}.translated.jsonl"

    should_run = _stage_runner(from_stage, to_stage)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:

        # Stage 1: Extract
        if should_run("extract"):
            task = progress.add_task("Extracting voice audio...", total=None)
            try:
                extraction = run_extraction(demo, voices_dir)
                wav_files = extraction.wav_files
                progress.update(task, description=f"Extracted {len(wav_files)} voice files")
            except CS2tlError as e:
                if e.code == "E1-0003":
                    # P1-4: Zero voice = exit 0 (valid result, not an error)
                    console.print(f"[yellow]{e.message}[/yellow]")
                    console.print(e.fix)
                    raise typer.Exit(0)
                exit_with_error(e)
            except CS2tlError as e:
                exit_with_error(e)
            progress.remove_task(task)
        # ---> extract ← here for type checker; wav_files always set if we reach further
        # but for type safety, we handle the resume path below

        # Stage 2: Transcribe
        if should_run("transcribe"):
            task = progress.add_task("Transcribing with Whisper...", total=None)
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
                progress.update(task, description=f"Transcribed {len(partial_segs)} segments")
            except CS2tlError as e:
                exit_with_error(e)
            progress.remove_task(task)

        # Stage 3: Dictionary
        if should_run("dictionary"):
            task = progress.add_task("Loading dictionaries...", total=None)
            try:
                dict_mgr = DictionaryManager(
                    repo_url=config.dictionary.repo_url,
                    local_path=Path(config.dictionary.local_path or ""),
                )
                dict_mgr.load_all()
                progress.update(task, description=f"Loaded dictionaries: {', '.join(dict_mgr.list_maps())}")
            except CS2tlError as e:
                if not no_dictionary:
                    console.print(f"[yellow]Dictionary warning: {e.message}[/yellow]")
                    console.print("Continuing without dictionary. Use --no-dictionary to suppress this warning.")
                dict_mgr = None
            progress.remove_task(task)

        # Stage 4: Rounds
        if should_run("rounds"):
            task = progress.add_task("Detecting rounds...", total=None)
            try:
                rounds = detect_rounds(demo)
                annotated_segs, clock_offset, clock_warnings = annotate_segments(partial_segs, rounds)
                for w in clock_warnings:
                    console.print(f"[yellow]{w}[/yellow]")
                partial_segs = annotated_segs
                progress.update(task, description=f"Detected {len(rounds)} rounds (offset: {clock_offset:.2f}s)")
            except CS2tlError as e:
                console.print(f"[yellow]{e.message}[/yellow]")
                rounds = []
            progress.remove_task(task)

        # Stage 5: Players
        if should_run("players"):
            task = progress.add_task("Resolving player names...", total=None)
            try:
                players = resolve_players(demo, wav_files)
                # Attach team info to segments
                for seg in partial_segs:
                    pid = players.get(getattr(seg, "steam_id", ""))
                    if pid:
                        setattr(seg, "team", pid.team)
                progress.update(
                    task,
                    description=f"Resolved {len(players)} players",
                )
            except CS2tlError as e:
                console.print(f"[yellow]{e.message}[/yellow]")
                players = {}
            progress.remove_task(task)

        # Halftime swap
        if rounds:
            partial_segs = halftime_swap(partial_segs, rounds)

        # Stage 6: Translate
        if should_run("translate"):
            task = progress.add_task(
                f"Translating {'(dry run) ' if dry_run else ''}with LLM...",
                total=None,
            )
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
                    progress.update(task, description=f"Dry run complete: {len(partial_segs)} segments (no API calls)")
                else:
                    progress.update(task, description=f"Translated {len(translated)} segments")
            except CS2tlError as e:
                exit_with_error(e)
            progress.remove_task(task)

        # Stage 7: Subtitles
        if should_run("subtitles"):
            if dry_run:
                console.print("[dim]Dry run: skipping SRT generation.[/dim]")
            else:
                task = progress.add_task("Writing SRT subtitles...", total=None)
                try:
                    srt_files = write_srt(translated, output_dir, demo_name)
                    progress.update(task, description="SRT files written")
                    console.print(f"\n[green]Done! {len(srt_files)} SRT file(s) written to {output_dir}/[/green]")
                    for team, path in srt_files.items():
                        console.print(f"  {path.name} ({team} team)")
                except CS2tlError as e:
                    exit_with_error(e)
                progress.remove_task(task)

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
