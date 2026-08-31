"""Cross-process acceptance check for workspace-bound model caches."""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path

def main() -> int:
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="cs2pov-model-e2e-") as td:
        base = Path(td) / "中文 E2E"; cwd = base / "cwd"; cwd.mkdir(parents=True)
        home, local, xdg, state, fake = (base / x for x in ("HOME", "LOCALAPPDATA", "XDG", "state/state.json", "fake"))
        for p in (home, local, xdg, state.parent, fake): p.mkdir(parents=True, exist_ok=True)
        record = base / "fake-record.json"
        (fake / "faster_whisper.py").write_text("import json,os\nclass WhisperModel:\n def __init__(self, model, **kwargs):\n  p=os.environ['FAKE_RECORD']; open(p,'w',encoding='utf8').write(json.dumps({'model':model,'kwargs':kwargs}))\n", encoding="utf-8")
        ws = base / "工作区 A"
        env = dict(os.environ); env.update(PYTHONUTF8="1", PYTHONPATH=os.pathsep.join((str(fake), str(source/'src'))), CS2POV_STATE_FILE=str(state), HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(local), XDG_STATE_HOME=str(xdg), FAKE_RECORD=str(record))
        def run(*args):
            r = subprocess.run([sys.executable, "-m", "cs2pov.cli.commands", *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8")
            assert "Traceback" not in r.stderr, r.stderr
            return r.returncode, json.loads(r.stdout)
        code, doc = run("models", "test", "--model", "base", "--json")
        assert code == 1 and doc["error"]["code"] == "workspace_selection_required" and not record.exists()
        code, doc = run("workspace", "init", str(ws), "--json"); assert code == 0 and doc["ok"]
        legacy = base / "legacy-configured-cache"; legacy.mkdir(); (legacy / "marker").write_bytes(b"legacy")
        (home / ".cs2pov").mkdir(); (home / ".cs2pov" / "config.json").write_text(json.dumps({"whisper_cache_dir":str(legacy)}), encoding="utf-8")
        env_cache = base / "legacy-env-cache"; env_cache.mkdir(); (env_cache / "marker").write_bytes(b"env"); env["HF_HOME"] = str(env_cache); env["HF_HUB_CACHE"] = str(env_cache)
        code, info = run("models", "info", "--json"); assert code == 0 and info["workspace_cache"]["whisper"] == str((ws/'cache/whisper').resolve())
        code, result = run("models", "test", "--model", "base", "--json"); assert code == 0 and result["cache_dir"] == str((ws/'cache/whisper').resolve())
        logged = json.loads(record.read_text(encoding="utf-8")); assert logged["kwargs"]["download_root"] == str((ws/'cache/whisper').resolve())
        before = record.read_bytes(); outside = base / "override"
        code, rejected = run("models", "test", "--model", "base", "--cache-dir", str(outside), "--json"); assert code == 1 and rejected["error"]["code"] == "legacy_model_cache_override_rejected" and not outside.exists() and record.read_bytes() == before
        (ws/'cache/whisper').rmdir(); record.unlink(); code, failed = run("models", "test", "--model", "base", "--json"); assert code == 1 and not record.exists()
    print("workspace model runtime E2E passed: isolated subprocess cache binding and legacy rejection")
    return 0
if __name__ == "__main__":
    try: raise SystemExit(main())
    except AssertionError as exc: print(f"E2E failed: {exc}", file=sys.stderr); raise SystemExit(1)
