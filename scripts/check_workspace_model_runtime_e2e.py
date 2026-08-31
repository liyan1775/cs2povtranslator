"""Cross-process acceptance check for workspace-bound model caches."""
from __future__ import annotations
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

def snapshot(root: Path) -> dict[str, str]:
    if not root.exists(): return {}
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}

def main() -> int:
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="cs2pov-model-e2e-") as temp:
        base = Path(temp) / "中文 E2E"; cwd = base / "cwd"; cwd.mkdir(parents=True)
        home, local, xdg = (base / name for name in ("HOME", "LOCALAPPDATA", "XDG"))
        state = base / "state" / "state.json"; fake = base / "fake-modules" / "faster_whisper"
        record = base / "fake-record.json"
        for path in (home, local, xdg, state.parent, fake): path.mkdir(parents=True, exist_ok=True)
        (fake / "__init__.py").write_text(
            "import json, os\nclass WhisperModel:\n"
            "    def __init__(self, model, **kwargs):\n"
            "        with open(os.environ['FAKE_RECORD'], 'w', encoding='utf-8') as f: json.dump({'model': model, 'kwargs': kwargs}, f)\n",
            encoding="utf-8")
        workspace = base / "工作区 A"; configured = base / "legacy-configured-cache"; env_cache = base / "legacy-env-cache"
        configured.mkdir(); env_cache.mkdir()
        for root in (configured, env_cache):
            model = root / "models--legacy--faster-whisper-base"; model.mkdir(); (model / "marker.bin").write_bytes(b"legacy")
        before_legacy = {"configured": snapshot(configured), "env": snapshot(env_cache)}
        env = dict(os.environ); env.update({"PYTHONUTF8":"1", "PYTHONPATH":os.pathsep.join((str(base/"fake-modules"), str(source/"src"))), "CS2POV_STATE_FILE":str(state), "HOME":str(home), "USERPROFILE":str(home), "LOCALAPPDATA":str(local), "XDG_STATE_HOME":str(xdg), "HF_HOME":str(env_cache), "HF_HUB_CACHE":str(env_cache), "FAKE_RECORD":str(record)})
        def run(*args: str):
            result = subprocess.run([sys.executable, "-m", "cs2pov.cli.commands", *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8")
            assert "Traceback" not in result.stderr, result.stderr
            try: return result.returncode, json.loads(result.stdout)
            except json.JSONDecodeError as exc: raise AssertionError(f"非 JSON 输出 {args}: {result.stdout!r}") from exc
        code, doc = run("models", "test", "--model", "base", "--json"); assert code == 1 and doc["error"]["code"] == "workspace_selection_required" and not record.exists()
        code, doc = run("workspace", "init", str(workspace), "--json"); assert code == 0 and doc["ok"]
        (home / ".cs2pov").mkdir(); (home / ".cs2pov" / "config.json").write_text(json.dumps({"whisper_cache_dir": str(configured)}), encoding="utf-8")
        code, info = run("models", "info", "--json"); assert code == 0 and info["deprecated_config"]["present"] is True
        paths = {row["path"] for row in info["legacy_candidates"]}; assert str(configured.resolve()) in paths and str(env_cache.resolve()) in paths
        assert all(row["managed"] is False for row in info["legacy_candidates"])
        code, result = run("models", "test", "--model", "base", "--json"); assert code == 0 and result["cache_dir"] == str((workspace/"cache/whisper").resolve())
        logged = record.read_text(encoding="utf-8")
        logged_data = json.loads(logged)
        assert logged_data["kwargs"]["download_root"] == str((workspace / "cache/whisper").resolve())
        logged_values = " ".join(str(value) for value in logged_data["kwargs"].values())
        for forbidden in (configured, env_cache, cwd, home, local):
            assert str(forbidden.resolve()) not in logged_values
        assert {"configured": snapshot(configured), "env": snapshot(env_cache)} == before_legacy
        before_record = record.read_bytes(); override = base / "override"
        code, rejected = run("models", "test", "--model", "base", "--cache-dir", str(override), "--json"); assert code == 1 and rejected["error"]["code"] == "legacy_model_cache_override_rejected" and not override.exists() and record.read_bytes() == before_record
        record.unlink(); whisper = workspace / "cache/whisper"; [child.rmdir() for child in whisper.iterdir() if child.is_dir()]; whisper.rmdir()
        code, failed = run("models", "test", "--model", "base", "--json"); assert code == 1 and failed["error"]["code"] == "workspace_unhealthy" and failed.get("diagnostic") and failed["diagnostic"]["ok"] is False and not record.exists() and not whisper.exists()
    print("workspace model runtime E2E passed: isolated subprocess cache binding and legacy rejection")
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except AssertionError as exc: print(f"E2E failed: {exc}", file=sys.stderr); raise SystemExit(1)
