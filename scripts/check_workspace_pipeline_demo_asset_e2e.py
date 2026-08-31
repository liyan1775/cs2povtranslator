from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import zstandard


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(root: Path):
    if not root.exists():
        return ()
    values = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in directories:
            path = current_path / name
            values.append((path.relative_to(root).as_posix(), "link" if path.is_symlink() else "dir", None, None))
        for name in files:
            path = current_path / name
            if path.is_symlink():
                values.append((path.relative_to(root).as_posix(), "link", None, None))
            else:
                stat = path.stat()
                values.append((path.relative_to(root).as_posix(), "file", stat.st_size, _hash_file(path)))
    return tuple(values)


def _run(source_root: Path, cwd: Path, env: dict[str, str], *arguments: str, expected_code: int = 0) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "cs2pov", *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert completed.returncode == expected_code, {
        "arguments": arguments,
        "expected": expected_code,
        "actual": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    assert completed.stderr == "", {"arguments": arguments, "stderr": completed.stderr}
    return completed.stdout


def _run_json(source_root: Path, cwd: Path, env: dict[str, str], *arguments: str, expected_code: int = 0) -> dict:
    text = _run(source_root, cwd, env, *arguments, "--json", expected_code=expected_code)
    return json.loads(text)


def _job_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "manifest.json").is_file())


def _assert_empty_input(job: Path) -> None:
    input_dir = job / "input"
    assert input_dir.is_dir()
    assert not list(input_dir.iterdir())


