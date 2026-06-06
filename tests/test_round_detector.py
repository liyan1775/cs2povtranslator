"""Tests for round_detector module."""

from __future__ import annotations

from cs2tl.round_detector import (
    RoundBoundary,
    _median,
    halftime_swap,
)
from cs2tl.transcriber import PartialSegment


class TestMedian:
    def test_odd_length(self):
        assert _median([1.0, 2.0, 3.0]) == 2.0

    def test_even_length(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_single_value(self):
        assert _median([5.0]) == 5.0

    def test_empty(self):
        assert _median([]) == 0.0


class TestHalftimeSwap:
    def _make_seg(self, round_num: int, team: str) -> PartialSegment:
        seg = PartialSegment(
            steam_id="sid1",
            start_time=float(round_num * 30),
            end_time=float(round_num * 30 + 5),
            text="test",
            confidence=0.9,
        )
        seg.round_number = round_num  # type: ignore
        seg.team = team  # type: ignore
        return seg

    def test_flips_t_to_ct_after_round_12(self):
        rounds = [RoundBoundary(i, float(i * 120), float(i * 120 + 100), {}) for i in range(1, 25)]
        segs = [
            self._make_seg(10, "T"),
            self._make_seg(15, "T"),
        ]
        halftime_swap(segs, rounds)
        assert segs[0].team == "T"  # unchanged, round < 13
        assert segs[1].team == "CT"  # flipped, round >= 13

    def test_flips_ct_to_t_after_round_12(self):
        rounds = [RoundBoundary(i, float(i * 120), float(i * 120 + 100), {}) for i in range(1, 25)]
        segs = [
            self._make_seg(6, "CT"),
            self._make_seg(18, "CT"),
        ]
        halftime_swap(segs, rounds)
        assert segs[0].team == "CT"
        assert segs[1].team == "T"

    def test_no_swap_for_round_12(self):
        rounds = [RoundBoundary(i, float(i * 120), float(i * 120 + 100), {}) for i in range(1, 13)]
        segs = [self._make_seg(12, "T")]
        halftime_swap(segs, rounds)
        assert segs[0].team == "T"  # boundary: round 12 not flipped

    def test_unknown_teams_unchanged(self):
        rounds = [RoundBoundary(i, float(i * 120), float(i * 120 + 100), {}) for i in range(1, 25)]
        segs = [self._make_seg(15, "unknown")]
        halftime_swap(segs, rounds)
        assert segs[0].team == "unknown"

    def test_no_round_number_preserved(self):
        rounds = [RoundBoundary(i, float(i * 120), float(i * 120 + 100), {}) for i in range(1, 25)]
        seg = self._make_seg(20, "T")
        seg.round_number = None
        halftime_swap([seg], rounds)
        assert seg.team == "T"
