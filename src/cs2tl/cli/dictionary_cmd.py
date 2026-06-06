"""cs2tl dictionary — manage callout dictionaries."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from cs2tl.config import load_config
from cs2tl.dictionary import DictionaryManager
from cs2tl.errors import CS2tlError

dict_app = typer.Typer()
console = Console()


def _get_manager() -> DictionaryManager:
    config = load_config()
    local_path = config.dictionary.local_path or None
    if not local_path:
        console.print("[red]Dictionary path not configured.[/red]")
        raise typer.Exit(1)
    return DictionaryManager(repo_url=config.dictionary.repo_url, local_path=local_path)


@dict_app.command("update")
def dict_update() -> None:
    """Pull the latest dictionary updates from the remote repository."""
    try:
        mgr = _get_manager()
        console.print("Updating callout dictionaries...")
        updated = mgr.update()
        if updated:
            console.print("[green]Dictionaries updated successfully.[/green]")
            mgr.load_all()
            maps = mgr.list_maps()
            console.print(f"Available maps: {', '.join(maps)}")
        else:
            console.print("Dictionaries already up to date.")
    except CS2tlError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@dict_app.command("list")
def dict_list() -> None:
    """List all installed map dictionaries."""
    try:
        mgr = _get_manager()
        maps = mgr.list_maps()
        if not maps:
            console.print("[yellow]No dictionaries installed. Run 'cs2tl dict update' to fetch them.[/yellow]")
            return

        table = Table(title="Installed Callout Dictionaries")
        table.add_column("Map", style="cyan")
        table.add_column("Terms", justify="right")
        table.add_column("Aliases", justify="right")

        for m in maps:
            cov = mgr.show_coverage(m)
            table.add_row(m, str(cov.get("total_terms", "?")), str(cov.get("total_aliases", "?")))

        console.print(table)
    except CS2tlError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@dict_app.command("show")
def dict_show(map_name: str = typer.Argument(..., help="Map name, e.g., de_dust2")) -> None:
    """Show callout coverage for a specific map."""
    try:
        mgr = _get_manager()
        cov = mgr.show_coverage(map_name)
        if "error" in cov:
            console.print(f"[red]{cov['error']}[/red]")
            raise typer.Exit(1)

        console.print(f"\n[bold cyan]{map_name}[/bold cyan] — {cov['total_terms']} terms, {cov['total_aliases']} aliases")
        console.print(f"Version: {cov['version']}")
        console.print("Categories:", ", ".join(f"{k}({v})" for k, v in cov.get("by_category", {}).items()))
        console.print()

        # Also print the term table
        table = mgr.build_term_table(map_name)
        console.print(table)
    except CS2tlError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
