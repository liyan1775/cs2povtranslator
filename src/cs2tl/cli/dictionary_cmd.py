"""cs2tl dictionary — manage callout dictionaries."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from cs2tl.config import default_dictionary_dir
from cs2tl.dictionary import DictionaryManager
from cs2tl.errors import CS2tlError

dict_app = typer.Typer()
console = Console()

# P1-8: Known CS2 competitive map whitelist (shared with translate.py)
_KNOWN_MAPS = {
    "de_dust2", "de_mirage", "de_inferno", "de_nuke",
    "de_overpass", "de_vertigo", "de_ancient", "de_anubis",
    "de_train", "de_cache", "de_cbble",
}


def _tsv_dir() -> Path:
    """Return the TSV dictionary directory, creating it if needed."""
    d = default_dictionary_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_map_name(map_name: str) -> None:
    """Reject path separators and non-standard characters in map names."""
    if re.search(r'[/\\\.]{2,}', map_name) or any(c in map_name for c in '/\\'):
        raise typer.BadParameter(
            f"'{map_name}' 不是有效的地图名。请使用例如 de_dust2 格式。"
        )


def _get_manager() -> DictionaryManager:
    """Create a DictionaryManager pointing at the TSV dictionary directory."""
    return DictionaryManager(local_path=_tsv_dir())


def _export_terms_to_tsv(terms: list, tsv_path: Path) -> int:
    """Write CalloutTerm list to a TSV file.  Returns line count."""
    lines = []
    for term in terms:
        en_str = " / ".join(term.aliases)
        ru_str = " / ".join(term.russian_aliases) if term.russian_aliases else "-"
        lines.append(f"{en_str}\t{ru_str}\t{term.chinese_name}\t{term.category}")
    content = "\n".join(lines) + "\n"
    tsv_path.write_text(content, encoding="utf-8")
    return len(lines)


@dict_app.command("update")
def dict_update() -> None:
    """(已移除) 此命令不再可用 — 术语库随 pip install 更新。

    词典数据现在打包在 wheel 中，通过 `pip install -U cs2tl` 更新。
    如需自定义术语，请运行 `cs2tl dictionary init` 导出 TSV 文件后直接编辑，
    或运行 `cs2tl dictionary edit <地图名>` 开始编辑。
    """
    console.print(
        "\n[yellow]此命令已移除。[/yellow]\n\n"
        "内置术语库随 [bold]pip install -U cs2tl[/bold] 更新。\n\n"
        "如需自定义术语：\n"
        "  1. 运行 [bold]cs2tl dictionary init[/bold] 导出所有地图\n"
        "  2. 运行 [bold]cs2tl dictionary edit <地图名>[/bold] 开始编辑\n"
        "  3. 改完保存，下次翻译自动生效\n"
    )


@dict_app.command("list")
def dict_list() -> None:
    """列出所有可用的地图词典（标注 TSV 覆盖）。"""
    try:
        mgr = _get_manager()
        maps = mgr.list_maps()
        if not maps:
            console.print(
                "[yellow]未找到词典数据。[/yellow]\n"
                "请检查 cs2tl 安装是否完整：pip install -U cs2tl"
            )
            return

        tsv_dir = _tsv_dir()

        table = Table(title="报点术语库")
        table.add_column("地图", style="cyan")
        table.add_column("来源", style="dim")
        table.add_column("术语数", justify="right")
        table.add_column("英语别名", justify="right")
        table.add_column("俄语别名", justify="right")

        for m in maps:
            cov = mgr.show_coverage(m)
            has_tsv = (tsv_dir / f"{m}.tsv").exists()
            source = "[green]TSV[/green]" if has_tsv else "[dim]内置[/dim]"
            table.add_row(
                m,
                source,
                str(cov.get("total_terms", "?")),
                str(cov.get("total_aliases", "?")),
                str(cov.get("total_russian_aliases", "?")),
            )

        console.print(table)
        console.print()
        console.print(
            "[dim]TSV = 可编辑  |  内置 = 只读随版本更新  "
            "|  用 [bold]cs2tl dictionary edit <地图>[/bold] 编辑[/dim]"
        )
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


@dict_app.command("edit")
def dict_edit(
    map_name: str = typer.Argument(..., help="地图名称，例如 de_dust2"),
) -> None:
    """用记事本打开地图的 TSV 词典文件。

    如果该地图的 TSV 文件不存在，先从内置词典创建一份副本。

    文件格式（制表符分隔）：
        English / alias \t Russian / алиас \t 中文术语 \t category

    改完后保存，下次翻译时自动生效。
    """
    _validate_map_name(map_name)

    tsv_dir = _tsv_dir()
    tsv_path = tsv_dir / f"{map_name}.tsv"

    # Auto-create from built-in if missing
    if not tsv_path.exists():
        mgr = DictionaryManager()
        builtin = mgr.load_builtin()
        if map_name not in builtin:
            console.print(
                f"[red]未知地图 '{map_name}'。[/red]\n"
                f"已知地图: {', '.join(sorted(DictionaryManager.KNOWN_MAPS))}"
            )
            raise typer.Exit(1)
        n = _export_terms_to_tsv(builtin[map_name].terms, tsv_path)
        console.print(f"[green]已从内置词典创建 {tsv_path} ({n} 术语)[/green]")

    # Open in default editor
    console.print(f"[bold]编辑词典:[/bold] {tsv_path}")
    console.print("[dim]格式: 英文别名 / ... (Tab) 俄文别名 / ... (Tab) 中文 (Tab) 分类[/dim]")
    console.print("[dim]改完保存后，下次翻译自动生效。[/dim]")
    console.print()

    _open_in_editor(tsv_path)


@dict_app.command("init")
def dict_init() -> None:
    """将所有 7 张地图的内置词典导出为 TSV 文件。

    导出到 cs2tl-data/dictionaries/ 目录。
    之后可以用 `cs2tl dictionary edit <map>` 编辑。
    """
    tsv_dir = _tsv_dir()
    mgr = DictionaryManager()
    builtin = mgr.load_builtin()

    created = 0
    for map_name in sorted(builtin.keys()):
        tsv_path = tsv_dir / f"{map_name}.tsv"
        if tsv_path.exists():
            console.print(f"  [dim]跳过 {map_name}.tsv（已存在）[/dim]")
            continue
        n = _export_terms_to_tsv(builtin[map_name].terms, tsv_path)
        created += 1
        console.print(f"  [green]+ {map_name}.tsv ({n} 术语)[/green]")

    console.print()
    console.print(f"✅ 已导出 {created} 张地图到 [bold]{tsv_dir}[/bold]")
    console.print("用 [bold]cs2tl dictionary edit <地图名>[/bold] 编辑")


def _open_in_editor(path: Path) -> None:
    """Open a file in the system's default text editor."""
    path_str = str(path.resolve())
    if sys.platform == "win32":
        os.startfile(path_str)
    elif sys.platform == "darwin":
        subprocess.run(["open", path_str], check=False)
    else:
        subprocess.run(["xdg-open", path_str], check=False)
