import multiprocessing

import pytest

from cs2pov.storage.cross_process_lock import CrossProcessFileLock
from cs2pov.storage.job_errors import JobRepositoryError


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
