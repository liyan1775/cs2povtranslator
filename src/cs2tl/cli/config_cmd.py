"""cs2tl config — manage configuration."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from cs2tl.config import default_config_path, load_config, write_default_config
from cs2tl.errors import CS2tlError

config_app = typer.Typer()
console = Console()


@config_app.command("init")
def config_init() -> None:
    """Interactive first-run configuration wizard."""
    console.print("\n[bold]cs2tl Configuration Setup[/bold]\n")

    existing = default_config_path()
    if existing.exists():
        console.print(f"[yellow]Config already exists at {existing}[/yellow]")
        overwrite = typer.confirm("Overwrite?", default=False)
        if not overwrite:
            console.print("Keeping existing config. Run 'cs2tl config show' to view it.")
            return

    console.print("LLM provider: [dim](openai / anthropic / openrouter)[/dim]")
    provider = typer.prompt("Provider", default="openai")

    console.print("API key: [dim](set OPENAI_API_KEY env var to skip this)[/dim]")
    api_key = typer.prompt("API key", default="", hide_input=True)

    console.print("Model: [dim](gpt-4o / gpt-4o-mini / claude-sonnet-4-6 / etc.)[/dim]")
    model = typer.prompt("Model", default="gpt-4o")

    console.print("Whisper model: [dim](tiny / base / small / medium / large-v3)[/dim]")
    whisper_model = typer.prompt("Whisper model", default="base")

    path = default_config_path()
    try:
        write_default_config(path, provider, api_key, model, whisper_model)
        console.print(f"\n[green]Config written to {path}[/green]")
        console.print("[dim]Tip: Run 'cs2tl doctor' to verify your setup.[/dim]")
    except CS2tlError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@config_app.command("show")
def config_show() -> None:
    """Show current effective configuration."""
    try:
        config = load_config()
    except CS2tlError as e:
        console.print(f"[red]{e}[/red]")
        console.print("Run 'cs2tl config init' to create your configuration.")
        raise typer.Exit(1)

    masked_key = config.llm.api_key[:8] + "..." if len(config.llm.api_key) > 8 else "(not set)"

    info = f"""LLM:
  Provider: {config.llm.provider}
  Model:    {config.llm.model}
  API Key:  {masked_key}
  Base URL: {config.llm.base_url or 'default'}

Whisper:
  Model:  {config.whisper.model}
  Device: {config.whisper.device}

Dictionary:
  Repo URL:    {config.dictionary.repo_url}
  Auto Update: {config.dictionary.auto_update}
  Local Path:  {config.dictionary.local_path}

Cache: {config.cache_dir}"""

    console.print(Panel(info, title=f"cs2tl Configuration", border_style="cyan"))
