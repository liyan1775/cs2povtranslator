import pytest

from cs2pov.cli import launcher


def _run_with_inputs(monkeypatch, values):
    vals = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(vals))
    return launcher.main(["--once"])


def test_main_menu_is_core_first(capsys):
    launcher.print_menu()
    out = capsys.readouterr().out
    assert "核心菜单" in out
    assert "1. 新建 POV 通讯流工程" in out
    assert "2. 渲染 Comms Overlay" in out
    assert "6. 设置与高级工具" in out
    assert "13." not in out
    assert "重新导出 SRT 字幕" not in out


def test_banner_mentions_current_version_and_primary_workflow(capsys):
    launcher.print_banner()
    out = capsys.readouterr().out
    assert "v0.9.8" in out
    assert "POV 通讯流 Overlay" in out
    assert "1 新建工程" in out


def test_comms_overlay_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["2", "0"]) == 0
    out = capsys.readouterr().out
    assert "Comms Overlay" in out
    assert "已返回主菜单" in out


def test_project_status_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["3", "0"]) == 0
    out = capsys.readouterr().out
    assert "查看工程" in out
    assert "已返回主菜单" in out


def test_feedback_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["4", "返回"]) == 0
    out = capsys.readouterr().out
    assert "已返回主菜单" in out


def test_setup_check_menu_is_available(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["5"]) == 0
    out = capsys.readouterr().out
    assert "启动前检查" in out or "setup" in out.lower()


def test_models_menu_explains_workspace_bound_cache(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")

    with pytest.raises(launcher.ReturnToMainMenu):
        launcher.run_models_menu()

    out = capsys.readouterr().out
    assert "模型缓存跟随当前工作区" in out
    assert "项目级缓存配置" not in out


def test_tools_menu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["6", "0"]) == 0
    out = capsys.readouterr().out
    assert "设置与高级工具" in out
    assert "已返回主菜单" in out


def test_export_submenu_is_hidden_in_tools(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["6", "4", "0"]) == 0
    out = capsys.readouterr().out
    assert "重新导出" in out
    assert "已返回主菜单" in out


def test_retranslate_submenu_is_hidden_in_tools(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["6", "5", "q"]) == 0
    out = capsys.readouterr().out
    assert "重新翻译" in out
    assert "已返回主菜单" in out


def test_resume_submenu_is_hidden_in_tools(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["6", "6", "back"]) == 0
    out = capsys.readouterr().out
    assert "恢复执行" in out
    assert "已返回主菜单" in out
