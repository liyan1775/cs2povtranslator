"""Tests for error taxonomy."""

from __future__ import annotations

import re

import pytest

from cs2tl.errors import (
    CS2tlError,
    clock_sync_overflow,
    clock_sync_warning,
    config_invalid_yaml,
    config_missing_key,
    config_not_found,
    dictionary_clone_failed,
    dictionary_yaml_error,
    exit_with_error,
    extractor_failed,
    extractor_not_found,
    invalid_map_name,
    llm_auth_failed,
    llm_rate_limited,
    llm_response_malformed,
    no_voice_data,
    round_detection_failed,
    subtitle_encoding_failed,
    subtitle_write_failed,
    whisper_model_download_failed,
    whisper_transcription_failed,
)


class TestCS2tlError:
    def test_format_includes_code_and_sections(self):
        err = CS2tlError("E0-0000", "Test message", "Test cause", "Test fix")
        text = str(err)
        assert "[CS2TL-E0-0000]" in text
        assert "Test message" in text
        assert "Cause:" in text
        assert "Test cause" in text
        assert "Fix:" in text
        assert "Test fix" in text

    def test_error_code_pattern(self):
        """Every error code must match [CS2TL-E{N}-{NNNN}]."""
        pattern = re.compile(r"\[CS2TL-E\d-\d{4}\]")
        err = CS2tlError("E1-0001", "msg", "cause", "fix")
        assert pattern.search(str(err))

    def test_exit_with_error_writes_to_stderr(self, capsys):
        err = CS2tlError("E9-9999", "Fatal", "Something broke", "Fix it")
        with pytest.raises(SystemExit) as exc_info:
            exit_with_error(err, exit_code=42)
        assert exc_info.value.code == 42
        captured = capsys.readouterr()
        assert "[CS2TL-E9-9999]" in captured.err


class TestAllConstructors:
    """Verify every constructor produces a valid error code."""

    PATTERN = re.compile(r"\[CS2TL-E\d-\d{4}\]")

    def _check(self, err: CS2tlError, expected_prefix: str):
        assert err.code.startswith(expected_prefix)
        assert self.PATTERN.search(str(err))
        assert err.message
        assert err.cause
        assert err.fix

    def test_e1_extractor(self):
        self._check(extractor_not_found("csgove"), "E1-")
        self._check(extractor_failed("test.dem", "panic"), "E1-")
        self._check(no_voice_data("test.dem"), "E1-")

    def test_e2_transcriber(self):
        self._check(whisper_model_download_failed("base", "timeout"), "E2-")
        self._check(whisper_transcription_failed("x.wav", "OOM"), "E2-")

    def test_e3_dictionary(self):
        self._check(dictionary_clone_failed("https://x", "timeout"), "E3-")
        self._check(dictionary_yaml_error("dust2", "bad indent"), "E3-")
        self._check(invalid_map_name("../../etc", ["de_dust2"]), "E3-")

    def test_e4_round(self):
        self._check(round_detection_failed("test.dem", "no events"), "E4-")

    def test_e5_translator(self):
        self._check(llm_auth_failed("401"), "E5-")
        self._check(llm_rate_limited("60"), "E5-")
        self._check(llm_response_malformed("missing json"), "E5-")

    def test_e6_subtitles(self):
        self._check(subtitle_write_failed("out.srt", "disk full"), "E6-")
        self._check(subtitle_encoding_failed("\U0001f600"), "E6-")

    def test_e7_config(self):
        self._check(config_not_found("~/.cs2tl/config.yml"), "E7-")
        self._check(config_invalid_yaml("config.yml", "tab char"), "E7-")
        self._check(config_missing_key("config.yml", "llm.api_key"), "E7-")

    def test_e8_clock(self):
        self._check(clock_sync_overflow(15.0, 10.0), "E8-")
        warning = clock_sync_warning(3.5)
        assert "3.5" in warning
        assert isinstance(warning, str)
