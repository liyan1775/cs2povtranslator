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