def main() -> int:
    source_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="cs2pov-pipeline-e2e-") as temporary:
        base = Path(temporary).resolve()
        cwd = base / "cwd"
        cwd.mkdir()
        workspace_a = base / "workspace-a"
        workspace_b = base / "workspace-b"
        state_file = base / "state" / "workspace.json"
        inputs = base / "external-inputs"
        inputs.mkdir()
        isolated = {
            "home": base / "HOME",
            "userprofile": base / "USERPROFILE",
            "localappdata": base / "LOCALAPPDATA",
            "appdata": base / "APPDATA",
            "xdg_state": base / "XDG_STATE_HOME",
            "xdg_config": base / "XDG_CONFIG_HOME",
            "temp": base / "TEMP",
            "other": base / "other-workspace",
        }
        for name, path in isolated.items():
            path.mkdir(parents=True)
            (path / f"{name}.sentinel").write_text("unchanged", encoding="utf-8")

        env = os.environ.copy()
        env.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(source_root / "src"),
                "CS2POV_STATE_FILE": str(state_file),
                "HOME": str(isolated["home"]),
                "USERPROFILE": str(isolated["userprofile"]),
                "LOCALAPPDATA": str(isolated["localappdata"]),
                "APPDATA": str(isolated["appdata"]),
                "XDG_STATE_HOME": str(isolated["xdg_state"]),
                "XDG_CONFIG_HOME": str(isolated["xdg_config"]),
                "TMP": str(isolated["temp"]),
                "TEMP": str(isolated["temp"]),
                "TMPDIR": str(isolated["temp"]),
            }
        )

        logical = (b"anonymous pipeline demo\x00" + bytes(range(64))) * 8192
        compressed_a = zstandard.ZstdCompressor(level=1).compress(logical)
        compressed_b = zstandard.ZstdCompressor(level=19).compress(logical)
        assert compressed_a != compressed_b
        source_a = inputs / "first match.dem.zst"
        source_b = inputs / "renamed match.dem.zst"
        source_a.write_bytes(compressed_a)
        source_b.write_bytes(compressed_b)
        external_snapshot = _snapshot(inputs)
        source_a_text = str(source_a)
        source_b_text = str(source_b)
        source_tree_snapshot = _snapshot(source_root)
        cwd_snapshot = _snapshot(cwd)
        isolated_snapshots = {name: _snapshot(path) for name, path in isolated.items()}

        missing = _run_json(source_root, cwd, env, "demos", "list", expected_code=1)
        assert missing["error"]["code"] == "workspace_selection_required"
        assert not state_file.exists()

        initialized = _run_json(source_root, cwd, env, "workspace", "init", str(workspace_a))
        assert initialized["ok"] is True
        first_output = _run(source_root, cwd, env, "run", str(source_a), "--map", "first", "--to-stage", "prepare_input")
        assert "已导入到当前工作区素材库" in first_output
        assert source_a_text not in first_output
        jobs_a = _job_dirs(workspace_a / "jobs")
        assert len(jobs_a) == 1

        second_output = _run(source_root, cwd, env, "run", str(source_b), "--map", "second", "--to-stage", "prepare_input")
        assert "工作区已有相同 Demo" in second_output
        assert source_b_text not in second_output
        jobs_a = _job_dirs(workspace_a / "jobs")
        assert len(jobs_a) == 2
        first_job, second_job = jobs_a
        manifests = [json.loads((job / "manifest.json").read_text("utf-8")) for job in jobs_a]
        asset_id = hashlib.sha256(logical).hexdigest()
        for manifest in manifests:
            assert manifest["demo"]["input_mode"] == "demo_asset"
            assert manifest["demo"]["asset_id"] == asset_id
            assert manifest["demo"]["asset_manifest"] == f"library/demos/{asset_id}/asset.json"
            assert "demo_path" not in manifest.get("artifacts", {})
            serialized = json.dumps(manifest, ensure_ascii=False)
            assert source_a_text not in serialized and source_b_text not in serialized
            assert str(workspace_a / "library") not in serialized
            assert str(workspace_a / "cache") not in serialized
        for job in jobs_a:
            _assert_empty_input(job)

        library_asset = workspace_a / "library" / "demos" / asset_id
        assert (library_asset / "source.dem.zst").read_bytes() == compressed_a
        assert not (workspace_a / "library" / "demos" / "source.dem.zst").exists()

        external_output = base / "external-output"
        external_run = _run(source_root, cwd, env, "run", str(source_b), "--map", "external", "--output", str(external_output), "--to-stage", "prepare_input")
        assert external_run.count("旧版外部输出") >= 2
        external_jobs = _job_dirs(external_output)
        assert len(external_jobs) == 1
        _assert_empty_input(external_jobs[0])
        assert not (external_output / "library").exists()
        assert _snapshot(inputs) == external_snapshot

        cache = workspace_a / "cache" / "decompressed_demos" / f"{asset_id}.dem"
        assert cache.is_file()
        cache.unlink()
        source_a.unlink()
        source_b.unlink()
        resumed = _run(source_root, cwd, env, "resume", str(first_job), "--from-stage", "prepare_input", "--to-stage", "prepare_input")
        assert "恢复执行完成" in resumed
        assert cache.read_bytes() == logical
        _assert_empty_input(first_job)
        assert not source_a.exists() and not source_b.exists()

        job_before_workspace_switch = _snapshot(first_job)
        _run_json(source_root, cwd, env, "workspace", "init", str(workspace_b))
        failed_switch = _run(source_root, cwd, env, "resume", str(first_job), "--from-stage", "prepare_input", "--to-stage", "prepare_input", expected_code=1)
        assert "demo_asset_not_found" in failed_switch
        assert str(workspace_a) not in failed_switch
        assert _snapshot(first_job) == job_before_workspace_switch
        assert not list((workspace_b / "library" / "demos").iterdir())

        late_manifest_path = first_job / "manifest.json"
        late_manifest = json.loads(late_manifest_path.read_text("utf-8"))
        late_manifest["config"]["skip_translation"] = True
        late_manifest_path.write_text(json.dumps(late_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (first_job / "artifacts" / "round_contexts.jsonl").write_text("", encoding="utf-8")
        late_resume = _run(source_root, cwd, env, "resume", str(first_job), "--from-stage", "translate", "--to-stage", "translate")
        assert "恢复执行完成" in late_resume

        _run_json(source_root, cwd, env, "workspace", "use", str(workspace_a))
        legacy_job = workspace_a / "jobs" / "legacy-fixture"
        legacy_job.mkdir(parents=True)
        legacy_input = legacy_job / "input"
        legacy_input.mkdir()
        (legacy_input / "legacy.dem").write_bytes(b"legacy-demo")
        legacy_manifest = json.loads((second_job / "manifest.json").read_text("utf-8"))
        legacy_manifest["job_id"] = "legacy-fixture"
        legacy_manifest["demo"] = {}
        legacy_job.joinpath("manifest.json").write_text(json.dumps(legacy_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        library_before_legacy = _snapshot(workspace_a / "library" / "demos")
        _run(source_root, cwd, env, "resume", str(legacy_job), "--from-stage", "prepare_input", "--to-stage", "prepare_input")
        legacy_after = json.loads((legacy_job / "manifest.json").read_text("utf-8"))
        assert legacy_after["demo"] == {"input_mode": "legacy_job_copy"}
        assert (legacy_input / "legacy.dem").read_bytes() == b"legacy-demo"
        assert _snapshot(workspace_a / "library" / "demos") == library_before_legacy

        damaged_source = inputs / "retry.dem"
        damaged_source.write_bytes(logical)
        persistent_source = library_asset / "source.dem.zst"
        persistent_source.write_bytes(b"tampered")
        damaged_before_jobs = _snapshot(workspace_a / "jobs")
        damaged = _run(source_root, cwd, env, "run", str(damaged_source), "--map", "damaged", "--to-stage", "prepare_input", expected_code=1)
        assert "demo_asset_integrity_failed" in damaged
        assert _snapshot(workspace_a / "jobs") == damaged_before_jobs
        assert str(damaged_source) not in damaged

        assert _snapshot(source_root) == source_tree_snapshot
        assert _snapshot(cwd) == cwd_snapshot
        for name, before in isolated_snapshots.items():
            assert _snapshot(isolated[name]) == before

    print("workspace Pipeline DemoAsset E2E passed: auto-import, reference-only jobs, resume, legacy compatibility, and isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
