from cs2pov.cli import launcher


def _run_with_inputs(monkeypatch, values):
    vals = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(vals))
    return launcher.main(["--once"])


def test_export_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["5", "0"]) == 0
    out = capsys.readouterr().out
    assert "重新导出" in out
    assert "已返回主菜单" in out


def test_retranslate_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["6", "q"]) == 0
    out = capsys.readouterr().out
    assert "重新翻译" in out
    assert "已返回主菜单" in out


def test_resume_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["7", "back"]) == 0
    out = capsys.readouterr().out
    assert "恢复执行" in out
    assert "已返回主菜单" in out


def test_feedback_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["8", "返回"]) == 0
    out = capsys.readouterr().out
    assert "已返回主菜单" in out


def test_setup_check_menu_is_available(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["2"]) == 0
    out = capsys.readouterr().out
    assert "启动前检查" in out


def test_explain_output_submenu_can_return_to_main(monkeypatch, capsys):
    assert _run_with_inputs(monkeypatch, ["4", "0"]) == 0
    out = capsys.readouterr().out
    assert "已返回主菜单" in out
