from __future__ import annotations

import ctypes


class OpusDecoderError(RuntimeError):
    pass


class PyOggOpusDecoder:
    """Small ctypes wrapper over PyOgg's libopus handle.

    PyOgg versions differ in what they export. This wrapper intentionally uses
    pyogg.opus.libopus because PyOgg 0.6.14a1 does not expose
    `opus_decoder_create` as a direct Python symbol.
    """

    def __init__(self, sample_rate: int = 24_000, channels: int = 1, max_samples: int = 5760):
        try:
            from pyogg import opus  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise OpusDecoderError("缺少 PyOgg。请运行：pip install pyogg") from exc

        self.sample_rate = sample_rate
        self.channels = channels
        self.max_samples = max_samples
        self.lib = opus.libopus
        self._configure_ctypes()
        err = ctypes.c_int()
        self.decoder = self.lib.opus_decoder_create(sample_rate, channels, ctypes.byref(err))
        if not self.decoder:
            raise OpusDecoderError(f"opus_decoder_create failed: {err.value}")
        self._pcm_buf = (ctypes.c_short * max_samples)()

    def _configure_ctypes(self) -> None:
        self.lib.opus_decoder_create.argtypes = [ctypes.c_int32, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.lib.opus_decoder_create.restype = ctypes.c_void_p
        self.lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        self.lib.opus_decoder_destroy.restype = None
        self.lib.opus_decode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_short),
            ctypes.c_int,
            ctypes.c_int,
        ]
        self.lib.opus_decode.restype = ctypes.c_int

    def decode(self, packet: bytes) -> bytes:
        raw = (ctypes.c_ubyte * len(packet))(*packet)
        samples = self.lib.opus_decode(self.decoder, raw, len(packet), self._pcm_buf, self.max_samples, 0)
        if samples <= 0:
            return b""
        return bytes(ctypes.string_at(ctypes.cast(self._pcm_buf, ctypes.c_void_p), samples * self.channels * 2))

    def close(self) -> None:
        if getattr(self, "decoder", None):
            self.lib.opus_decoder_destroy(self.decoder)
            self.decoder = None

    def __enter__(self) -> "PyOggOpusDecoder":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
