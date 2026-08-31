from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from cs2pov.application.demo_assets import DemoAssetUseCaseError
from cs2pov.application.workspace_runtime import WorkspaceRuntimeError
from cs2pov.cli import commands, demo_commands
from cs2pov.domain.assets import (
    DemoAsset,
    DemoAssetInspection,
    DemoAssetSummary,
    DemoImportResult,
)
from cs2pov.application.workspace import WorkspaceSelection
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


def sample_asset(*, source_format="dem"):
    asset_id = hashlib.sha256(b"anonymous-demo").hexdigest()
    return DemoAsset(
        schema_version=1,
        asset_id=asset_id,
        logical_sha256=asset_id,
        logical_size_bytes=14,
        source_sha256=asset_id,
        source_size_bytes=14,
        source_format=source_format,
        source_relative_path=f"library/demos/{asset_id}/source.{source_format}",
        display_name="match.dem.zst" if source_format == "dem.zst" else "match.dem",
        imported_at="2026-08-31T00:00:00.000000Z",
    )


class FakeApplication:
    def __init__(self):
        self.calls = []
        self.import_result = DemoImportResult(sample_asset(), "imported", 128)
        asset = sample_asset()
        self.list_result = (
            DemoAssetSummary(
                asset.asset_id,
                asset.display_name,
                asset.source_format,
                asset.source_size_bytes,
                asset.logical_size_bytes,
                asset.imported_at,
                True,
                None,
            ),
        )
        self.inspect_result = DemoAssetInspection(asset, True, "not_applicable", ())
        self.error = None

    def _record(self, name, value=None):
        self.calls.append((name, value))
        if self.error is not None:
            raise self.error

    def import_demo(self, source):
        self._record("import", source)
        return self.import_result

    def list_assets(self):
        self._record("list")
        return self.list_result

    def inspect_asset(self, asset_id):
        self._record("inspect", asset_id)
        return self.inspect_result


@pytest.fixture
def fake_app(monkeypatch):
    app = FakeApplication()
    monkeypatch.setattr(demo_commands, "_application", lambda: app)
    return app


def test_demos_parser_has_only_import_list_and_inspect():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    demo_commands.add_demos_parser(subparsers)

    imported = parser.parse_args(["demos", "import", "match.dem", "--json"])
    listed = parser.parse_args(["demos", "list", "--json"])
    inspected = parser.parse_args(["demos", "inspect", "a" * 64, "--json"])

    assert (imported.cmd, imported.demos_cmd, imported.path, imported.json) == (
        "demos", "import", "match.dem", True
    )
    assert (listed.demos_cmd, listed.json) == ("list", True)
    assert (inspected.demos_cmd, inspected.asset_id, inspected.json) == ("inspect", "a" * 64, True)
    help_text = parser.format_help()
    assert "delete" not in help_text
    assert "repair" not in help_text
    assert "migrate" not in help_text


@pytest.mark.parametrize(
    "argv,command,key",
    [
        (["demos", "import", "match.dem", "--json"], "demos.import", "result"),
        (["demos", "list", "--json"], "demos.list", "assets"),
        (["demos", "inspect", "a" * 64, "--json"], "demos.inspect", "inspection"),
    ],
)
def test_json_success_is_one_parseable_document(fake_app, capsys, argv, command, key):
    code = commands.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["command"] == command
    assert key in payload
    assert captured.err == ""


