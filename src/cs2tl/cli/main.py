"""cs2tl — CS2 POV Translator CLI entry point."""

import os
import sys

# Set HF_HOME before anything imports faster_whisper, so model weights
# land in ./cs2tl-data/huggingface/ instead of the global HF cache.
def _set_hf_home() -> None:
    if "HF_HOME" in os.environ:
        return
    # Walk up from this file to find project root
    from pathlib import Path
    start = Path(__file__).resolve().parent
    for ancestor in [start, *start.parents]:
        if (ancestor / ".git").exists() or (ancestor / "pyproject.toml").exists():
            project_root = ancestor
            break
    else:
        project_root = Path.cwd()
    # Priority: CS2TL_DATA_DIR env → ./cs2tl-data/ (project root)
    env_dir = os.environ.get("CS2TL_DATA_DIR", "")
    data_dir = Path(env_dir) if env_dir else project_root / "cs2tl-data"
    os.environ["HF_HOME"] = str(data_dir / "huggingface")

_set_hf_home()

import typer

from cs2tl.cli.config_cmd import config_app
from cs2tl.cli.dictionary_cmd import dict_app
from cs2tl.cli.doctor import doctor_cmd
from cs2tl.cli.translate import translate_cmd
from cs2tl.web.app import main as web_main

app = typer.Typer(
    name="cs2tl",
    help="CS2 POV Translator — CS2 Faceit demo voice comms → Chinese SRT subtitles",
    no_args_is_help=True,
)

# cs2tl translate
app.command(name="translate")(translate_cmd)

# cs2tl dictionary | dict (P1-10: shortcut alias)
app.add_typer(dict_app, name="dictionary", help="Manage CS2 callout dictionaries")
app.add_typer(dict_app, name="dict", help="Alias for 'dictionary'")

# cs2tl config
app.add_typer(config_app, name="config", help="Manage cs2tl configuration")

# cs2tl doctor
app.command(name="doctor")(doctor_cmd)

# cs2tl web
@app.command(name="web")
def web_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址"),
    port: int = typer.Option(8765, "--port", help="监听端口"),
    no_browser: bool = typer.Option(False, "--no-browser", help="不自动打开浏览器"),
):
    """启动 Web UI"""
    web_main(host=host, port=port, open_browser=not no_browser)
