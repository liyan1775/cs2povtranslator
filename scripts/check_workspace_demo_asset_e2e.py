from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import zstandard


ASSET_KEYS = {
    "schema_version",
    "asset_id",
    "logical_sha256",
    "logical_size_bytes",
    "source_sha256",
    "source_size_bytes",
    "source_format",
    "source_relative_path",
    "display_name",
    "imported_at",
}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
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
            relative = path.relative_to(root).as_posix()
            values.append((relative, "link" if path.is_symlink() else "dir", None, None))
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                values.append((relative, "link", None, None))
            else:
                stat = path.stat()
                values.append((relative, "file", stat.st_size, _hash_file(path)))
    return tuple(values)


def _run(source_root: Path, env: dict[str, str], *arguments: str, expected_code: int = 0):
    completed = subprocess.run(
        [sys.executable, "-m", "cs2pov", *arguments],
        cwd=source_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
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
    return json.loads(completed.stdout)


def _spawn_import(source_root: Path, env: dict[str, str], source: Path):
    return subprocess.Popen(
        [sys.executable, "-m", "cs2pov", "demos", "import", str(source), "--json"],
        cwd=source_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def main() -> int:
    source_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="cs2pov-demo-asset-e2e-") as temporary:
        base = Path(temporary).resolve()
        workspace = base / "workspace"
        state_file = base / "state" / "workspace.json"
        inputs = base / "inputs"
        inputs.mkdir()

        isolated_roots = {
            "home": base / "HOME",
            "local": base / "LOCALAPPDATA",
            "app": base / "APPDATA",
            "xdg_state": base / "XDG_STATE",
            "xdg_config": base / "XDG_CONFIG",
            "os_temp": base / "OS_TEMP",
            "outside": base / "outside",
        }
        for name, root in isolated_roots.items():
            root.mkdir(parents=True)
            (root / f"{name}.sentinel").write_text("unchanged", encoding="utf-8")

        env = os.environ.copy()
        env.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(source_root / "src"),
                "CS2POV_STATE_FILE": str(state_file),
                "HOME": str(isolated_roots["home"]),
                "USERPROFILE": str(isolated_roots["home"]),
                "LOCALAPPDATA": str(isolated_roots["local"]),
                "APPDATA": str(isolated_roots["app"]),
                "XDG_STATE_HOME": str(isolated_roots["xdg_state"]),
                "XDG_CONFIG_HOME": str(isolated_roots["xdg_config"]),
                "TMP": str(isolated_roots["os_temp"]),
                "TEMP": str(isolated_roots["os_temp"]),
                "TMPDIR": str(isolated_roots["os_temp"]),
            }
        )

        logical = bytes(range(256)) * 4096
        plain = inputs / "same content.dem"
        zst_a = inputs / "first source.dem.zst"
        zst_b = inputs / "different compression.dem.zst"
        concurrent_source = inputs / "fresh concurrent source.dem.zst"
        plain.write_bytes(logical)
        first_compressed = zstandard.ZstdCompressor(level=1).compress(logical)
        second_compressed = zstandard.ZstdCompressor(level=9).compress(logical)
        assert first_compressed != second_compressed
        zst_a.write_bytes(first_compressed)
        zst_b.write_bytes(second_compressed)
        concurrent_logical = b"fresh-concurrent-logical-demo" * 65536
        concurrent_source.write_bytes(zstandard.ZstdCompressor(level=3).compress(concurrent_logical))
        source_stats = {
            path: (path.stat().st_size, path.stat().st_mtime_ns, _hash_file(path))
            for path in (plain, zst_a, zst_b, concurrent_source)
        }

        source_before = _snapshot(source_root)
        isolated_before = {name: _snapshot(root) for name, root in isolated_roots.items()}
        inputs_before = _snapshot(inputs)
        missing = _run(
            source_root,
            env,
            "demos",
            "import",
            str(zst_a),
            "--json",
            expected_code=1,
        )
        assert missing["command"] == "demos.import"
        assert missing["error"]["code"] == "workspace_selection_required"
        assert not workspace.exists() and not state_file.parent.exists()
        assert _snapshot(source_root) == source_before
        assert {name: _snapshot(root) for name, root in isolated_roots.items()} == isolated_before
        assert _snapshot(inputs) == inputs_before

        initialized = _run(source_root, env, "workspace", "init", str(workspace), "--json")
        assert initialized["ok"] is True
        assert state_file.is_file()

        imported = _run(source_root, env, "demos", "import", str(zst_a), "--json")
        reused_plain = _run(source_root, env, "demos", "import", str(plain), "--json")
        reused_zst = _run(source_root, env, "demos", "import", str(zst_b), "--json")
        assert [
            imported["result"]["disposition"],
            reused_plain["result"]["disposition"],
            reused_zst["result"]["disposition"],
        ] == ["imported", "reused", "reused"]
        asset_id = hashlib.sha256(logical).hexdigest()
        assert {
            imported["result"]["asset"]["asset_id"],
            reused_plain["result"]["asset"]["asset_id"],
            reused_zst["result"]["asset"]["asset_id"],
        } == {asset_id}

        library = workspace / "library" / "demos"
        asset_dirs = [path for path in library.iterdir() if path.is_dir()]
        assert asset_dirs == [library / asset_id]
        asset_dir = asset_dirs[0]
        assert {path.name for path in asset_dir.iterdir()} == {"asset.json", "source.dem.zst"}
        assert (asset_dir / "source.dem.zst").read_bytes() == first_compressed
        manifest_path = asset_dir / "asset.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        assert set(manifest) == ASSET_KEYS
        assert manifest["source_relative_path"] == f"library/demos/{asset_id}/source.dem.zst"
        manifest_text = manifest_path.read_text("utf-8")
        for forbidden in [str(base), *(str(root) for root in isolated_roots.values())]:
            assert forbidden not in manifest_text

        listed = _run(source_root, env, "demos", "list", "--json")
        inspected = _run(source_root, env, "demos", "inspect", asset_id, "--json")
        assert listed["count"] == 1 and listed["assets"][0]["asset_id"] == asset_id
        assert inspected["inspection"]["source_ok"] is True
        assert inspected["inspection"]["cache_status"] == "valid"
        for document in (listed, inspected):
            encoded = json.dumps(document, ensure_ascii=False)
            assert str(inputs) not in encoded
            assert str(base / "HOME") not in encoded

        cache = workspace / "cache" / "decompressed_demos" / f"{asset_id}.dem"
        assert cache.read_bytes() == logical
        cache.unlink()
        workspace_before_inspect = _snapshot(workspace)
        missing_cache = _run(source_root, env, "demos", "inspect", asset_id, "--json")
        assert missing_cache["inspection"]["cache_status"] == "missing"
        assert _snapshot(workspace) == workspace_before_inspect
        repaired = _run(source_root, env, "demos", "import", str(zst_a), "--json")
        assert repaired["result"]["disposition"] == "reused"
        assert cache.read_bytes() == logical

        orphan = workspace / "cache" / "tmp" / "demo_imports" / "orphan" / "asset"
        orphan.mkdir(parents=True)
        orphan_marker = orphan / "incomplete.txt"
        orphan_marker.write_text("keep", encoding="utf-8")
        assert _run(source_root, env, "demos", "list", "--json")["count"] == 1
        processes = [_spawn_import(source_root, env, concurrent_source) for _ in range(6)]
        concurrent = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=45)
            assert process.returncode == 0, {"stdout": stdout, "stderr": stderr}
            assert stderr == ""
            concurrent.append(json.loads(stdout))
        concurrent_asset_id = hashlib.sha256(concurrent_logical).hexdigest()
        assert all(item["result"]["asset"]["asset_id"] == concurrent_asset_id for item in concurrent)
        assert sorted(item["result"]["disposition"] for item in concurrent) == ["imported", *("reused" for _ in range(5))]
        assert len([path for path in library.iterdir() if path.is_dir()]) == 2
        concurrent_asset = library / concurrent_asset_id
        assert {path.name for path in concurrent_asset.iterdir()} == {"asset.json", "source.dem.zst"}
        assert (
            workspace / "cache" / "decompressed_demos" / f"{concurrent_asset_id}.dem"
        ).read_bytes() == concurrent_logical
        assert orphan_marker.read_text("utf-8") == "keep"

        workspace_config = workspace / "workspace.json"
        config_bytes = workspace_config.read_bytes()
        workspace_config.write_text("{broken-json", encoding="utf-8")
        library_before_failure = _snapshot(library)
        cache_before_failure = _snapshot(workspace / "cache")
        broken = _run(
            source_root,
            env,
            "demos",
            "import",
            str(plain),
            "--json",
            expected_code=1,
        )
        assert broken["error"]["code"] == "workspace_unhealthy"
        assert _snapshot(library) == library_before_failure
        assert _snapshot(workspace / "cache") == cache_before_failure
        workspace_config.write_bytes(config_bytes)

        stored_source = asset_dir / "source.dem.zst"
        replacement_logical = b"different-logical-content" * 4096
        replacement_source = zstandard.ZstdCompressor(level=1).compress(replacement_logical)
        stored_source.write_bytes(replacement_source)
        tampered_manifest = dict(manifest)
        tampered_manifest["source_sha256"] = hashlib.sha256(replacement_source).hexdigest()
        tampered_manifest["source_size_bytes"] = len(replacement_source)
        manifest_path.write_text(
            json.dumps(tampered_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        damaged_before = _snapshot(asset_dir)
        damaged_inspection = _run(
            source_root,
            env,
            "demos",
            "inspect",
            asset_id,
            "--json",
            expected_code=1,
        )
        assert damaged_inspection["inspection"]["source_ok"] is False
        refused = _run(
            source_root,
            env,
            "demos",
            "import",
            str(zst_a),
            "--json",
            expected_code=1,
        )
        assert refused["error"]["code"] == "demo_asset_integrity_failed"
        assert _snapshot(asset_dir) == damaged_before

        for path, expected in source_stats.items():
            stat = path.stat()
            assert (stat.st_size, stat.st_mtime_ns, _hash_file(path)) == expected
        assert _snapshot(inputs) == inputs_before
        assert _snapshot(source_root) == source_before
        assert {name: _snapshot(root) for name, root in isolated_roots.items()} == isolated_before
        assert not (source_root / "output").exists()
        assert not (source_root / "jobs").exists()

    print("workspace DemoAsset E2E passed: content dedupe, atomic concurrency, integrity, and path isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
