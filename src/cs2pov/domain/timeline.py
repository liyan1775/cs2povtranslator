from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .errors import DomainSchemaError
from .schema import (
    MAX_COUNT,
    MAX_DEMO_TIME_US,
    MAX_SOURCE_POSITION,
    require_current_schema,
    require_exact_keys,
    require_identifier,
    require_int,
    require_mapping,
    require_optional_int,
    require_optional_str,
    require_sha256,
    require_str,
    reject_private_data,
)
from .timebase import (
    TimeRange,
    TimeAnchor,
    SourceClock,
    map_source_range,
    validate_anchor_sequence,
)


def bad(code, path="timeline"):
    raise DomainSchemaError(code, "领域引用无效。", "请修正后重试。", path)


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    player_id: str
    display_name: str
    team_number: int | None

    def __post_init__(self):
        require_identifier(self.player_id, "player_id")
        require_str(self.display_name, "display_name")
        require_optional_int(self.team_number, "team_number", minimum=0)
        reject_private_data(
            {"player_id": self.player_id, "display_name": self.display_name}, "player"
        )

    def to_dict(self):
        return {
            "player_id": self.player_id,
            "display_name": self.display_name,
            "team_number": self.team_number,
        }

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "player")
        reject_private_data(d, "player")
        require_exact_keys(
            d, {"player_id", "display_name", "team_number"}, set(), "player"
        )
        return cls(
            require_identifier(d["player_id"], "player_id"),
            require_str(d["display_name"], "display_name"),
            require_optional_int(d["team_number"], "team_number", minimum=0),
        )


class RoundBoundaryConfidence(Enum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    FALLBACK = "fallback"


class MatchPhase(Enum):
    WARMUP = "warmup"
    REGULATION_FIRST_HALF = "regulation_first_half"
    REGULATION_SECOND_HALF = "regulation_second_half"
    OVERTIME_FIRST_HALF = "overtime_first_half"
    OVERTIME_SECOND_HALF = "overtime_second_half"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DemoDescriptor:
    demo_asset_id: str
    map_name: str
    server_name: str | None
    tick_rate_numerator: int
    tick_rate_denominator: int
    players: tuple[PlayerSnapshot, ...]

    def __post_init__(self):
        if not isinstance(self.players, (tuple, list)):
            bad("domain_field_invalid")
        if not isinstance(self.players, tuple):
            object.__setattr__(self, "players", tuple(self.players))
        if any(not isinstance(p, PlayerSnapshot) for p in self.players):
            bad("domain_field_invalid")
        require_sha256(self.demo_asset_id, "demo_asset_id")
        require_identifier(self.map_name, "map_name")
        require_optional_str(self.server_name, "server_name")
        require_int(self.tick_rate_numerator, "tick_rate.numerator", minimum=1)
        require_int(self.tick_rate_denominator, "tick_rate.denominator", minimum=1)
        reject_private_data({"server_name": self.server_name}, "demo")
        if len({p.player_id for p in self.players}) != len(self.players):
            bad("player_reference_invalid")

    def to_dict(self):
        return {
            "schema_version": 1,
            "demo_asset_id": self.demo_asset_id,
            "map_name": self.map_name,
            "server_name": self.server_name,
            "tick_rate": {
                "numerator": self.tick_rate_numerator,
                "denominator": self.tick_rate_denominator,
            },
            "players": [p.to_dict() for p in self.players],
        }

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "demo")
        reject_private_data(d, "demo")
        require_current_schema(d, "demo")
        require_exact_keys(
            d,
            {
                "schema_version",
                "demo_asset_id",
                "map_name",
                "server_name",
                "tick_rate",
                "players",
            },
            set(),
            "demo",
        )
        t = require_mapping(d["tick_rate"], "tick_rate")
        require_exact_keys(t, {"numerator", "denominator"}, set(), "tick_rate")
        if not isinstance(d["players"], (list, tuple)):
            bad("domain_field_invalid")
        return cls(
            require_sha256(d["demo_asset_id"], "demo_asset_id"),
            require_identifier(d["map_name"], "map_name"),
            require_optional_str(d["server_name"], "server_name"),
            require_int(t["numerator"], "numerator", minimum=1),
            require_int(t["denominator"], "denominator", minimum=1),
            tuple(PlayerSnapshot.from_dict(x) for x in d["players"]),
        )