def test_json_list_has_stable_count_and_assets(fake_app, capsys):
    code = commands.main(["demos", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload == {
        "ok": True,
        "command": "demos.list",
        "count": 1,
        "assets": [fake_app.list_result[0].to_dict()],
    }


def test_json_known_error_uses_stable_envelope_without_path(fake_app, capsys):
    fake_app.error = DemoAssetUseCaseError(
        "demo_source_not_found",
        "找不到 Demo 源文件。",
        "请确认文件仍存在后重试。",
    )

    code = commands.main(["demos", "import", "C:/private/user/match.dem", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 1
    assert payload == {
        "ok": False,
        "command": "demos.import",
        "error": {
            "code": "demo_source_not_found",
            "message_zh": "找不到 Demo 源文件。",
            "suggestion_zh": "请确认文件仍存在后重试。",
        },
    }
    assert "C:/private" not in captured.out
    assert captured.err == ""


def test_json_workspace_error_is_owned_by_demos_command(fake_app, capsys):
    fake_app.error = WorkspaceRuntimeError(
        "workspace_selection_required",
        "尚未选择工作区。",
        "请先初始化或选择一个工作区。",
    )

    code = commands.main(["demos", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["command"] == "demos.list"
    assert payload["error"]["code"] == "workspace_selection_required"


def test_unhealthy_inspection_returns_detail_and_exit_one_not_generic_error(fake_app, capsys):
    asset = sample_asset()
    fake_app.inspect_result = DemoAssetInspection(
        asset,
        False,
        "not_applicable",
        ("demo_asset_integrity_failed",),
    )

    code = commands.main(["demos", "inspect", asset.asset_id, "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["command"] == "demos.inspect"
    assert payload["inspection"]["source_ok"] is False
    assert "error" not in payload


def test_text_import_reuse_empty_list_and_cache_missing_are_non_programmer_friendly(fake_app, capsys):
    assert commands.main(["demos", "import", "match.dem"]) == 0
    imported_text = capsys.readouterr().out
    assert "已导入到当前工作区素材库" in imported_text
    assert "长期新增空间" in imported_text

    fake_app.import_result = DemoImportResult(sample_asset(), "reused", 0)
    assert commands.main(["demos", "import", "renamed.dem"]) == 0
    assert "工作区已有相同 Demo，本次直接复用" in capsys.readouterr().out

    fake_app.list_result = ()
    assert commands.main(["demos", "list"]) == 0
    assert "cs2pov demos import" in capsys.readouterr().out

    compressed = sample_asset(source_format="dem.zst")
    fake_app.inspect_result = DemoAssetInspection(compressed, True, "missing", ())
    assert commands.main(["demos", "inspect", compressed.asset_id]) == 0
    missing_text = capsys.readouterr().out
    assert "持久源完整" in missing_text
    assert "需要时可自动重建" in missing_text
    assert "缓存损坏" not in missing_text


def test_text_persistent_source_failure_has_advice_and_no_traceback(fake_app, capsys):
    asset = sample_asset()
    fake_app.inspect_result = DemoAssetInspection(
        asset,
        False,
        "not_applicable",
        ("demo_asset_integrity_failed",),
    )

    code = commands.main(["demos", "inspect", asset.asset_id])
    output = capsys.readouterr().out

    assert code == 1
    assert "持久源完整性检查失败" in output
    assert "建议" in output
    assert "Traceback" not in output


def test_unknown_programming_error_still_propagates(fake_app):
    fake_app.error = RuntimeError("programming bug")

    with pytest.raises(RuntimeError, match="programming bug"):
        commands.main(["demos", "list", "--json"])


def _snapshot(root: Path):
    if not root.exists():
        return ()
    values = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        values.append((relative, path.read_bytes() if path.is_file() else None))
    return tuple(values)


def test_real_missing_workspace_returns_owned_json_without_writes(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state" / "state.json"
    monkeypatch.setenv("CS2POV_STATE_FILE", str(state))

    code = commands.main(["demos", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["command"] == "demos.list"
    assert payload["error"]["code"] == "workspace_selection_required"
    assert not state.parent.exists()


def test_real_damaged_workspace_is_read_only_and_returns_stable_json(tmp_path, monkeypatch, capsys):
    root = tmp_path / "workspace"
    paths = WorkspacePaths(root)
    WorkspaceService(paths, minimum_free_bytes=0).initialize()
    state = tmp_path / "state" / "state.json"
    JsonWorkspaceSelectionStore(state).save(WorkspaceSelection(1, str(root)))
    paths.config_file.write_text("{broken-json", encoding="utf-8")
    before = _snapshot(root)
    monkeypatch.setenv("CS2POV_STATE_FILE", str(state))

    code = commands.main(["demos", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["command"] == "demos.list"
    assert payload["error"]["code"] == "workspace_unhealthy"
    assert _snapshot(root) == before
    assert not list(paths.temp_dir.glob("demo_imports/*"))
