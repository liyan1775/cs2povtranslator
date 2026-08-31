from __future__ import annotations

import io
from pathlib import Path

import pytest
import zstandard

from cs2pov.adapters.demoparser_adapter import DemoparserAdapter
from cs2pov.adapters.zstandard_adapter import DemoCompressionError, ZstandardDemoAdapter


def test_iter_decompressed_yields_original_bytes_in_bounded_chunks():
    original = (b"anonymous-cs2-demo" * 8192) + b"end"
    compressed = zstandard.ZstdCompressor(level=3).compress(original)

    chunks = list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(compressed), chunk_size=4096))

    assert b"".join(chunks) == original
    assert chunks
    assert all(0 < len(chunk) <= 4096 for chunk in chunks)


def test_iter_decompressed_handles_complete_unknown_content_size_frame():
    original = b"anonymous-unknown-size-demo" * 256
    compressed = zstandard.ZstdCompressor(write_content_size=False).compress(original)

    chunks = list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(compressed), chunk_size=4096))

    assert b"".join(chunks) == original


@pytest.mark.parametrize("trim", [1, 3, 10])
def test_iter_decompressed_rejects_any_truncated_unknown_content_size_frame(trim):
    compressed = zstandard.ZstdCompressor(write_content_size=False).compress(b"anonymous-demo" * 256)

    with pytest.raises(DemoCompressionError):
        list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(compressed[:-trim]), chunk_size=4096))


def test_iter_decompressed_never_requests_unbounded_source_reads():
    original = b"anonymous-tracking-demo" * 1024
    compressed = zstandard.ZstdCompressor().compress(original)

    class TrackingReader(io.BytesIO):
        requests: list[int] = []

        def read(self, size=-1):
            self.requests.append(size)
            assert 0 <= size <= 256 * 1024
            return super().read(size)

    source = TrackingReader(compressed)
    chunks = list(ZstandardDemoAdapter().iter_decompressed(source, chunk_size=4096))

    assert b"".join(chunks) == original
    assert source.requests


def test_iter_decompressed_accepts_a_valid_empty_frame():
    compressed = zstandard.ZstdCompressor().compress(b"")

    assert list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(compressed), chunk_size=8)) == []


@pytest.mark.parametrize("data", [b"not zstandard", b"\x00\x01\x02"])
def test_iter_decompressed_maps_corrupt_stream_to_stable_error(data):
    with pytest.raises(DemoCompressionError) as caught:
        list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(data), chunk_size=8))

    assert "not zstandard" not in str(caught.value)
    assert "\\" not in str(caught.value)


def test_iter_decompressed_maps_truncated_stream_to_stable_error():
    compressed = zstandard.ZstdCompressor().compress(b"anonymous-demo" * 100)

    with pytest.raises(DemoCompressionError):
        list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(compressed[:-1]), chunk_size=8))


@pytest.mark.parametrize("chunk_size", [True, False, 0, -1])
def test_iter_decompressed_rejects_invalid_chunk_size(chunk_size):
    with pytest.raises(ValueError):
        list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(b""), chunk_size=chunk_size))


def test_iter_decompressed_rejects_source_without_read_method():
    class NoReader:
        pass

    with pytest.raises(DemoCompressionError):
        list(ZstandardDemoAdapter().iter_decompressed(NoReader(), chunk_size=8))


def test_demoparser_adapter_keeps_zst_and_plain_copy_behavior(tmp_path: Path):
    original = b"anonymous-demo" * 100
    compressed_path = tmp_path / "source.dem.zst"
    compressed_path.write_bytes(zstandard.ZstdCompressor().compress(original))
    plain_path = tmp_path / "source.dem"
    plain_path.write_bytes(original)

    compressed_target = tmp_path / "decoded" / "compressed.dem"
    plain_target = tmp_path / "decoded" / "plain.dem"
    adapter = DemoparserAdapter()

    assert adapter.decompress_if_needed(compressed_path, compressed_target) == compressed_target
    assert compressed_target.read_bytes() == original
    assert adapter.decompress_if_needed(plain_path, plain_target) == plain_target
    assert plain_target.read_bytes() == original
