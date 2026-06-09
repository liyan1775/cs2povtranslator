"""cs2tl wizard — interactive guided translation for first-time users.

Four-step wizard:
  1. Welcome + environment check (reuses doctor._run_checks)
  2. Select demo file (auto-scan + Rich prompt)
  3. Confirm parameters (inferred defaults + user edits)
  4. Execute pipeline (calls translate_cmd, catches all exceptions)

Remembers last-used parameters in cs2tl-data/wizard-state.json.
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from cs2tl.cli.doctor import _run_checks
from cs2tl.cli.translate import KNOWN_MAPS, VALID_STAGES, translate_cmd
from cs2tl.config import default_data_dir
from cs2tl.errors import CS2tlError

console = Console()

# ---------------------------------------------------------------------------
# Wizard state persistence
# ---------------------------------------------------------------------------

STATE_FILENAME = "wizard-state.json"


def _state_path() -> Path:
    """Return the path to wizard-state.json inside the data directory."""
    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / STATE_FILENAME


@dataclass
class WizardState:
    """Persisted wizard preferences — survives between runs."""

    map_name: str = ""
    output_dir: str = "./subtitles"
    target_language: str = "zh"
    use_dictionary: bool = True

    def save(self) -> None:
        """Write state to disk atomically."""
        path = _state_path()
        try:
            path.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # non-critical — just skip saving

    @classmethod
    def load(cls) -> "WizardState":
        """Load saved state, falling back to defaults on any error."""
        path = _state_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                map_name=data.get("map_name", ""),
                output_dir=data.get("output_dir", "./subtitles"),
                target_language=data.get("target_language", "zh"),
                use_dictionary=data.get("use_dictionary", True),
            )
        except (json.JSONDecodeError, KeyError, OSError):
            return cls()


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


class Wizard:
    """Interactive 4-step translation wizard powered by Rich."""

    def __init__(self) -> None:
        self.console = console
        self.state = WizardState.load()

    # -- public API ----------------------------------------------------------

    def run(self) -> int:
        """Run the full wizard flow. Returns exit code (0 = success)."""
        self._print_banner()

        if not self._step_welcome():
            return 1

        demo_path = self._step_select_demo()
        if demo_path is None:
            self.console.print("[yellow]已取消。[/yellow]")
            return 0

        if not self._step_confirm_params(demo_path):
            self.console.print("[yellow]已取消。[/yellow]")
            return 0

        return self._step_execute(demo_path)

    # -- step 1: welcome + environment ---------------------------------------

    def _print_banner(self) -> None:
        """Display welcome banner."""
        title = Text("CS2 POV Translator", style="bold cyan")
        subtitle = Text("CS2 Faceit Demo 语音 → 中文 SRT 字幕", style="dim")
        self.console.print()
        self.console.print(Panel(subtitle, title=title, border_style="cyan"))
        self.console.print()

    def _step_welcome(self) -> bool:
        """Run environment checks. Returns True if user can proceed."""
        self.console.print("[bold]⏳ 正在检查环境...[/bold]\n")

        checks = _run_checks(verbose=False)

        # Render results as a Rich table
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("icon", width=2)
        table.add_column("component", width=24)
        table.add_column("detail")

        failures: list[tuple[str, str]] = []
        warnings: list[tuple[str, str]] = []

        for status, comp, detail, fix in checks:
            if status == "PASS":
                table.add_row("✅", comp, Text(detail, style="dim"))
            elif status == "FAIL":
                table.add_row("❌", Text(comp, style="red"), Text(detail, style="red"))
                failures.append((comp, fix))
            else:  # WARN
                table.add_row("⚠️", Text(comp, style="yellow"), Text(detail, style="yellow"))
                if fix:
                    warnings.append((comp, fix))

        self.console.print(table)

        # Show warnings (non-blocking)
        if warnings:
            self.console.print()
            for comp, fix in warnings:
                self.console.print(f"  [yellow]⚠[/yellow] [bold]{comp}[/bold]: {fix}")

        self.console.print()

        if not failures:
            self.console.print("[green]✅ 环境就绪！[/green]\n")
            return True

        # Show failure details with fix instructions
        self.console.print("[red]❌ 以下组件需要修复：[/red]\n")
        for comp, fix in failures:
            self.console.print(f"  [bold]{comp}[/bold]")
            if fix:
                self.console.print(f"    {fix}")
            self.console.print()

        self.console.print("修复后重新运行 [bold]cs2tl wizard[/bold] 或 [bold]cs2tl doctor[/bold]。")
        self.console.print()
        return False

    # -- step 2: select demo file --------------------------------------------

    def _step_select_demo(self) -> Path | None:
        """Scan for .dem files and let the user pick one. Returns None if cancelled."""
        self.console.print("[bold]📁 选择 Demo 文件[/bold]\n")

        # Scan for .dem files
        demos_dir = Path("demos")
        candidates: list[Path] = []
        if demos_dir.is_dir():
            candidates.extend(sorted(demos_dir.glob("*.dem")))
        candidates.extend(sorted(Path().glob("*.dem")))

        # Deduplicate (in case cwd is demos/)
        seen: set[str] = set()
        unique: list[Path] = []
        for p in candidates:
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                unique.append(p)

        if not unique:
            self.console.print(
                "[yellow]未找到 .dem 文件。[/yellow]\n"
                "请将 demo 文件放入 [bold]./demos/[/bold] 目录，\n"
                "或直接输入文件路径："
            )
            return self._manual_demo_input()

        if len(unique) == 1:
            demo = unique[0]
            self.console.print(f"找到 1 个 demo 文件：[bold cyan]{demo}[/bold cyan]")
            if Confirm.ask("使用此文件？", default=True):
                return demo
            return self._manual_demo_input()

        # Multiple files — let user select
        self.console.print(f"找到 {len(unique)} 个 demo 文件：")
        for i, p in enumerate(unique, 1):
            self.console.print(f"  [bold]{i}[/bold]. {p}")
        self.console.print(f"  [bold]M[/bold]. 手动输入路径")
        self.console.print(f"  [bold]Q[/bold]. 退出")
        self.console.print()

        while True:
            choice = Prompt.ask("请选择", default="1").strip()
            if choice.upper() == "Q":
                return None
            if choice.upper() == "M":
                return self._manual_demo_input()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(unique):
                    return unique[idx]
            except ValueError:
                pass
            self.console.print("[red]无效选择，请重试。[/red]")

    def _manual_demo_input(self) -> Path | None:
        """Prompt for a manual demo file path. Returns None if cancelled."""
        while True:
            raw = Prompt.ask("Demo 文件路径", default="").strip()
            if not raw:
                return None
            path = Path(raw)
            if path.is_file() and path.suffix.lower() == ".dem":
                return path
            if path.is_file():
                self.console.print("[yellow]文件存在但不是 .dem 格式，请确认。[/yellow]")
                if Confirm.ask("仍然使用此文件？", default=False):
                    return path
            else:
                self.console.print(f"[red]文件不存在：{path}[/red]")

    # -- step 3: confirm parameters ------------------------------------------

    def _step_confirm_params(self, demo_path: Path) -> bool:
        """Show inferred parameters and let the user confirm or edit.
        Returns True if the user wants to proceed, False to quit.
        """
        self.console.print("[bold]⚙️  确认翻译参数[/bold]\n")

        # Infer map name from demo filename
        inferred_map = self._infer_map(demo_path)
        map_name = self.state.map_name or inferred_map or ""

        while True:
            # Show parameter summary
            table = Table(show_header=True, box=None, padding=(0, 1))
            table.add_column("#", width=2, style="dim")
            table.add_column("参数", width=12)
            table.add_column("当前值", style="bold")

            table.add_row("1", "地图", map_name or "(未指定)")
            table.add_row("2", "输出目录", self.state.output_dir)
            table.add_row("3", "词典", "启用" if self.state.use_dictionary else "禁用")
            table.add_row("", "目标语言", self.state.target_language)

            self.console.print(table)
            self.console.print()
            self.console.print(
                "[dim][Enter] 开始翻译  [1] 改地图  [2] 改输出目录  [3] 切换词典  [Q] 退出[/dim]"
            )
            self.console.print()

            choice = Prompt.ask("", default="").strip()

            if choice == "":
                # Proceed — save state and continue
                self.state.map_name = map_name
                self.state.save()
                return True

            if choice.upper() == "Q":
                return False

            if choice == "1":
                map_name = self._prompt_map_name()
            elif choice == "2":
                new_dir = Prompt.ask("输出目录", default=self.state.output_dir)
                self.state.output_dir = new_dir
            elif choice == "3":
                self.state.use_dictionary = not self.state.use_dictionary
                status = "启用" if self.state.use_dictionary else "禁用"
                self.console.print(f"词典已{status}。")
            else:
                self.console.print("[red]无效选择。[/red]")

    def _infer_map(self, demo_path: Path) -> str | None:
        """Try to infer map name from demo filename.

        Common patterns: de_dust2.dem, faceit_de_mirage_12345.dem
        """
        stem = demo_path.stem.lower()
        for known in sorted(KNOWN_MAPS, key=len, reverse=True):
            if known in stem:
                return known
        return None

    def _prompt_map_name(self) -> str:
        """Prompt for a CS2 map name with validation against KNOWN_MAPS."""
        self.console.print()
        self.console.print("[dim]已知地图:[/dim] " + ", ".join(sorted(KNOWN_MAPS)))
        self.console.print()

        while True:
            name = Prompt.ask("地图名", default=self.state.map_name or "").strip().lower()
            if not name:
                return ""
            if name in KNOWN_MAPS:
                return name
            self.console.print(
                f"[red]'{name}' 不是已知 CS2 地图。请输入上表中的地图名。[/red]"
            )

    # -- step 4: execute pipeline --------------------------------------------

    def _step_execute(self, demo_path: Path) -> int:
        """Run the translation pipeline. Returns exit code."""
        self.console.print()
        self.console.print("[bold]🚀 开始翻译...[/bold]")
        self.console.print()

        output_dir = Path(self.state.output_dir)

        try:
            translate_cmd(
                demo=demo_path,
                map_name=self.state.map_name or None,
                to=self.state.target_language,
                output=output_dir,
                no_dictionary=not self.state.use_dictionary,
                machine_readable=False,
            )
        except typer.Exit as e:
            if e.exit_code == 0:
                # Zero voice data — valid result, not an error
                self.console.print()
                self.console.print("[yellow]该 demo 文件没有语音数据。[/yellow]")
                return 0
            self.console.print()
            self.console.print(f"[red]翻译失败 (exit code {e.exit_code})[/red]")
            self.console.print("请检查参数是否正确，或运行 [bold]cs2tl doctor[/bold] 检查环境。")
            return 1
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if code == 0:
                self.console.print()
                self.console.print("[yellow]翻译已取消。[/yellow]")
                return 0
            self.console.print()
            self.console.print(f"[red]翻译中断 (exit code {code})[/red]")
            self.console.print("请检查参数是否正确，或运行 [bold]cs2tl doctor[/bold] 检查环境。")
            return 1
        except CS2tlError as e:
            self.console.print()
            self.console.print(f"[red]{e.message}[/red]")
            if e.fix:
                self.console.print(f"[dim]{e.fix}[/dim]")
            return 1
        except Exception as e:
            self.console.print()
            self.console.print(f"[red]未知错误: {e}[/red]")
            self.console.print("[dim]请运行 [bold]cs2tl doctor[/bold] 检查环境。[/dim]")
            if "--verbose" in sys.argv:
                self.console.print()
                self.console.print(Panel(traceback.format_exc(), title="详细错误", border_style="red"))
            return 1

        # Success — show result paths
        self.console.print()
        self.console.print(Panel(
            f"SRT 字幕文件：[bold cyan]{output_dir.resolve()}/[/bold cyan]\n"
            f"词典文件：   [bold cyan]{default_data_dir() / 'dictionary'}/[/bold cyan]",
            title="✅ 翻译完成",
            border_style="green",
        ))
        self.console.print()
        self.console.print("[dim]如需修改翻译术语，用记事本打开词典目录中的 .json 文件直接编辑。[/dim]")
        self.console.print("[dim]下次翻译将自动填充本次的参数。[/dim]")

        return 0


# ---------------------------------------------------------------------------
# Typer command entry point
# ---------------------------------------------------------------------------


def wizard_cmd() -> None:
    """交互式翻译向导 — 适合首次使用的用户。

    双击 start-cs2tl.bat 或在终端运行：cs2tl wizard

    提供 4 步引导：
      1. 环境检查（Whisper 模型、API key 等）
      2. 选择 demo 文件（自动扫描 + 多选）
      3. 确认参数（地图名、输出目录、词典开关）
      4. 执行翻译（7 阶段管道 + 进度条）

    参数记忆：地图名和输出目录保存到 wizard-state.json，下次自动填充。
    """
    wizard = Wizard()
    code = wizard.run()
    if code != 0:
        raise typer.Exit(code)
