from __future__ import annotations

from typing import BinaryIO, Iterator

import zstandard


class DemoCompressionError(RuntimeError):
    """The compressed Demo stream could not be decoded."""


class _ReplaySource:
    def __init__(self, prefix: bytes, source: BinaryIO) -> None:
        self._prefix = memoryview(prefix)
        self._source = source

    def read(self, size: int = -1) -> bytes:
        if not self._prefix:
            return self._source.read(size)
        if size < 0 or size >= len(self._prefix):
            prefix = self._prefix.tobytes()
            self._prefix = self._prefix[len(self._prefix):]
            remainder = size - len(prefix) if size >= 0 else -1
            return prefix + self._source.read(remainder)
        prefix = self._prefix[:size].tobytes()
        self._prefix = self._prefix[size:]
        return prefix


class ZstandardDemoAdapter:
    def iter_decompressed(
        self, source: BinaryIO, *, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]:
        if type(chunk_size) is not int or chunk_size <= 0:
            raise ValueError("chunk_size 必须是正整数。")
        try:
            prefix = source.read(64)
            if not isinstance(prefix, (bytes, bytearray, memoryview)):
                raise TypeError("source.read() 必须返回 bytes。")
            prefix = bytes(prefix)
            replay_source = _ReplaySource(prefix, source)
            expected_size: int | None = None
            try:
                frame_size = zstandard.frame_content_size(prefix)
                if frame_size not in (zstandard.CONTENTSIZE_UNKNOWN, zstandard.CONTENTSIZE_ERROR):
                    expected_size = frame_size
            except zstandard.ZstdError:
                pass
            reader = zstandard.ZstdDecompressor().stream_reader(replay_source)
            actual_size = 0
            with reader:
                while True:
                    chunk = reader.read(chunk_size)
                    if not chunk:
                        break
                    actual_size += len(chunk)
                    yield chunk
            if expected_size is None:
                try:
                    zstandard.get_frame_parameters(prefix)
                except zstandard.ZstdError as exc:
                    raise DemoCompressionError("zstandard demo 解压失败。") from exc
            elif actual_size < expected_size:
                raise DemoCompressionError("zstandard demo 解压失败。")
        except Exception as exc:
            if isinstance(exc, DemoCompressionError):
                raise
            raise DemoCompressionError("zstandard demo 解压失败。") from exc
