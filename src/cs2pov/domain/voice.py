from dataclasses import dataclass
from .timebase import TimeRange
from .schema import (
    MAX_COUNT,
    MAX_DEMO_TIME_US,
    require_current_schema,
    require_exact_keys,
    require_identifier,
    require_int,
    require_mapping,
    reject_private_data,
)
from .errors import DomainSchemaError


@dataclass(frozen=True, slots=True)
class VoiceActivityCue:
    activity_id: str
    player_id: str
    time_range: TimeRange
    packet_count: int
    anchor_ids: tuple[str, ...]
    uncertainty_us: int

    def __post_init__(self):
        require_identifier(self.activity_id, "activity_id")
        require_identifier(self.player_id, "player_id")
        if not isinstance(self.time_range, TimeRange):
            raise DomainSchemaError(
                "domain_field_invalid", "活动无效。", "请修正后重试。"
            )
        require_int(self.packet_count, "packet_count", minimum=1, maximum=MAX_COUNT)
        if not isinstance(self.anchor_ids, (list, tuple)):
            raise DomainSchemaError(
                "domain_field_invalid", "活动无效。", "请修正后重试。"
            )
        object.__setattr__(
            self,
            "anchor_ids",
            tuple(require_identifier(x, "anchor_id") for x in self.anchor_ids),
        )
        require_int(
            self.uncertainty_us, "uncertainty_us", minimum=0, maximum=MAX_DEMO_TIME_US
        )
        if not self.anchor_ids:
            raise DomainSchemaError(
                "domain_field_invalid", "活动无效。", "请修正后重试。"
            )

    def to_dict(self):
        return {
            "schema_version": 1,
            "activity_id": self.activity_id,
            "player_id": self.player_id,
            "start_us": self.time_range.start_us,
            "end_us": self.time_range.end_us,
            "packet_count": self.packet_count,
            "anchor_ids": list(self.anchor_ids),
            "uncertainty_us": self.uncertainty_us,
        }

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "activity")
        reject_private_data(d, "activity")
        require_current_schema(d, "activity")
        require_exact_keys(
            d,
            {
                "schema_version",
                "activity_id",
                "player_id",
                "start_us",
                "end_us",
                "packet_count",
                "anchor_ids",
                "uncertainty_us",
            },
            set(),
            "activity",
        )
        if not isinstance(d["anchor_ids"], (list, tuple)):
            raise DomainSchemaError(
                "domain_field_invalid", "活动无效。", "请修正后重试。"
            )
        return cls(
            d["activity_id"],
            d["player_id"],
            TimeRange(d["start_us"], d["end_us"]),
            d["packet_count"],
            tuple(d["anchor_ids"]),
            d["uncertainty_us"],
        )
