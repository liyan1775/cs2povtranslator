import multiprocessing
import time

import pytest

from cs2pov.storage.cross_process_lock import CrossProcessFileLock
from cs2pov.storage.job_errors import JobRepositoryError


def _lock_worker(path, queue):
    try:
        with CrossProcessFileLock.open_existing(path, timeout_ms=1000):
            queue.put("entered")
            time.sleep(0.15)
    except JobRepositoryError as exc:
        queue.put(exc.code)


def _lock_race_worker(path, queue):
    try:
        with CrossProcessFileLock.open_existing(path, timeout_ms=1500):
            queue.put("entered")
    except JobRepositoryError as exc:
        queue.put(exc.code)


def _bootstrap_worker(path, queue):
    with CrossProcessFileLock.bootstrap_for_write(path, timeout_ms=3000):
        queue.put(time.monotonic())
        time.sleep(0.15)


def _crash_worker(path, ready):
    with CrossProcessFileLock.open_existing(path, timeout_ms=1000):
        ready.set()
        __import__("os")._exit(7)


def test_lock_requires_existing_regular_nonempty_file(tmp_path):
    p = tmp_path / "lock"
    with pytest.raises(JobRepositoryError):
        with CrossProcessFileLock.open_existing(p, timeout_ms=10):
            pass
    p.write_bytes(b"0")
    with CrossProcessFileLock.open_existing(p, timeout_ms=100):
        assert p.exists()


def test_lock_is_non_reentrant(tmp_path):
    p = tmp_path / "lock"
    p.write_bytes(b"0")
    with CrossProcessFileLock.open_existing(p, timeout_ms=100):
        with pytest.raises(JobRepositoryError):
            with CrossProcessFileLock.open_existing(p, timeout_ms=10):
                pass


def test_lock_rejects_bool_timeout_and_bootstraps_zero_length_same_path(tmp_path):
    p = tmp_path / "lock"
    with pytest.raises(JobRepositoryError):
        with CrossProcessFileLock.bootstrap_for_write(p, timeout_ms=True):
            pass
    p.touch()
    with CrossProcessFileLock.bootstrap_for_write(p, timeout_ms=100):
        assert p.stat().st_size == 1


def test_two_processes_cannot_enter_lock_critical_section_together(tmp_path):
    p = tmp_path / "lock"
    p.write_bytes(b"0")
    queue = multiprocessing.get_context("spawn").Queue()
    first = multiprocessing.get_context("spawn").Process(target=_lock_worker, args=(p, queue))
    second = multiprocessing.get_context("spawn").Process(target=_lock_worker, args=(p, queue))
    first.start()
    assert queue.get(timeout=3) == "entered"
    second.start()
    result = queue.get(timeout=3)
    first.join(3)
    second.join(3)
    assert result == "entered"
    assert first.exitcode == 0 and second.exitcode == 0


def test_path_replacement_during_descriptor_validation_maps_interrupted(tmp_path, monkeypatch):
    p = tmp_path / "lock"
    p.write_bytes(b"0")
    original = __import__("os").lstat
    def fail_lstat(path):
        if str(path) == str(p):
            raise OSError("injected pathname race")
        return original(path)
    monkeypatch.setattr("cs2pov.storage.cross_process_lock.os.lstat", fail_lstat)
    with pytest.raises(JobRepositoryError) as exc:
        with CrossProcessFileLock.open_existing(p, timeout_ms=100):
            pass
    assert exc.value.code == "job_write_interrupted"
    assert isinstance(exc.value.__cause__, OSError)


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX inode race semantics")
@pytest.mark.parametrize("race", ["unlink", "replace"])
def test_child_waiting_lock_detects_path_unlink_or_replacement(tmp_path, race):
    import os
    p = tmp_path / "lock"
    p.write_bytes(b"0")
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    child = ctx.Process(target=_lock_race_worker, args=(p, queue))
    with CrossProcessFileLock.open_existing(p, timeout_ms=1000):
        child.start()
        time.sleep(0.2)
        if race == "unlink":
            p.unlink()
        else:
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"1")
            os.replace(replacement, p)
    result = queue.get(timeout=3)
    child.join(3)
    assert result == "job_write_interrupted"
    assert child.exitcode == 0


def test_absent_lock_bootstrap_is_single_file_and_serialized(tmp_path):
    p = tmp_path / "absent.lock"
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    children = [ctx.Process(target=_bootstrap_worker, args=(p, queue)) for _ in range(2)]
    for child in children:
        child.start()
    entered = sorted(queue.get(timeout=5) for _ in children)
    for child in children:
        child.join(5)
    assert p.exists() and p.stat().st_size == 1
    assert entered[1] - entered[0] >= 0.10
    assert all(child.exitcode == 0 for child in children)


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX crash release test")
def test_lock_releases_after_abnormal_process_exit(tmp_path):
    p = tmp_path / "crash.lock"
    p.write_bytes(b"0")
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    child = ctx.Process(target=_crash_worker, args=(p, ready))
    child.start()
    assert ready.wait(3)
    child.join(3)
    assert child.exitcode == 7
    with CrossProcessFileLock.open_existing(p, timeout_ms=1000):
        pass
