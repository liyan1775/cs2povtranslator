from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from math import ceil
from .errors import DomainSchemaError
from .schema import *


def _bad(code, path="time", msg="时间值无效。"):
    raise DomainSchemaError(code, msg, "请修正后重试。", path)


@dataclass(frozen=True, slots=True)
class TimeRange:
    start_us: int
    end_us: int

    def __post_init__(self):
        try:
            require_int(self.start_us, "start_us", minimum=0, maximum=MAX_DEMO_TIME_US)
            require_int(self.end_us, "end_us", minimum=0, maximum=MAX_DEMO_TIME_US)
        except DomainSchemaError as e:
            raise DomainSchemaError(
                "time_range_invalid", e.message, e.action, e.path
            ) from e
        if self.end_us <= self.start_us:
            _bad("time_range_invalid")

    @property
    def duration_us(self):
        return self.end_us - self.start_us

    def contains(self, v):
        return self.start_us <= v < self.end_us


class SourceClock(Enum):
    DEMO_TICK = "demo_tick"
    COMPACT_AUDIO_SAMPLE = "compact_audio_sample"
    VIDEO_FRAME = "video_frame"


@dataclass(frozen=True, slots=True)
class TimeAnchor:
    anchor_id: str
    source_clock: SourceClock
    source_stream_id: str
    source_start: int
    source_end: int
    demo_range: TimeRange
    uncertainty_us: int
    provenance: str

    def __post_init__(self):
        if not isinstance(self.source_clock, SourceClock) or not isinstance(
            self.demo_range, TimeRange
        ):
            _bad("domain_field_invalid")
        require_identifier(self.anchor_id, "anchor_id")
        require_identifier(self.source_stream_id, "source_stream_id")
        require_identifier(self.provenance, "provenance")
        require_int(
            self.source_start, "source_start", minimum=0, maximum=MAX_SOURCE_POSITION
        )
        require_int(
            self.source_end, "source_end", minimum=0, maximum=MAX_SOURCE_POSITION
        )
        if self.source_end <= self.source_start:
            _bad("time_anchor_invalid", "source_end")
        require_int(
            self.uncertainty_us, "uncertainty_us", minimum=0, maximum=MAX_DEMO_TIME_US
        )
        reject_private_data(
            (
                self.__dict__
                if hasattr(self, "__dict__")
                else {
                    "anchor_id": self.anchor_id,
                    "source_stream_id": self.source_stream_id,
                    "provenance": self.provenance,
                }
            ),
            "anchor",
        )

    def to_dict(self):
        return {
            "schema_version": 1,
            "anchor_id": self.anchor_id,
            "source_clock": self.source_clock.value,
            "source_stream_id": self.source_stream_id,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "demo_start_us": self.demo_range.start_us,
            "demo_end_us": self.demo_range.end_us,
            "uncertainty_us": self.uncertainty_us,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data):
        d = require_mapping(data, "anchor")
        reject_private_data(d, "anchor")
        require_current_schema(d, "anchor")
        require_exact_keys(
            d,
            {
                "schema_version",
                "anchor_id",
                "source_clock",
                "source_stream_id",
                "source_start",
                "source_end",
                "demo_start_us",
                "demo_end_us",
                "uncertainty_us",
                "provenance",
            },
            set(),
            "anchor",
        )
        try:
            clock = SourceClock(require_str(d["source_clock"], "source_clock"))
        except ValueError as e:
            _bad("domain_field_invalid", "source_clock")
        return cls(
            require_identifier(d["anchor_id"], "anchor_id"),
            clock,
            require_identifier(d["source_stream_id"], "source_stream_id"),
            require_int(
                d["source_start"],
                "source_start",
                minimum=0,
                maximum=MAX_SOURCE_POSITION,
            ),
            require_int(
                d["source_end"], "source_end", minimum=0, maximum=MAX_SOURCE_POSITION
            ),
            TimeRange(
                require_int(
                    d["demo_start_us"],
                    "demo_start_us",
                    minimum=0,
                    maximum=MAX_DEMO_TIME_US,
                ),
                require_int(
                    d["demo_end_us"], "demo_end_us", minimum=0, maximum=MAX_DEMO_TIME_US
                ),
            ),
            require_int(
                d["uncertainty_us"],
                "uncertainty_us",
                minimum=0,
                maximum=MAX_DEMO_TIME_US,
            ),
            require_identifier(d["provenance"], "provenance"),
        )


