from __future__ import annotations

from typing import BinaryIO, Iterator

import zstandard

_MAX_SOURCE_READ = 256 * 1024


class DemoCompressionError(RuntimeError):
    """The compressed Demo stream could not be decoded."""


class _ValidatingSource:
    def __init__(self, source: BinaryIO) -> None:
        self._source = source
        self._validator = zstandard.ZstdDecompressor().decompressobj()

    def read(self, size: int = -1) -> bytes:
        request = _MAX_SOURCE_READ if size < 0 else min(size, _MAX_SOURCE_READ)
        data = self._source.read(request)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("source.read() 必须返回 bytes。")
        data = bytes(data)
        if data:
            self._validator.decompress(data)
        elif not self._validator.eof:
            raise DemoCompressionError("zstandard demo 解压失败。")
        return data


class ZstandardDemoAdapter:
    def iter_decompressed(
        self, source: BinaryIO, *, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]:
        if type(chunk_size) is not int or chunk_size <= 0:
            raise ValueError("chunk_size 必须是正整数。")
        try:
            reader = zstandard.ZstdDecompressor().stream_reader(_ValidatingSource(source))
            with reader:
                while True:
                    chunk = reader.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except Exception as exc:
            if isinstance(exc, DemoCompressionError):
                raise
            raise DemoCompressionError("zstandard demo 解压失败。") from exc
