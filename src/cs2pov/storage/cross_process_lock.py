from __future__ import annotations

import errno
import os
import stat
import time
from pathlib import Path

from .job_errors import JobRepositoryError


_HELD: set[str] = set()


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            count = os.write(fd, payload[offset:])
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            raise
        if count <= 0:
            raise OSError(errno.EIO, "zero-progress write")
        offset += count


def _error(code: str, message: str, path: Path, cause: BaseException | None = None):
    exc = JobRepositoryError(code, message, "请稍后重试或检查仓储锁。", path.name)
    if cause is not None:
        exc.__cause__ = cause
    return exc


class _LockedContext:
    def __init__(self, path: Path, timeout_ms: int, bootstrap: bool) -> None:
        self.path = Path(path)
        self.timeout_ms = timeout_ms
        self.bootstrap = bootstrap
        self._file = None
        self._key = None

    def __enter__(self):
        if type(self.timeout_ms) is not int or self.timeout_ms < 0:
            raise _error("job_write_failed", "锁超时时间无效。", self.path)
        self._validate_parent()
        key = os.path.normcase(str(self.path.absolute()))
        if key in _HELD:
            raise _error("job_write_busy", "当前进程重复获取同一写锁。", self.path)
        try:
            self._file = self._open_descriptor()
        except OSError as exc:
            raise _error("job_write_failed", "无法打开仓储锁。", self.path, exc) from exc
        try:
            self._validate_descriptor(require_nonempty=False)
            if self.bootstrap and os.fstat(self._file.fileno()).st_size == 0:
                _write_all(self._file.fileno(), b"0")
                os.fsync(self._file.fileno())
            self._validate_descriptor()
            self._acquire()
            self._validate_descriptor()
        except BaseException:
            self._file.close()
            self._file = None
            raise
        _HELD.add(key)
        self._key = key
        return self

    @property
    def file(self):
        return self._file

    def _validate_parent(self) -> None:
        current = self.path.parent
        while True:
            try:
                st = os.lstat(current)
            except FileNotFoundError:
                current = current.parent
                if current == current.parent:
                    break
                continue
            attrs = getattr(st, "st_file_attributes", 0)
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if stat.S_ISLNK(st.st_mode) or bool(attrs & reparse) or not stat.S_ISDIR(st.st_mode):
                raise _error("job_write_failed", "仓储锁父目录不能是链接。", self.path)
            if current == current.parent:
                break
            current = current.parent

    def _open_descriptor(self):
        flags = os.O_RDWR
        if self.bootstrap:
            flags |= os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            handle = os.fdopen(os.open(self.path, flags, 0o600), "r+b", buffering=0)
        except FileNotFoundError as exc:
            raise _error("job_write_failed", "仓储锁不存在。", self.path, exc) from exc
        st = os.fstat(handle.fileno())
        attrs = getattr(st, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(st.st_mode) or bool(attrs & reparse) or not stat.S_ISREG(st.st_mode):
            handle.close()
            raise _error("job_write_failed", "仓储锁必须是普通文件。", self.path)
        return handle

    def _validate_descriptor(self, *, require_nonempty: bool = True) -> None:
        st = os.fstat(self._file.fileno())
        attrs = getattr(st, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if not stat.S_ISREG(st.st_mode) or bool(attrs & reparse) or (require_nonempty and st.st_size < 1):
            raise _error("job_write_failed", "仓储锁描述符无效。", self.path)
        try:
            current = os.lstat(self.path)
        except OSError as exc:
            raise _error("job_write_interrupted", "仓储锁路径在校验期间发生变化。", self.path, exc) from exc
        if stat.S_ISLNK(current.st_mode) or bool(getattr(current, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)) or (st.st_dev, st.st_ino) != (current.st_dev, current.st_ino):
            raise _error("job_write_interrupted", "仓储锁在打开期间发生变化。", self.path)

    def _acquire(self) -> None:
        deadline = time.monotonic() + self.timeout_ms / 1000
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                    return
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise _error("job_write_busy", "仓储锁正被其他进程占用。", self.path, exc) from exc
                    time.sleep(0.005)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EINTR):
                        raise _error("job_write_failed", "获取仓储锁失败。", self.path, exc) from exc
                    if time.monotonic() >= deadline:
                        raise _error("job_write_busy", "仓储锁正被其他进程占用。", self.path, exc) from exc
                    time.sleep(0.005)

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._file is not None:
                if os.name == "nt":
                    import msvcrt

                    self._file.seek(0)
                    try:
                        msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl

                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
        finally:
            if self._key is not None:
                _HELD.discard(self._key)
            self._file = None
            self._key = None


class CrossProcessFileLock:
    @classmethod
    def open_existing(cls, path: Path, *, timeout_ms: int):
        return _LockedContext(path, timeout_ms, False)

    @classmethod
    def bootstrap_for_write(cls, path: Path, *, timeout_ms: int):
        return _LockedContext(path, timeout_ms, True)


LockedFile = _LockedContext
