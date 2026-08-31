from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import queue
import subprocess
import time

import pytest
import zstandard

from cs2pov.storage.demo_asset_repository import (
    DemoAssetRepositoryError,
    FileSystemDemoAssetRepository,
)
from cs2pov.workspace.paths import WorkspacePaths


def _import_worker(workspace: str, source: str, start_event, result_queue) -> None:
    try:
        if not start_event.wait(20):
            result_queue.put(("error", "start_timeout"))
            return
        result = FileSystemDemoAssetRepository(WorkspacePaths(Path(workspace))).import_source(Path(source))
        result_queue.put(("ok", result.asset.asset_id, result.disposition, result.asset.source_format))
    except DemoAssetRepositoryError as exc:
        result_queue.put(("error", exc.code))
    except BaseException as exc:  # pragma: no cover - reported to the parent with type only
        result_queue.put(("crash", type(exc).__name__))


def _run_import_processes(workspace: Path, sources: list[Path], *, timeout: float = 45.0):
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_import_worker,
            args=(str(workspace), str(source), start_event, result_queue),
        )
        for source in sources
    ]
    try:
        for process in processes:
            process.start()
        start_event.set()
        deadline = time.monotonic() + timeout
        for process in processes:
            process.join(max(0.0, deadline - time.monotonic()))
        alive = [process for process in processes if process.is_alive()]
        if alive:
            pytest.fail(f"Demo 导入子进程超时：{len(alive)} 个仍在运行")
        results = []
        for _ in processes:
            try:
                results.append(result_queue.get(timeout=5))
            except queue.Empty:
                break
        assert len(results) == len(processes), [process.exitcode for process in processes]
        assert all(process.exitcode == 0 for process in processes)
        return results
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(5)
        result_queue.close()


def _tree_bytes(root: Path):
    if not root.exists():
        return ()
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            entries.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            entries.append((relative, None))
    return tuple(entries)


def test_six_processes_import_same_plain_demo_atomically(tmp_path):
    logical = b"six-process-plain-demo" * 8192
    source = tmp_path / "match.dem"
    source.write_bytes(logical)
    workspace = tmp_path / "workspace"
    paths = WorkspacePaths(workspace)
    orphan = paths.temp_dir / "demo_imports" / "unrelated" / "asset"
    orphan.mkdir(parents=True)
    marker = orphan / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    results = _run_import_processes(workspace, [source] * 6)

    asset_id = hashlib.sha256(logical).hexdigest()
    assert all(result[0] == "ok" and result[1] == asset_id for result in results)
    assert sum(result[2] == "imported" for result in results) == 1
    asset_dirs = [path for path in paths.demo_library_dir.iterdir() if path.is_dir()]
    assert asset_dirs == [paths.demo_library_dir / asset_id]
    assert {path.name for path in asset_dirs[0].iterdir()} == {"asset.json", "source.dem"}
    assert (asset_dirs[0] / "source.dem").read_bytes() == logical
    assert marker.read_text("utf-8") == "keep"


def test_six_processes_import_different_zst_bytes_with_one_logical_identity(tmp_path):
    logical = bytes(range(256)) * 8192
    first = zstandard.ZstdCompressor(level=1).compress(logical)
    second = zstandard.ZstdCompressor(level=9).compress(logical)
    assert first != second
    sources = []
    for index in range(6):
        source = tmp_path / f"match-{index}.dem.zst"
        source.write_bytes(first if index % 2 == 0 else second)
        sources.append(source)
    workspace = tmp_path / "workspace"
    paths = WorkspacePaths(workspace)

    results = _run_import_processes(workspace, sources)

    asset_id = hashlib.sha256(logical).hexdigest()
    assert all(result[0] == "ok" and result[1] == asset_id for result in results)
    assert sum(result[2] == "imported" for result in results) == 1
    asset_dir = paths.demo_library_dir / asset_id
    assert {path.name for path in asset_dir.iterdir()} == {"asset.json", "source.dem.zst"}
    assert (asset_dir / "source.dem.zst").read_bytes() in {first, second}
    assert (paths.decompressed_demos_cache_dir / f"{asset_id}.dem").read_bytes() == logical
    assert len([path for path in paths.demo_library_dir.iterdir() if path.is_dir()]) == 1


def test_six_processes_never_overwrite_corrupt_final_asset(tmp_path):
    logical = b"corrupt-final-demo" * 4096
    source = tmp_path / "match.dem"
    source.write_bytes(logical)
    workspace = tmp_path / "workspace"
    paths = WorkspacePaths(workspace)
    imported = FileSystemDemoAssetRepository(paths).import_source(source)
    stored_source = paths.demo_library_dir / imported.asset.asset_id / "source.dem"
    stored_source.write_bytes(b"corrupt-final-must-remain")
    before = _tree_bytes(paths.demo_library_dir / imported.asset.asset_id)

    results = _run_import_processes(workspace, [source] * 6)

    assert results == [("error", "demo_asset_integrity_failed")] * 6
    assert _tree_bytes(paths.demo_library_dir / imported.asset.asset_id) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows junction containment check")
def test_six_processes_reject_cache_root_junction_without_external_write(tmp_path):
    logical = b"process-junction-demo" * 1024
    source = tmp_path / "match.dem.zst"
    source.write_bytes(zstandard.ZstdCompressor().compress(logical))
    workspace = tmp_path / "workspace"
    paths = WorkspacePaths(workspace)
    paths.cache_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(paths.decompressed_demos_cache_dir), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip("当前系统无法创建 Windows junction")
    before = _tree_bytes(outside)
    try:
        results = _run_import_processes(workspace, [source] * 6)
        assert results == [("error", "demo_asset_path_escape")] * 6
        assert _tree_bytes(outside) == before
        assert not paths.demo_library_dir.exists()
    finally:
        if paths.decompressed_demos_cache_dir.exists():
            paths.decompressed_demos_cache_dir.rmdir()
