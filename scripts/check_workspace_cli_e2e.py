from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_cli(root: Path, state: Path, *args: str) -> tuple[int, dict]:
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(root / "src"), "CS2POV_STATE_FILE": str(state)})
    result = subprocess.run([sys.executable, "-m", "cs2pov.cli.commands", *args], cwd=root, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    if "Traceback" in result.stderr:
        raise RuntimeError("CLI emitted traceback")
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI returned non-JSON output for {args}") from exc
    return result.returncode, document


def main() -> int:
    source_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="cs2pov-workspace-e2e-") as temp:
        base = Path(temp) / "中文 E2E"
        state = base / "状态" / "state.json"
        a, b = base / "工作区 A", base / "工作区 B"
        code, init_a = run_cli(source_root, state, "workspace", "init", str(a), "--json")
        assert code == 0 and init_a["ok"]
        config_a = (a / "workspace.json").read_bytes()
        code, show = run_cli(source_root, state, "workspace", "show", "--json")
        assert code == 0 and show["selected_workspace"] == str(a.resolve())
        code, doctor = run_cli(source_root, state, "workspace", "doctor", "--json")
        assert code == 0 and doctor["diagnostic"]["ok"]
        code, init_b = run_cli(source_root, state, "workspace", "init", str(b), "--json")
        assert code == 0 and init_b["ok"]
        config_b = (b / "workspace.json").read_bytes()
        code, _ = run_cli(source_root, state, "workspace", "use", str(a), "--json")
        assert code == 0
        code, show = run_cli(source_root, state, "workspace", "show", "--json")
        assert code == 0 and show["selected_workspace"] == str(a.resolve())
        code, forgotten = run_cli(source_root, state, "workspace", "forget", "--json")
        assert code == 0 and forgotten["forgotten"] is True
        code, missing = run_cli(source_root, state, "workspace", "show", "--json")
        assert code == 1 and missing["error"]["code"] == "selection_missing"
        env = dict(os.environ)
        env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(source_root / "src"), "CS2POV_STATE_FILE": str(state)})
        launcher = subprocess.run([sys.executable, "-m", "cs2pov.cli.launcher", "--once"], cwd=source_root,
                                  env=env, input=f"6\n10\n1\n{b}\n", capture_output=True,
                                  text=True, encoding="utf-8")
        assert launcher.returncode == 0 and "工作区管理" in launcher.stdout
        code, show = run_cli(source_root, state, "workspace", "show", "--json")
        assert code == 0 and show["selected_workspace"] == str(b.resolve())
        assert (a / "workspace.json").read_bytes() == config_a
        assert (b / "workspace.json").read_bytes() == config_b
        state_assets = {p.name for p in state.parent.iterdir()}
        assert not state_assets.intersection({"models", "library", "jobs", "knowledge", "cache", "render_bundles"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
