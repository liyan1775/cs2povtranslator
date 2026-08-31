from __future__ import annotations

from typing import BinaryIO, Iterator

import zstandard

_MAX_SOURCE_READ = 256 * 1024
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_SKIPPABLE_MAGIC_SUFFIX = b"\x2a\x4d\x18"


class DemoCompressionError(RuntimeError):
    """The compressed Demo stream could not be decoded."""


class _ZstdFrameScanner:
    """Validate compressed frame boundaries without materializing output."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._state = "magic"
        self._need = 4
        self._payload_remaining = 0
        self._after_payload_state = "magic"
        self._after_payload_need = 4
        self._checksum_remaining = 0
        self._has_checksum = False
        self._seen_frame = False

    def feed(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            if self._payload_remaining:
                consumed = min(len(view), self._payload_remaining)
                self._payload_remaining -= consumed
                view = view[consumed:]
                if self._payload_remaining == 0:
                    self._state = self._after_payload_state
                    self._need = self._after_payload_need
                    if self._after_payload_state == "magic":
                        self._seen_frame = True
                continue

            needed = self._need - len(self._buffer)
            consumed = min(len(view), needed)
            self._buffer.extend(view[:consumed])
            view = view[consumed:]
            if len(self._buffer) < self._need:
                continue
            chunk = bytes(self._buffer)
            self._buffer.clear()
            self._parse_complete(chunk)

    def finish(self) -> None:
        if not self._seen_frame or self._state != "magic" or self._buffer:
            raise DemoCompressionError("zstandard demo 解压失败。")

    def _parse_complete(self, chunk: bytes) -> None:
        if self._state == "magic":
            if chunk == _ZSTD_MAGIC:
                self._state = "fhd"
                self._need = 1
                return
            if len(chunk) == 4 and 0x50 <= chunk[0] <= 0x5f and chunk[1:] == _SKIPPABLE_MAGIC_SUFFIX:
                self._state = "skip_size"
                self._need = 4
                return
            raise DemoCompressionError("zstandard demo 解压失败。")

        if self._state == "skip_size":
            self._payload_remaining = int.from_bytes(chunk, "little")
            self._seen_frame = True
            self._after_payload_state = "magic"
            self._after_payload_need = 4
            if self._payload_remaining == 0:
                self._state = "magic"
                self._need = 4
            return

        if self._state == "fhd":
            fhd = chunk[0]
            if fhd & 0x08:
                raise DemoCompressionError("zstandard demo 解压失败。")
            fcs_flag = fhd >> 6
            single_segment = bool(fhd & 0x20)
            dictionary_flag = fhd & 0x03
            window_size = 0 if single_segment else 1
            dictionary_size = (0, 1, 2, 4)[dictionary_flag]
            content_size = (1 if single_segment else 0, 2, 4, 8)[fcs_flag]
            self._has_checksum = bool(fhd & 0x04)
            self._state = "header_tail"
            self._need = window_size + dictionary_size + content_size
            if self._need == 0:
                self._state = "block_header"
                self._need = 3
            return

        if self._state == "header_tail":
            self._state = "block_header"
            self._need = 3
            return

        if self._state == "block_header":
            block_header = int.from_bytes(chunk, "little")
            block_type = (block_header >> 1) & 0x03
            if block_type == 3:
                raise DemoCompressionError("zstandard demo 解压失败。")
            block_size = block_header >> 3
            is_last = bool(block_header & 0x01)
            self._payload_remaining = 1 if block_type == 1 else block_size
            if is_last:
                self._checksum_remaining = 4 if self._has_checksum else 0
                if self._checksum_remaining:
                    self._after_payload_state = "checksum"
                    self._after_payload_need = self._checksum_remaining
                else:
                    self._after_payload_state = "magic"
                    self._after_payload_need = 4
            else:
                self._after_payload_state = "block_header"
                self._after_payload_need = 3
            if self._payload_remaining == 0:
                self._state = self._after_payload_state
                self._need = self._after_payload_need
                if is_last and not self._checksum_remaining:
                    self._seen_frame = True
            return

        if self._state == "checksum":
            self._checksum_remaining = 0
            self._seen_frame = True
            self._state = "magic"
            self._need = 4
            return

        raise DemoCompressionError("zstandard demo 解压失败。")


class _ValidatingSource:
    def __init__(self, source: BinaryIO) -> None:
        self._source = source
        self._scanner = _ZstdFrameScanner()

    def read(self, size: int = -1) -> bytes:
        request = _MAX_SOURCE_READ if size < 0 else min(size, _MAX_SOURCE_READ)
        data = self._source.read(request)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("source.read() 必须返回 bytes。")
        data = bytes(data)
        if data:
            self._scanner.feed(data)
        else:
            self._scanner.finish()
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
