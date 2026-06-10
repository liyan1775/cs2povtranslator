from cs2pov.adapters.demoparser_adapter import _clean_round_candidates
from cs2pov.domain.models import Round


def test_clean_round_candidates_drops_startup_restart_preamble_and_renumbers():
    raw = [
        Round(1, 0.0, 47.0, source="demoparser2:round_start_raw"),
        Round(2, 47.0, 54.5, source="demoparser2:round_start_raw"),
        Round(3, 54.5, 56.3, source="demoparser2:round_start_raw"),
        Round(4, 56.3, 119.0, source="demoparser2:round_start_raw"),
        Round(5, 119.0, 204.0, source="demoparser2:round_start_raw"),
    ]

    cleaned = _clean_round_candidates(raw, min_duration_seconds=10.0)

    assert [r.round_number for r in cleaned] == [1, 2]
    assert [(r.start_time, r.end_time) for r in cleaned] == [(56.3, 119.0), (119.0, 204.0)]
    assert all(r.source == "demoparser2:round_start_cleaned" for r in cleaned)


def test_clean_round_candidates_filters_warmup():
    raw = [
        Round(1, 0.0, 60.0, is_warmup=True, source="demoparser2:round_start_raw"),
        Round(2, 60.0, 130.0, source="demoparser2:round_start_raw"),
    ]

    cleaned = _clean_round_candidates(raw, min_duration_seconds=10.0)

    assert len(cleaned) == 1
    assert cleaned[0].round_number == 1
    assert cleaned[0].start_time == 60.0


def test_clean_round_candidates_keeps_normal_short_free_start():
    raw = [
        Round(1, 20.0, 70.0, source="demoparser2:round_start_raw"),
        Round(2, 70.0, 130.0, source="demoparser2:round_start_raw"),
    ]

    cleaned = _clean_round_candidates(raw, min_duration_seconds=10.0)

    assert [(r.start_time, r.end_time) for r in cleaned] == [(20.0, 70.0), (70.0, 130.0)]
