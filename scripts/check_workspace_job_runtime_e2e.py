"""Cross-process acceptance check for workspace-bound Job filesystem behavior."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def snapshot(root: Path) -> tuple[str, tuple[str, ...], dict[str, str]]:
    if not root.exists():
        return "missing", (), {}
    directories = tuple(sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_dir()))
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }
    return "present", directories, files


def run_cli(source_root: Path, cwd: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "cs2pov.cli.commands", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if "Traceback" in result.stdout or "Traceback" in result.stderr:
        raise AssertionError(f"CLI emitted traceback for {args}:\n{result.stdout}\n{result.stderr}")
    return result


def json_stdout(result: subprocess.CompletedProcess[str], args: tuple[str, ...]) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"expected JSON stdout for {args}: {result.stdout!r}") from exc


def assert_independent_copy(source: Path, copied: Path) -> None:
    assert copied.exists() and copied.read_bytes() == source.read_bytes()
    assert not os.path.samefile(copied, source)


def manifest_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in manifest_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in manifest_strings(child)]
    return []


def assert_manifest_hides_roots(path: Path, roots: tuple[Path, ...]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    values = [item.replace("\\", "/").casefold() for item in manifest_strings(document)]
    for root in roots:
        normalized = str(root.resolve()).replace("\\", "/").casefold().rstrip("/")
        assert not any(normalized in value for value in values), root


def assert_stable_error(result: subprocess.CompletedProcess[str], code: str) -> None:
    assert result.returncode == 1, result.stdout
    assert f"错误[{code}]" in result.stdout, result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def main() -> int:
    source_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="cs2pov-job-runtime-e2e-") as temp:
        base = Path(temp) / "中文 Job E2E"
        cwd = base / "cwd"
        home = base / "HOME"
        userprofile = base / "USERPROFILE"
        localappdata = base / "LOCALAPPDATA"
        appdata = base / "APPDATA"
        xdg_state = base / "XDG_STATE_HOME"
        xdg_config = base / "XDG_CONFIG_HOME"
        state = base / "state" / "selection.json"
        workspace = base / "工作区"
        old_cache = base / "old-cache"
        external_demo_dir = base / "外部 demo"
        external_output = base / "legacy-output"
        for path in (cwd, home, userprofile, localappdata, appdata, xdg_state, state.parent, old_cache, external_demo_dir):
            path.mkdir(parents=True, exist_ok=True)
        demo = external_demo_dir / "synthetic.dem"
        demo.write_bytes(b"synthetic demo; prepare_input only\n")
        old_marker = old_cache / "legacy-marker.bin"
        old_marker.write_bytes(b"must remain untouched")

        env = dict(os.environ)
        env.update({
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(source_root / "src"),
            "CS2POV_STATE_FILE": str(state),
            "HOME": str(home),
            "USERPROFILE": str(userprofile),
            "LOCALAPPDATA": str(localappdata),
            "APPDATA": str(appdata),
            "XDG_STATE_HOME": str(xdg_state),
            "XDG_CONFIG_HOME": str(xdg_config),
            "HF_HOME": str(old_cache),
            "HF_HUB_CACHE": str(old_cache),
        })
        xdg_config.mkdir()

        bypass_roots = (source_root, cwd, home, userprofile, localappdata, appdata, xdg_state, xdg_config, state.parent, old_cache, external_demo_dir)
        demo_hash = hashlib.sha256(demo.read_bytes()).hexdigest()
        init_bypass_roots = tuple(path for path in bypass_roots if path != state.parent)
        before_init_bypass = {path: snapshot(path) for path in init_bypass_roots}

        initialized = run_cli(source_root, cwd, env, "workspace", "init", str(workspace), "--json")
        initialized_doc = json_stdout(initialized, ("workspace", "init"))
        assert initialized.returncode == 0 and initialized_doc["ok"] is True
        assert set(path.name for path in state.parent.iterdir()) == {state.name}
        for path in init_bypass_roots:
            assert snapshot(path) == before_init_bypass[path], path
        before_bypass = {path: snapshot(path) for path in bypass_roots}

        default_run = run_cli(source_root, cwd, env, "run", str(demo), "--to-stage", "prepare_input")
        assert default_run.returncode == 0, default_run.stdout + default_run.stderr
        default_jobs = [path for path in (workspace / "jobs").iterdir() if path.is_dir()]
        assert len(default_jobs) == 1
        default_job = default_jobs[0]
        assert hashlib.sha256(demo.read_bytes()).hexdigest() == demo_hash
        default_manifest_path = default_job / "manifest.json"
        default_manifest = json.loads(default_manifest_path.read_text(encoding="utf-8"))
        assert default_manifest["legacy_external_output"] is False
        assert default_manifest["path_policy_version"] == 1
        assert default_manifest["demo"]["input_mode"] == "demo_asset"
        assert default_manifest["demo"]["asset_id"] == demo_hash
        assert "demo_path" not in default_manifest.get("artifacts", {})
        assert not list((default_job / "input").iterdir())
        assert_manifest_hides_roots(default_manifest_path, (workspace, external_output, home, userprofile, localappdata, appdata, xdg_state, xdg_config, state, cwd, old_cache, demo, external_demo_dir))
        assert (workspace / "library" / "demos" / demo_hash / "asset.json").is_file()
        for path in bypass_roots:
            assert snapshot(path) == before_bypass[path], path

        rejected_cache = run_cli(source_root, cwd, env, "run", str(demo), "--to-stage", "prepare_input", "--whisper-cache-dir", str(old_cache))
        assert_stable_error(rejected_cache, "legacy_model_cache_override_rejected")
        assert len([path for path in (workspace / "jobs").iterdir() if path.is_dir()]) == 1
        for path in bypass_roots:
            assert snapshot(path) == before_bypass[path], path

        explicit_run = run_cli(source_root, cwd, env, "run", str(demo), "--output", str(external_output), "--to-stage", "prepare_input")
        assert explicit_run.returncode == 0, explicit_run.stdout + explicit_run.stderr
        assert explicit_run.stdout.count("旧版外部输出") >= 2
        explicit_jobs = [path for path in external_output.iterdir() if path.is_dir()]
        assert len(explicit_jobs) == 1
        explicit_manifest_path = explicit_jobs[0] / "manifest.json"
        explicit_manifest = json.loads(explicit_manifest_path.read_text(encoding="utf-8"))
        assert explicit_manifest["legacy_external_output"] is True
        assert explicit_manifest["demo"]["input_mode"] == "demo_asset"
        assert explicit_manifest["demo"]["asset_id"] == demo_hash
        assert "demo_path" not in explicit_manifest.get("artifacts", {})
        assert not list((explicit_jobs[0] / "input").iterdir())
        assert_manifest_hides_roots(explicit_manifest_path, (workspace, external_output, home, userprofile, localappdata, appdata, xdg_state, xdg_config, state, cwd, old_cache, demo, external_demo_dir))
        for path in bypass_roots:
            assert snapshot(path) == before_bypass[path], path

        workspace_config = workspace / "workspace.json"
        workspace_config.write_bytes(b"{broken workspace config")
        before_broken = {
            path: snapshot(path)
            for path in (workspace, external_output, cwd, home, userprofile, localappdata, appdata, xdg_state, xdg_config, state.parent, old_cache, external_demo_dir, source_root)
        }
        broken_default = run_cli(source_root, cwd, env, "run", str(demo), "--to-stage", "prepare_input")
        assert_stable_error(broken_default, "workspace_unhealthy")
        assert {path: snapshot(path) for path in before_broken} == before_broken
        broken_explicit = run_cli(source_root, cwd, env, "run", str(demo), "--output", str(external_output), "--to-stage", "prepare_input")
        assert_stable_error(broken_explicit, "workspace_unhealthy")
        assert {path: snapshot(path) for path in before_broken} == before_broken
        assert hashlib.sha256(demo.read_bytes()).hexdigest() == demo_hash

    print("workspace Job runtime E2E passed: real CLI path isolation, compatibility, and pre-write failure gates")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"workspace Job runtime E2E failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
