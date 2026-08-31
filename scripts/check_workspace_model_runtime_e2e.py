"""Cross-process acceptance check for workspace-bound model caches."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def snapshot(root: Path) -> tuple[tuple[str, ...], dict[str, str]]:
    if not root.exists():
        return (), {}
    directories = tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_dir())
    )
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    return directories, files


def main() -> int:
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="cs2pov-model-e2e-") as temp:
        base = Path(temp) / "中文 E2E"
        cwd = base / "cwd"
        cwd.mkdir(parents=True)
        home, local, xdg = (base / name for name in ("HOME", "LOCALAPPDATA", "XDG"))
        state = base / "state" / "state.json"
        fake = base / "fake-modules" / "faster_whisper"
        record = base / "fake-record.json"
        for path in (home, local, xdg, state.parent, fake):
            path.mkdir(parents=True, exist_ok=True)
        (fake / "__init__.py").write_text(
            "import json\nimport os\n\nclass WhisperModel:\n"
            "    def __init__(self, model, **kwargs):\n"
            "        with open(os.environ['FAKE_RECORD'], 'w', encoding='utf-8') as handle:\n"
            "            json.dump({'model': model, 'kwargs': kwargs}, handle)\n",
            encoding="utf-8",
        )
        workspace = base / "工作区 A"
        configured = base / "legacy-configured-cache"
        env_cache = base / "legacy-env-cache"
        configured.mkdir()
        env_cache.mkdir()
        for root in (configured, env_cache):
            model = root / "models--legacy--faster-whisper-base"
            model.mkdir()
            (model / "marker.bin").write_bytes(b"legacy")
        before_legacy = {"configured": snapshot(configured), "env": snapshot(env_cache)}
        env = dict(os.environ)
        env.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONPATH": os.pathsep.join(
                    (str(base / "fake-modules"), str(source / "src"))
                ),
                "CS2POV_STATE_FILE": str(state),
                "HOME": str(home),
                "USERPROFILE": str(home),
                "LOCALAPPDATA": str(local),
                "XDG_STATE_HOME": str(xdg),
                "HF_HOME": str(env_cache),
                "HF_HUB_CACHE": str(env_cache),
                "FAKE_RECORD": str(record),
            }
        )

        def run(*args: str) -> tuple[int, dict]:
            result = subprocess.run(
                [sys.executable, "-m", "cs2pov.cli.commands", *args],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            assert "Traceback" not in result.stderr, result.stderr
            try:
                document = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"非 JSON 输出 {args}: {result.stdout!r}") from exc
            return result.returncode, document

        code, document = run("models", "test", "--model", "base", "--json")
        assert code == 1 and document["error"]["code"] == "workspace_selection_required" and not record.exists()
        code, document = run("workspace", "init", str(workspace), "--json")
        assert code == 0 and document["ok"]
        (home / ".cs2pov").mkdir()
        config_path = home / ".cs2pov" / "config.json"
        config_path.write_text(
            json.dumps({"whisper_cache_dir": str(configured)}),
            encoding="utf-8",
        )
        expected_home = snapshot(home)
        code, info = run("models", "info", "--json")
        assert code == 0
        assert info["workspace_cache"] == {
            "whisper": str((workspace / "cache/whisper").resolve()),
            "huggingface_hub": str((workspace / "cache/huggingface/hub").resolve()),
        }
        assert info["deprecated_config"]["present"] is True
        assert info["deprecated_config"]["deprecated"] is True
        legacy = {(row["source"], row["path"]): row for row in info["legacy_candidates"]}
        assert ("configured", str(configured.resolve())) in legacy
        assert ("HF_HUB_CACHE", str(env_cache.resolve())) in legacy
        assert all(row["managed"] is False for row in legacy.values())
        code, result = run("models", "test", "--model", "base", "--json")
        assert code == 0 and result["cache_dir"] == str((workspace / "cache/whisper").resolve())
        logged = json.loads(record.read_text(encoding="utf-8"))
        assert logged["model"] == "base"
        assert logged["kwargs"]["download_root"] == str((workspace / "cache/whisper").resolve())
        assert logged["kwargs"]["device"] == "cpu"
        assert logged["kwargs"]["compute_type"] == "int8"
        logged_values = " ".join(str(value) for value in logged["kwargs"].values())
        for forbidden in (configured, env_cache, cwd, home, local, xdg):
            assert str(forbidden.resolve()) not in logged_values
        code, local_result = run(
            "models", "test", "--model", "base", "--local-only", "--json"
        )
        assert code == 0 and local_result["ok"] is True
        local_logged = json.loads(record.read_text(encoding="utf-8"))
        assert local_logged["kwargs"]["local_files_only"] is True
        before_record = record.read_bytes()
        assert snapshot(configured) == before_legacy["configured"]
        assert snapshot(env_cache) == before_legacy["env"]
        override = base / "override"
        code, rejected = run("models", "test", "--model", "base", "--cache-dir", str(override), "--json")
        assert code == 1 and rejected["error"]["code"] == "legacy_model_cache_override_rejected"
        assert not override.exists() and record.read_bytes() == before_record
        assert snapshot(configured) == before_legacy["configured"] and snapshot(env_cache) == before_legacy["env"]
        valid_config = config_path.read_bytes()
        config_path.write_bytes(b"\xff")
        code, invalid_encoding_info = run("models", "info", "--json")
        assert code == 0
        assert invalid_encoding_info["deprecated_config"]["present"] is False
        config_path.write_text("null", encoding="utf-8")
        code, invalid_shape_info = run("models", "info", "--json")
        assert code == 0
        assert invalid_shape_info["deprecated_config"]["present"] is False
        config_path.unlink()
        config_path.mkdir()
        code, unreadable_info = run("models", "info", "--json")
        assert code == 0
        assert unreadable_info["deprecated_config"]["present"] is False
        config_path.rmdir()
        config_path.write_bytes(valid_config)
        assert snapshot(home) == expected_home
        record.unlink()
        whisper = workspace / "cache/whisper"
        for child in whisper.iterdir():
            if child.is_dir():
                child.rmdir()
        whisper.rmdir()
        code, failed = run("models", "test", "--model", "base", "--json")
        assert code == 1
        assert failed["error"]["code"] == "workspace_unhealthy"
        assert failed.get("diagnostic")
        assert failed["diagnostic"]["ok"] is False
        assert not record.exists() and not whisper.exists()
        assert snapshot(configured) == before_legacy["configured"]
        assert snapshot(env_cache) == before_legacy["env"]
        assert not any(cwd.iterdir()) and not any(local.iterdir()) and not any(xdg.iterdir())
        assert snapshot(home) == expected_home
    print("workspace model runtime E2E passed: isolated subprocess cache binding and legacy rejection")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"E2E failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
