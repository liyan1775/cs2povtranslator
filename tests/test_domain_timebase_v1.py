from __future__ import annotations
import pytest
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.schema import MAX_DEMO_TIME_US
from cs2pov.domain.timebase import (
    SourceClock,
    TimeAnchor,
    TimeRange,
    demo_to_round_local_us,
    map_source_range,
    to_export_milliseconds,
)


def _audio_anchor(i, s, e, d):
    return TimeAnchor(
        i,
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        s,
        e,
        TimeRange(d, d + 1_000_000),
        16_000,
        "synthetic-voice-extractor-v1",
    )


def test_time_range_is_non_negative_non_empty_and_half_open():
    v = TimeRange(1_000_000, 2_000_000)
    assert (
        v.duration_us == 1_000_000
        and v.contains(1_000_000)
        and v.contains(1_999_999)
        and not v.contains(2_000_000)
    )
    for s, e in ((-1, 1), (1, 1), (2, 1)):
        with pytest.raises(DomainSchemaError) as x:
            TimeRange(s, e)
        assert x.value.code == "time_range_invalid"


def test_discontinuous_compact_audio_maps_to_two_demo_segments():
    a = map_source_range(
        (
            _audio_anchor("anchor-a", 0, 24000, 10000000),
            _audio_anchor("anchor-b", 24000, 48000, 20000000),
        ),
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        18000,
        30000,
    )
    assert (
        a.segments == (TimeRange(10750000, 11000000), TimeRange(20000000, 20250000))
        and a.anchor_ids == ("anchor-a", "anchor-b")
        and a.uncertainty_us == 16000
        and not a.is_contiguous
        and a.envelope == TimeRange(10750000, 20250000)
    )


@pytest.mark.parametrize(
    "clock,stream,s,e,d,ms,me",
    [
        (SourceClock.DEMO_TICK, "demo", 640, 704, 10000000, 672, 704),
        (SourceClock.VIDEO_FRAME, "render-main", 0, 30, 20000000, 15, 30),
    ],
)
def test_tick_and_video_frame_clocks_use_same_mapping(clock, stream, s, e, d, ms, me):
    a = TimeAnchor(
        "anchor-" + clock.value,
        clock,
        stream,
        s,
        e,
        TimeRange(d, d + 1000000),
        0,
        "synthetic-clock-v1",
    )
    m = map_source_range((a,), clock, stream, ms, me)
    assert m.segments == (TimeRange(d + 500000, d + 1000000),) and m.is_contiguous


def test_anchor_mapping_rejects_gaps_and_wrong_streams():
    a = (_audio_anchor("anchor-a", 0, 24000, 10000000),)
    for stream, s, e in (
        ("player-bravo", 0, 1000),
        ("player-alpha", 24000, 25000),
        ("player-alpha", 20000, 25000),
    ):
        with pytest.raises(DomainSchemaError) as x:
            map_source_range(a, SourceClock.COMPACT_AUDIO_SAMPLE, stream, s, e)
        assert x.value.code == "time_anchor_gap"


@pytest.mark.parametrize("second", [5000000, 10500000])
def test_anchor_sequence_rejects_reversal_overlap(second):
    with pytest.raises(DomainSchemaError) as x:
        map_source_range(
            (
                _audio_anchor("anchor-a", 0, 24000, 10000000),
                _audio_anchor("anchor-b", 24000, 48000, second),
            ),
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-alpha",
            0,
            48000,
        )
    assert x.value.code == "time_anchor_invalid"


def test_anchor_round_trip():
    a = _audio_anchor("anchor-a", 0, 24000, 10000000)
    p = a.to_dict()
    assert (
        p["schema_version"] == 1
        and p["demo_start_us"] == 10000000
        and TimeAnchor.from_dict(p) == a
    )
    p["unexpected"] = True
    with pytest.raises(DomainSchemaError) as x:
        TimeAnchor.from_dict(p)
    assert x.value.code == "domain_schema_invalid"


def test_uncertainty_bounded():
    with pytest.raises(DomainSchemaError) as x:
        TimeAnchor(
            "x",
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-alpha",
            0,
            24000,
            TimeRange(10000000, 11000000),
            MAX_DEMO_TIME_US + 1,
            "synthetic",
        )
    assert x.value.code == "domain_field_invalid"


def test_round_local_and_export_rounding():
    r = TimeRange(10000000, 20000000)
    assert demo_to_round_local_us(10750000, r) == 750000 and to_export_milliseconds(
        TimeRange(10000001, 10001001)
    ) == (10000, 10002)
    with pytest.raises(DomainSchemaError) as x:
        demo_to_round_local_us(20000000, r)
    assert x.value.code == "time_outside_round"


def test_mapped_time_rejects_empty_and_misaligned_segments():
    with pytest.raises(DomainSchemaError):
        from cs2pov.domain.timebase import MappedTime

        MappedTime((), (), 0)


def test_private_scan_rejects_tilde_backslash_path():
    from cs2pov.domain.schema import reject_private_data

    with pytest.raises(DomainSchemaError):
        reject_private_data({"value": "~\\private\\demo.dem"}, "document")


def test_canonical_json_rejects_non_string_keys():
    from cs2pov.domain.fingerprint import canonical_json_bytes

    with pytest.raises(DomainSchemaError):
        canonical_json_bytes({1: "one", "1": "string"})
