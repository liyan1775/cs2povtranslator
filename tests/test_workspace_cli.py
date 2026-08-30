import json
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(args, env):
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    return subprocess.run([sys.executable, "-m", "cs2pov.cli.commands", *args], capture_output=True, text=True, encoding="utf-8", env=env)


def test_workspace_init_show_doctor_forget_json_across_processes(tmp_path):
    env = dict(__import__("os").environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    state = tmp_path / "中文 状态" / "state.json"
    env["CS2POV_STATE_FILE"] = str(state)
    root = tmp_path / "工作区 A"
    init = run_cli(["workspace", "init", str(root), "--json"], env)
    assert init.returncode == 0
    init_doc = json.loads(init.stdout)
    assert init_doc["ok"] is True and init_doc["command"] == "workspace.init"
    show = run_cli(["workspace", "show", "--json"], env)
    assert show.returncode == 0
    assert json.loads(show.stdout)["selected_workspace"] == str(root.resolve())
    doctor = run_cli(["workspace", "doctor", "--json"], env)
    assert doctor.returncode == 0 and json.loads(doctor.stdout)["diagnostic"]["ok"] is True
    forget = run_cli(["workspace", "forget", "--json"], env)
    assert forget.returncode == 0 and json.loads(forget.stdout)["forgotten"] is True
    missing = run_cli(["workspace", "show", "--json"], env)
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["error"]["code"] == "selection_missing"


def test_workspace_invalid_use_is_json_error_without_traceback(tmp_path):
    env = dict(__import__("os").environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["CS2POV_STATE_FILE"] = str(tmp_path / "state.json")
    result = run_cli(["workspace", "use", str(tmp_path / "missing"), "--json"], env)
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] in {"workspace_missing", "workspace_config_missing", "workspace_config_invalid"}
    assert "Traceback" not in result.stderr


def test_launcher_once_exposes_workspace_management_menu(tmp_path):
    env = dict(__import__("os").environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["CS2POV_STATE_FILE"] = str(tmp_path / "state.json")
    result = subprocess.run([sys.executable, "-m", "cs2pov.cli.launcher", "--once"], input="6\n10\n0\n", capture_output=True, text=True, encoding="utf-8", env=env)
    assert result.returncode == 0
    assert "工作区管理" in result.stdout
    assert "当前步骤只设置新版本数据目录" in result.stdout


def test_launcher_homepage_reports_workspace_status_without_creating_state(tmp_path):
    env = dict(__import__("os").environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["CS2POV_STATE_FILE"] = str(tmp_path / "state" / "state.json")
    result = subprocess.run([sys.executable, "-m", "cs2pov.cli.launcher", "--once"], input="0\n", capture_output=True, text=True, encoding="utf-8", env=env)
    assert result.returncode == 0
    assert "工作区状态：未选择" in result.stdout
    assert not (tmp_path / "state").exists()
