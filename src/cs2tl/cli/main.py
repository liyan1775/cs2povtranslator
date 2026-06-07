"""cs2tl — CS2 POV Translator CLI entry point."""

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