def validate_anchor_sequence(anchors):
    groups = {}
    for a in anchors:
        groups.setdefault((a.source_clock, a.source_stream_id), []).append(a)
    for group in groups.values():
        ordered = sorted(group, key=lambda a: a.source_start)
        for x, y in zip(ordered, ordered[1:]):
            if (
                y.source_start < x.source_end
                or y.demo_range.start_us < x.demo_range.end_us
            ):
                _bad("time_anchor_invalid")


def _ceildiv(a, b):
    return -((-a) // b)


@dataclass(frozen=True, slots=True)
class MappedTime:
    segments: tuple[TimeRange, ...]
    anchor_ids: tuple[str, ...]
    uncertainty_us: int

    def __post_init__(self):
        if not isinstance(self.segments, tuple):
            object.__setattr__(self, "segments", tuple(self.segments))
        if not isinstance(self.anchor_ids, tuple):
            object.__setattr__(self, "anchor_ids", tuple(self.anchor_ids))
        if not self.segments or len(self.segments) != len(self.anchor_ids):
            _bad("domain_field_invalid")
        if any(not isinstance(x, TimeRange) for x in self.segments):
            _bad("domain_field_invalid")
        if any(not isinstance(x, str) for x in self.anchor_ids):
            _bad("domain_field_invalid")
        for x in self.anchor_ids:
            require_identifier(x, "anchor_id")
        require_int(
            self.uncertainty_us, "uncertainty_us", minimum=0, maximum=MAX_DEMO_TIME_US
        )

    @property
    def is_contiguous(self):
        return all(
            a.end_us == b.start_us for a, b in zip(self.segments, self.segments[1:])
        )

    @property
    def envelope(self):
        return TimeRange(self.segments[0].start_us, self.segments[-1].end_us)


def map_source_range(anchors, source_clock, source_stream_id, source_start, source_end):
    require_int(source_start, "source_start", minimum=0, maximum=MAX_SOURCE_POSITION)
    require_int(source_end, "source_end", minimum=0, maximum=MAX_SOURCE_POSITION)
    if source_end <= source_start:
        _bad("time_anchor_gap")
    validate_anchor_sequence(anchors)
    selected = sorted(
        (
            a
            for a in anchors
            if a.source_clock == source_clock and a.source_stream_id == source_stream_id
        ),
        key=lambda a: a.source_start,
    )
    cur = source_start
    segments = []
    ids = []
    unc = 0
    for a in selected:
        if a.source_end <= cur:
            continue
        if a.source_start > cur:
            break
        lo = max(cur, a.source_start)
        hi = min(source_end, a.source_end)
        if hi <= lo:
            continue
        span = a.source_end - a.source_start
        dspan = a.demo_range.duration_us
        ds = a.demo_range.start_us + (lo - a.source_start) * dspan // span
        de = a.demo_range.start_us + _ceildiv((hi - a.source_start) * dspan, span)
        segments.append(TimeRange(ds, de))
        ids.append(a.anchor_id)
        unc = max(unc, a.uncertainty_us)
        cur = hi
        if cur >= source_end:
            break
    if cur < source_end or not segments:
        _bad("time_anchor_gap")
    return MappedTime(tuple(segments), tuple(ids), unc)


def demo_to_round_local_us(demo_time_us, round_range):
    require_int(demo_time_us, "demo_time_us", minimum=0, maximum=MAX_DEMO_TIME_US)
    if not isinstance(round_range, TimeRange):
        _bad("domain_field_invalid")
    if not round_range.contains(demo_time_us):
        _bad("time_outside_round")
    return demo_time_us - round_range.start_us


def to_export_milliseconds(time_range):
    return (time_range.start_us // 1000, _ceildiv(time_range.end_us, 1000))
