from __future__ import annotations
import pytest
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.timeline import (
    DemoDescriptor,
    DemoTimeline,
    PlayerSnapshot,
    Round,
    RoundBoundaryConfidence,
    RoundCollection,
    MatchPhase,
)


def _round(i, n, s, e):
    return Round(
        i,
        n,
        TimeRange(s, e),
        None,
        None,
        MatchPhase.REGULATION_FIRST_HALF,
        "synthetic-round-parser-v1",
        RoundBoundaryConfidence.EXACT,
        0,
    )


def _descriptor():
    return DemoDescriptor(
        "a" * 64,
        "de_mirage",
        "fixture-server",
        64,
        1,
        (
            PlayerSnapshot("player-alpha", "Alpha", 2),
            PlayerSnapshot("player-bravo", "Bravo", 2),
        ),
    )


def test_demo_and_round_documents_round_trip_without_float_time():
    d = _descriptor()
    r = RoundCollection(
        (
            _round("round-001", 1, 10000000, 20000000),
            _round("round-002", 2, 20000000, 30000000),
        )
    )
    dp = d.to_dict()
    rp = r.to_dict()
    assert (
        dp["schema_version"] == 1
        and rp["schema_version"] == 1
        and "start_time" not in str(rp)
        and DemoDescriptor.from_dict(dp) == d
        and RoundCollection.from_dict(rp) == r
    )


def test_demo_rejects_private_absolute_location_in_direct_and_decoded_values():
    with pytest.raises(DomainSchemaError) as e:
        DemoDescriptor("a" * 64, "de_mirage", r"C:\private\demo.dem", 64, 1, ())
    assert e.value.code == "domain_private_data_forbidden"
    p = _descriptor().to_dict()
    p["server_name"] = "/home/private/demo.dem"
    with pytest.raises(DomainSchemaError) as e:
        DemoDescriptor.from_dict(p)
    assert e.value.code == "domain_private_data_forbidden"


def test_round_ids_and_player_ids_are_unique():
    with pytest.raises(DomainSchemaError) as e:
        DemoDescriptor(
            "a" * 64,
            "de_mirage",
            None,
            64,
            1,
            (
                PlayerSnapshot("player-alpha", "Alpha", 2),
                PlayerSnapshot("player-alpha", "Alias", 2),
            ),
        )
    assert e.value.code == "player_reference_invalid"
    with pytest.raises(DomainSchemaError) as e:
        RoundCollection(
            (
                _round("round-001", 1, 10000000, 20000000),
                _round("round-001", 2, 20000000, 30000000),
            )
        )
    assert e.value.code == "round_reference_invalid"


def test_rounds_must_be_ordered_and_non_overlapping():
    with pytest.raises(DomainSchemaError) as e:
        RoundCollection(
            (
                _round("round-001", 1, 10000000, 21000000),
                _round("round-002", 2, 20000000, 30000000),
            )
        )
    assert e.value.code == "round_reference_invalid"


def test_half_open_boundary_assigns_exact_end_to_next_round():
    t = DemoTimeline(
        _descriptor(),
        RoundCollection(
            (
                _round("round-001", 1, 10000000, 20000000),
                _round("round-002", 2, 20000000, 30000000),
            )
        ),
        (),
    )
    assert (
        t.round_for_time(19999999).round_id == "round-001"
        and t.round_for_time(20000000).round_id == "round-002"
        and t.round_for_time(30000000) is None
    )


def test_anchor_stream_must_refer_to_known_player_or_demo_stream():
    a = TimeAnchor(
        "anchor-a",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-missing",
        0,
        24000,
        TimeRange(10000000, 11000000),
        16000,
        "synthetic-voice-extractor-v1",
    )
    with pytest.raises(DomainSchemaError) as e:
        DemoTimeline(
            _descriptor(),
            RoundCollection((_round("round-001", 1, 10000000, 20000000),)),
            (a,),
        )
    assert e.value.code == "time_anchor_invalid"


def test_exact_tick_boundaries_must_map_to_declared_demo_range():
    a = TimeAnchor(
        "anchor-demo-ticks",
        SourceClock.DEMO_TICK,
        "demo",
        640,
        1280,
        TimeRange(10000000, 20000000),
        0,
        "synthetic-round-parser-v1",
    )
    r = Round(
        "round-001",
        1,
        TimeRange(10000000, 20000000),
        640,
        1200,
        MatchPhase.REGULATION_FIRST_HALF,
        "synthetic-round-parser-v1",
        RoundBoundaryConfidence.EXACT,
        0,
    )
    with pytest.raises(DomainSchemaError) as e:
        DemoTimeline(_descriptor(), RoundCollection((r,)), (a,))
    assert e.value.code == "round_reference_invalid"


def test_estimated_tick_boundary_may_differ_only_within_declared_uncertainty():
    a = TimeAnchor(
        "anchor-demo-ticks",
        SourceClock.DEMO_TICK,
        "demo",
        640,
        1280,
        TimeRange(10000000, 20000000),
        0,
        "synthetic-round-parser-v1",
    )

    def r(u):
        return Round(
            "round-001",
            1,
            TimeRange(10000000, 20000000),
            640,
            1279,
            MatchPhase.REGULATION_FIRST_HALF,
            "synthetic-round-parser-v1",
            RoundBoundaryConfidence.ESTIMATED,
            u,
        )

    DemoTimeline(_descriptor(), RoundCollection((r(20000),)), (a,))
    with pytest.raises(DomainSchemaError) as e:
        DemoTimeline(_descriptor(), RoundCollection((r(10000),)), (a,))
    assert e.value.code == "round_reference_invalid"


def test_ticks_require_demo_anchor_and_rounds_display_numbers_ascending():
    r = _round("round-001", 2, 10000000, 20000000)
    with pytest.raises(DomainSchemaError):
        RoundCollection((r, _round("round-000", 1, 20000000, 25000000)))
    with pytest.raises(DomainSchemaError):
        DemoTimeline(
            _descriptor(),
            RoundCollection(
                (
                    Round(
                        "round-001",
                        1,
                        TimeRange(10000000, 20000000),
                        640,
                        1280,
                        MatchPhase.REGULATION_FIRST_HALF,
                        "synthetic-round-parser-v1",
                        RoundBoundaryConfidence.EXACT,
                        0,
                    ),
                )
            ),
            (),
        )


def test_round_for_time_rejects_non_integer():
    t = DemoTimeline(
        _descriptor(),
        RoundCollection((_round("round-001", 1, 10000000, 20000000),)),
        (),
    )
    with pytest.raises(DomainSchemaError):
        t.round_for_time(1.5)


def test_direct_collections_are_defensively_tupled_and_types_validated():
    d = DemoDescriptor(
        "a" * 64,
        "de_mirage",
        "fixture-server",
        64,
        1,
        [PlayerSnapshot("player-alpha", "Alpha", 2)],
    )
    assert isinstance(d.players, tuple)
    with pytest.raises(DomainSchemaError):
        DemoDescriptor("a" * 64, "de_mirage", None, 64, 1, ["bad"])


def test_non_array_public_inputs_raise_domain_error():
    for call in (
        lambda: DemoDescriptor.from_dict({"players": 123}),
        lambda: RoundCollection.from_dict({"rounds": 123}),
        lambda: DemoDescriptor("a" * 64, "de_mirage", None, 64, 1, 123),
        lambda: RoundCollection(123),
        lambda: DemoTimeline(_descriptor(), RoundCollection(()), 123),
    ):
        with pytest.raises(DomainSchemaError):
            call()
