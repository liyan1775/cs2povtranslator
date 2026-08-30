from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_cli(root: Path, state: Path, cwd: Path, *args: str) -> tuple[int, dict]:
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(root / "src"), "CS2POV_STATE_FILE": str(state),
                "HOME": str(cwd.parent / "HOME"), "USERPROFILE": str(cwd.parent / "HOME"),
                "LOCALAPPDATA": str(cwd.parent / "LOCALAPPDATA"), "XDG_STATE_HOME": str(cwd.parent / "XDG")})
    result = subprocess.run([sys.executable, "-m", "cs2pov.cli.commands", *args], cwd=cwd, env=env,
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
        cwd = base / "cwd"
        cwd.mkdir(parents=True)
        for name in ("HOME", "LOCALAPPDATA", "XDG"):
            (base / name).mkdir()
        monitored = [source_root, cwd, base / "HOME", base / "LOCALAPPDATA"]
        before = {(path, tuple(sorted(p.name for p in path.iterdir()))) for path in monitored}
        state = base / "状态" / "state.json"
        a, b = base / "工作区 A", base / "工作区 B"
        code, init_a = run_cli(source_root, state, cwd, "workspace", "init", str(a), "--json")
        assert code == 0 and init_a["ok"]
        config_a = (a / "workspace.json").read_bytes()
        marker_a = a / "marker.txt"; marker_a.write_bytes(b"A")
        code, show = run_cli(source_root, state, cwd, "workspace", "show", "--json")
        assert code == 0 and show["selected_workspace"] == str(a.resolve())
        code, doctor = run_cli(source_root, state, cwd, "workspace", "doctor", "--json")
        assert code == 0 and doctor["diagnostic"]["ok"]
        code, init_b = run_cli(source_root, state, cwd, "workspace", "init", str(b), "--json")
        assert code == 0 and init_b["ok"]
        config_b = (b / "workspace.json").read_bytes()
        marker_b = b / "marker.txt"; marker_b.write_bytes(b"B")
        code, _ = run_cli(source_root, state, cwd, "workspace", "use", str(a), "--json")
        assert code == 0
        code, show = run_cli(source_root, state, cwd, "workspace", "show", "--json")
        assert code == 0 and show["selected_workspace"] == str(a.resolve())
        code, forgotten = run_cli(source_root, state, cwd, "workspace", "forget", "--json")
        assert code == 0 and forgotten["forgotten"] is True
        code, missing = run_cli(source_root, state, cwd, "workspace", "show", "--json")
        assert code == 1 and missing["error"]["code"] == "selection_missing"
        env = dict(os.environ)
        env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(source_root / "src"), "CS2POV_STATE_FILE": str(state),
                    "HOME": str(base / "HOME"), "USERPROFILE": str(base / "HOME"),
                    "LOCALAPPDATA": str(base / "LOCALAPPDATA"), "XDG_STATE_HOME": str(base / "XDG")})
        launcher = subprocess.run([sys.executable, "-m", "cs2pov.cli.launcher", "--once"], cwd=cwd,
                                  env=env, input=f"6\n10\n1\n{b}\n", capture_output=True,
                                  text=True, encoding="utf-8")
        assert launcher.returncode == 0 and "工作区管理" in launcher.stdout
        if "Traceback" in launcher.stderr:
            raise RuntimeError("launcher emitted traceback")
        code, show = run_cli(source_root, state, cwd, "workspace", "show", "--json")
        assert code == 0 and show["selected_workspace"] == str(b.resolve())
        assert (a / "workspace.json").read_bytes() == config_a
        assert (b / "workspace.json").read_bytes() == config_b
        assert marker_a.read_bytes() == b"A" and marker_b.read_bytes() == b"B"
        for path, names in before:
            after = tuple(sorted(p.name for p in path.iterdir()))
            assert after == names
        state_assets = {p.name for p in state.parent.iterdir()}
        assert not state_assets.intersection({"models", "library", "jobs", "knowledge", "cache", "render_bundles"})
        assert state_assets <= {"state.json"}
    print("workspace CLI E2E passed: cross-process selection, isolation, and launcher flow")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"workspace CLI E2E failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