@dataclass(frozen=True, slots=True)
class Round:
    round_id: str
    display_number: int
    time_range: TimeRange
    start_tick: int | None
    end_tick: int | None
    match_phase: MatchPhase
    provenance: str
    confidence: RoundBoundaryConfidence
    boundary_uncertainty_us: int

    def __post_init__(self):
        if (
            not isinstance(self.time_range, TimeRange)
            or not isinstance(self.match_phase, MatchPhase)
            or not isinstance(self.confidence, RoundBoundaryConfidence)
        ):
            bad("domain_field_invalid")
        require_identifier(self.round_id, "round_id")
        require_int(self.display_number, "display_number", minimum=1, maximum=MAX_COUNT)
        require_optional_int(
            self.start_tick, "start_tick", minimum=0, maximum=MAX_SOURCE_POSITION
        )
        require_optional_int(
            self.end_tick, "end_tick", minimum=0, maximum=MAX_SOURCE_POSITION
        )
        require_identifier(self.provenance, "provenance")
        require_int(
            self.boundary_uncertainty_us,
            "boundary_uncertainty_us",
            minimum=0,
            maximum=MAX_DEMO_TIME_US,
        )
        if (self.start_tick is None) != (self.end_tick is None) or (
            self.start_tick is not None and self.end_tick <= self.start_tick
        ):
            bad("round_reference_invalid")
        if (
            self.confidence is RoundBoundaryConfidence.EXACT
            and self.boundary_uncertainty_us != 0
        ):
            bad("round_reference_invalid")

    def to_dict(self):
        return {
            "round_id": self.round_id,
            "display_number": self.display_number,
            "start_us": self.time_range.start_us,
            "end_us": self.time_range.end_us,
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
            "match_phase": self.match_phase.value,
            "provenance": self.provenance,
            "confidence": self.confidence.value,
            "boundary_uncertainty_us": self.boundary_uncertainty_us,
        }

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "round")
        reject_private_data(d, "round")
        require_exact_keys(
            d,
            {
                "round_id",
                "display_number",
                "start_us",
                "end_us",
                "start_tick",
                "end_tick",
                "match_phase",
                "provenance",
                "confidence",
                "boundary_uncertainty_us",
            },
            set(),
            "round",
        )
        try:
            phase = MatchPhase(d["match_phase"])
            conf = RoundBoundaryConfidence(d["confidence"])
        except ValueError as e:
            bad("domain_field_invalid")
        return cls(
            require_identifier(d["round_id"], "round_id"),
            require_int(
                d["display_number"], "display_number", minimum=1, maximum=MAX_COUNT
            ),
            TimeRange(d["start_us"], d["end_us"]),
            require_optional_int(
                d["start_tick"], "start_tick", minimum=0, maximum=MAX_SOURCE_POSITION
            ),
            require_optional_int(
                d["end_tick"], "end_tick", minimum=0, maximum=MAX_SOURCE_POSITION
            ),
            phase,
            require_identifier(d["provenance"], "provenance"),
            conf,
            require_int(
                d["boundary_uncertainty_us"],
                "boundary_uncertainty_us",
                minimum=0,
                maximum=MAX_DEMO_TIME_US,
            ),
        )


@dataclass(frozen=True, slots=True)
class RoundCollection:
    rounds: tuple[Round, ...]

    def __post_init__(self):
        if not isinstance(self.rounds, (tuple, list)):
            bad("domain_field_invalid")
        if not isinstance(self.rounds, tuple):
            object.__setattr__(self, "rounds", tuple(self.rounds))
        if any(not isinstance(r, Round) for r in self.rounds):
            bad("domain_field_invalid")
        if len({r.round_id for r in self.rounds}) != len(self.rounds) or len(
            {r.display_number for r in self.rounds}
        ) != len(self.rounds):
            bad("round_reference_invalid")
        if any(
            a.display_number >= b.display_number
            for a, b in zip(self.rounds, self.rounds[1:])
        ):
            bad("round_reference_invalid")
        if any(
            a.time_range.end_us > b.time_range.start_us
            for a, b in zip(self.rounds, self.rounds[1:])
        ):
            bad("round_reference_invalid")

    def to_dict(self):
        return {"schema_version": 1, "rounds": [r.to_dict() for r in self.rounds]}

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "rounds")
        reject_private_data(d, "rounds")
        require_current_schema(d, "rounds")
        require_exact_keys(d, {"schema_version", "rounds"}, set(), "rounds")
        if not isinstance(d["rounds"], (list, tuple)):
            bad("domain_field_invalid")
        return cls(tuple(Round.from_dict(x) for x in d["rounds"]))


@dataclass(frozen=True, slots=True)
class DemoTimeline:
    descriptor: DemoDescriptor
    rounds: RoundCollection
    anchors: tuple[TimeAnchor, ...]

    def __post_init__(self):
        if not isinstance(self.descriptor, DemoDescriptor) or not isinstance(
            self.rounds, RoundCollection
        ):
            bad("domain_field_invalid")
        if not isinstance(self.anchors, (tuple, list)):
            bad("domain_field_invalid")
        if not isinstance(self.anchors, tuple):
            object.__setattr__(self, "anchors", tuple(self.anchors))
        if any(not isinstance(a, TimeAnchor) for a in self.anchors):
            bad("domain_field_invalid")
        if len({a.anchor_id for a in self.anchors}) != len(self.anchors):
            bad("time_anchor_invalid")
        players = {p.player_id for p in self.descriptor.players}
        for a in self.anchors:
            if a.source_clock is SourceClock.DEMO_TICK and a.source_stream_id != "demo":
                bad("time_anchor_invalid")
            if (
                a.source_clock is SourceClock.COMPACT_AUDIO_SAMPLE
                and a.source_stream_id not in players
            ):
                bad("time_anchor_invalid")
        validate_anchor_sequence(self.anchors)
        tick = tuple(
            a
            for a in self.anchors
            if a.source_clock is SourceClock.DEMO_TICK and a.source_stream_id == "demo"
        )
        for r in self.rounds.rounds:
            if r.start_tick is None:
                continue
            if not tick:
                bad("round_reference_invalid")
            mapped = map_source_range(
                tick, SourceClock.DEMO_TICK, "demo", r.start_tick, r.end_tick
            )
            if not mapped.is_contiguous:
                bad("round_reference_invalid")
            for actual, declared in (
                (mapped.segments[0].start_us, r.time_range.start_us),
                (mapped.segments[-1].end_us, r.time_range.end_us),
            ):
                if r.confidence is RoundBoundaryConfidence.EXACT and (
                    mapped.uncertainty_us != 0 or actual != declared
                ):
                    bad("round_reference_invalid")
                if (
                    r.confidence is not RoundBoundaryConfidence.EXACT
                    and abs(actual - declared) + mapped.uncertainty_us
                    > r.boundary_uncertainty_us
                ):
                    bad("round_reference_invalid")

    def round_for_time(self, demo_time_us):
        require_int(demo_time_us, "demo_time_us", minimum=0, maximum=MAX_DEMO_TIME_US)
        return next(
            (r for r in self.rounds.rounds if r.time_range.contains(demo_time_us)), None
        )
