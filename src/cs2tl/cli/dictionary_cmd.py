"""cs2tl dictionary — manage callout dictionaries."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from cs2tl.dictionary import DictionaryManager
from cs2tl.errors import CS2tlError

dict_app = typer.Typer()
console = Console()


def _get_manager() -> DictionaryManager:
    """Create a DictionaryManager that loads the built-in dictionary.

    No git clone needed — the dictionary ships with the wheel.
    """
    return DictionaryManager()


@dict_app.command("update")
def dict_update() -> None:
    """(已移除) 此命令不再可用 — 内置词典随 pip install 更新。

    词典数据现在打包在 wheel 中，通过 `pip install -U cs2tl` 更新。
    如需自定义术语，请在 cs2tl-data/dictionaries/ 目录中放置 YAML 文件。
    """
    console.print(
        "\n[yellow]此命令已移除。[/yellow]\n\n"
        "内置词典随 [bold]pip install -U cs2tl[/bold] 更新。\n\n"
        "如需添加自定义术语，请将 YAML 文件放入\n"
        "[dim]cs2tl-data/dictionaries/[/dim] 目录中"
        "（每个地图一个子目录，内含 zones.yml）。\n"
        "新术语会自动与内置词典合并。\n"
    )


@dict_app.command("list")
def dict_list() -> None:
    """列出所有可用的地图词典。"""
    try:
        mgr = _get_manager()
        maps = mgr.list_maps()
        if not maps:
            console.print(
                "[yellow]未找到词典数据。[/yellow]\n"
                "请检查 cs2tl 安装是否完整：pip install -U cs2tl"
            )
            return

        table = Table(title="内置报点术语库")
        table.add_column("地图", style="cyan")
        table.add_column("术语数", justify="right")
        table.add_column("英语别名", justify="right")
        table.add_column("俄语别名", justify="right")

        for m in maps:
            cov = mgr.show_coverage(m)
            table.add_row(
                m,
                str(cov.get("total_terms", "?")),
                str(cov.get("total_aliases", "?")),
                str(cov.get("total_russian_aliases", "?")),
            )

        console.print(table)
    except CS2tlError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@dict_app.command("show")
def dict_show(map_name: str = typer.Argument(..., help="地图名称，例如 de_dust2")) -> None:
    """查看指定地图的术语覆盖情况。"""
    try:
        mgr = _get_manager()
        cov = mgr.show_coverage(map_name)
        if "error" in cov:
            console.print(f"[red]{cov['error']}[/red]")
            console.print(
                f"\n已知地图: {', '.join(sorted(DictionaryManager.KNOWN_MAPS))}"
            )
            raise typer.Exit(1)

        console.print(
            f"\n[bold cyan]{map_name}[/bold cyan] — "
            f"{cov['total_terms']} 术语, {cov['total_aliases']} 英语别名, "
            f"{cov.get('total_russian_aliases', 0)} 俄语别名"
        )
        console.print(f"版本: {cov['version']}")
        console.print(
            "分类: " + ", ".join(
                f"{k}({v})" for k, v in cov.get("by_category", {}).items()
            )
        )
        console.print()

        # Also print the term table
        table = mgr.build_term_table(map_name)
        console.print(table)
    except CS2tlError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
