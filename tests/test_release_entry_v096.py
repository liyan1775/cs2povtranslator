from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_startup_entry_files_exist_and_warn_about_clean_room():
    assert (ROOT / "START_HERE_DOUBLE_CLICK.bat").exists()
    assert (ROOT / "README_FIRST_READ_ME_FIRST.txt").exists()
    readme = (ROOT / "README_FIRST_READ_ME_FIRST.txt").read_text(encoding="utf-8")
    assert "v0.9.8" in readme
    assert "全新的目录" in readme
    assert "v0.8.x" in readme


def test_launcher_script_prints_runtime_path_and_runs_sanity_check():
    text = (ROOT / "Start_CS2_POV_Translator.bat").read_text(encoding="utf-8")
    assert "Current directory: %CD%" in text
    assert "scripts\\launch_sanity_check.py" in text
    assert "cs2pov_arch_project\\Start_CS2_POV_Translator.bat" in text
    assert "clean-room" in text


def test_install_script_runs_sanity_check_after_install():
    text = (ROOT / "Install_CS2_POV_Translator.bat").read_text(encoding="utf-8")
    assert "Current install directory: %CD%" in text
    assert "clean-room" in text
    assert "scripts\\launch_sanity_check.py" in text
    assert "[4/5] Running launch sanity check" in text


def test_bat_files_are_ascii_only_to_avoid_windows_gbk_parse_errors():
    for name in ["Start_CS2_POV_Translator.bat", "Install_CS2_POV_Translator.bat", "START_HERE_DOUBLE_CLICK.bat"]:
        data = (ROOT / name).read_bytes()
        assert data.decode("ascii"), f"{name} must be ASCII-only so CMD can parse it before chcp"
        assert not data.startswith(b"\xef\xbb\xbf"), f"{name} must not contain UTF-8 BOM"


def test_launch_sanity_check_uses_current_src():
    # Windows may use GBK as the parent process locale, while the child process
    # can emit UTF-8 Chinese diagnostics under PYTHONUTF8/launcher settings.
    # Decode explicitly so release-entry tests verify the real startup text instead
    # of failing on locale-dependent subprocess decoding.
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "scripts/launch_sanity_check.py"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "0.9.8" in result.stdout
    assert "启动自检" in result.stdout
    assert "通过" in result.stdout


def test_installer_auto_discovers_python_beyond_path():
    text = (ROOT / "Install_CS2_POV_Translator.bat").read_text(encoding="ascii")
    assert ":find_python" in text
    assert "py -3" in text
    assert "python3" in text
    assert "anaconda3\\python.exe" in text.lower()
    assert "miniconda3\\python.exe" in text.lower()
    assert "Python312\\python.exe" in text or "Python313\\python.exe" in text
    assert "enable Add to PATH" not in text


def test_start_script_runs_installer_when_venv_missing():
    text = (ROOT / "Start_CS2_POV_Translator.bat").read_text(encoding="ascii")
    assert "Local virtual environment not found" in text
    assert "call Install_CS2_POV_Translator.bat" in text
    assert "v0.9.8" in text
