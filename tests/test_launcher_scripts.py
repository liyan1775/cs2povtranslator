from pathlib import Path


def test_launcher_uses_local_virtualenv_python():
    text = Path("Start_CS2_POV_Translator.bat").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "py -3 -X utf8 -m cs2pov.cli.wizard" not in text
    assert "Install_CS2_POV_Translator.bat" in text
    assert "PYTHONPATH=%CD%\\src;%PYTHONPATH%" in text
    assert "cs2pov.cli.launcher" in text
