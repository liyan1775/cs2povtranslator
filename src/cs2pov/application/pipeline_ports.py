from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import math
from pathlib import Path
from typing import Protocol

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.models import DemoInfo, Player, Round as LegacyRound
from cs2pov.domain.job import CreateJobRequest, JobPhase
from cs2pov.domain.job_state import advance_job_phase
from cs2pov.domain.schema import require_sha256
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.timeline import (
    DemoDescriptor,
    DemoTimeline,
    MatchPhase,
    PlayerSnapshot,
    Round,
    RoundBoundaryConfidence,
    RoundCollection,
)
from cs2pov.adapters.demoparser_adapter import DemoparserAdapter


class PipelinePortError(RuntimeError):
    """Stable application error exposed by a current-version pipeline port."""

    def __init__(
        self,
        code: str,
        message_zh: str,
        suggestion_zh: str,
        path: str | None = None,
    ) -> None:
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        self.path = path
        super().__init__(message_zh)


class DemoParserPort(Protocol):
    def parse_timeline(
        self,
        demo_path: Path,
        demo_asset_id: str,
        *,
        min_duration_seconds: float = 10.0,
        fallback_end_time: float = 1.0,
    ) -> DemoTimeline:
        """Return a validated current-version DemoTimeline."""


@dataclass(frozen=True, slots=True)
class _TickRate:
    value: Fraction

    @property
    def numerator(self) -> int:
        return self.value.numerator

    @property
    def denominator(self) -> int:
        return self.value.denominator

    @property
    def one_tick_us(self) -> int:
        return _ceil_fraction(Fraction(1_000_000, 1) / self.value)


class LegacyDemoParserPort:
    """Adapt the existing parser to the current-version timeline contract.

    The legacy parser remains responsible for demoparser2 compatibility and
    round cleaning. This boundary owns only deterministic type and time
    conversion; it never writes an ArtifactStore or a PipelineManifest.
    """

    def __init__(self, adapter: object | None = None) -> None:
        self.adapter = adapter or DemoparserAdapter()
        if not callable(getattr(self.adapter, "inspect", None)) or not callable(
            getattr(self.adapter, "parse_rounds", None)
        ):
            raise TypeError("adapter 必须提供 inspect 和 parse_rounds 方法。")

    def parse_timeline(
        self,
        demo_path: Path,
        demo_asset_id: str,
        *,
        min_duration_seconds: float = 10.0,
        fallback_end_time: float = 1.0,
    ) -> DemoTimeline:
        path = _require_demo_path(demo_path)
        asset_id = _require_asset_id(demo_asset_id)
        tick_rate = _require_positive_seconds(min_duration_seconds, "min_duration_seconds")
        fallback_end = _require_positive_seconds(fallback_end_time, "fallback_end_time")

        try:
            info = self.adapter.inspect(path, path)
            if not isinstance(info, DemoInfo):
                raise PipelinePortError(
                    "pipeline_metadata_invalid",
                    "Demo 解析器返回的描述信息无效。",
                    "请检查 demoparser2 适配器版本后重试。",
                    "demo",
                )
            rate = _parse_tick_rate(info.tick_rate)
            legacy_rounds = self.adapter.parse_rounds(
                path,
                tick_rate=float(rate.value),
                fallback_end_time=fallback_end,
                min_duration_seconds=tick_rate,
            )
            return _build_timeline(asset_id, info, legacy_rounds, rate)
        except PipelinePortError:
            raise
        except DomainSchemaError as exc:
            raise PipelinePortError(
                exc.code,
                exc.message,
                exc.action,
                exc.path,
            ) from exc
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            raise PipelinePortError(
                "pipeline_parse_failed",
                "无法把旧版 Demo 解析结果转换为当前版本时间线。",
                "请检查 Demo 文件、解析器版本和回合边界后重试。",
                "timeline",
            ) from exc


def _build_timeline(
    asset_id: str,
    info: DemoInfo,
    legacy_rounds: object,
    tick_rate: _TickRate,
) -> DemoTimeline:
    map_name = info.map_name.strip() if isinstance(info.map_name, str) else ""
    if not map_name:
        raise PipelinePortError(
            "pipeline_metadata_invalid",
            "Demo 缺少可用于当前 Job 的地图名称。",
            "请使用包含有效地图信息的 Demo，或先修正解析器输出。",
            "demo.map_name",
        )
    if not isinstance(legacy_rounds, (list, tuple)):
        raise PipelinePortError(
            "pipeline_rounds_invalid",
            "Demo 解析器返回的回合集合无效。",
            "请检查回合解析适配器后重试。",
            "rounds",
        )
    rounds, anchors = _convert_rounds(tuple(legacy_rounds), tick_rate)
    players = tuple(_convert_player(player) for player in info.players)
    descriptor = DemoDescriptor(
        asset_id,
        map_name,
        info.server_name if isinstance(info.server_name, str) and info.server_name else None,
        tick_rate.numerator,
        tick_rate.denominator,
        players,
    )
    return DemoTimeline(descriptor, RoundCollection(rounds), tuple(anchors))


def _convert_player(player: object) -> PlayerSnapshot:
    if not isinstance(player, Player):
        raise PipelinePortError(
            "pipeline_metadata_invalid",
            "Demo 解析器返回的玩家信息无效。",
            "请检查玩家信息解析结果后重试。",
            "demo.players",
        )
    player_id = str(player.steamid).strip()
    display_name = str(player.display_name or player.name or player_id).strip()
    if not player_id or not display_name:
        raise PipelinePortError(
            "pipeline_metadata_invalid",
            "Demo 玩家缺少稳定身份或显示名称。",
            "请检查 Demo 玩家信息后重试。",
            "demo.players",
        )
    try:
        return PlayerSnapshot(player_id, display_name, player.team_number)
    except DomainSchemaError as exc:
        raise PipelinePortError(exc.code, exc.message, exc.action, exc.path) from exc


def _convert_rounds(
    legacy_rounds: tuple[object, ...],
    tick_rate: _TickRate,
) -> tuple[tuple[Round, ...], tuple[TimeAnchor, ...]]:
    ordered: list[LegacyRound] = []
    for value in legacy_rounds:
        if not isinstance(value, LegacyRound):
            raise PipelinePortError(
                "pipeline_rounds_invalid",
                "Demo 解析器返回了无法识别的回合对象。",
                "请检查回合适配器的返回类型后重试。",
                "rounds",
            )
        if not _finite(value.start_time) or not _finite(value.end_time) or value.end_time <= value.start_time:
            raise PipelinePortError(
                "pipeline_rounds_invalid",
                "回合边界不是有效的递增时间区间。",
                "请检查 Demo 回合事件或调整回合清洗参数。",
                "rounds",
            )
        if (value.start_tick is None) != (value.end_tick is None):
            raise PipelinePortError(
                "pipeline_rounds_invalid",
                "回合的 tick 边界不完整。",
                "请检查解析器输出；不完整的 tick 边界不能进入当前时间线。",
                "rounds",
            )
        if value.start_tick is not None and value.end_tick <= value.start_tick:
            raise PipelinePortError(
                "pipeline_rounds_invalid",
                "回合的 tick 边界不是递增区间。",
                "请检查 Demo 回合事件后重试。",
                "rounds",
            )
        ordered.append(value)
    ordered.sort(key=lambda value: (value.start_time, value.end_time, value.round_number))

    converted: list[Round] = []
    anchors: list[TimeAnchor] = []
    previous_end_us: int | None = None
    for display_number, value in enumerate(ordered, 1):
        has_ticks = value.start_tick is not None and value.end_tick is not None
        if has_ticks:
            start_us = _tick_to_us(value.start_tick, tick_rate.value, ceil=False)
            end_us = _tick_to_us(value.end_tick, tick_rate.value, ceil=True)
            confidence = RoundBoundaryConfidence.EXACT
            uncertainty_us = 0
        else:
            start_us = _seconds_to_us(value.start_time, ceil=False)
            end_us = _seconds_to_us(value.end_time, ceil=True)
            confidence = (
                RoundBoundaryConfidence.FALLBACK
                if str(value.source).startswith("fallback")
                else RoundBoundaryConfidence.ESTIMATED
            )
            uncertainty_us = 0 if confidence is RoundBoundaryConfidence.FALLBACK else tick_rate.one_tick_us
        if end_us <= start_us or (previous_end_us is not None and start_us < previous_end_us):
            raise PipelinePortError(
                "pipeline_rounds_invalid",
                "规范化后的回合边界重叠或倒退。",
                "请检查回合清洗结果后重试；当前版本不会写入部分时间线。",
                f"rounds[{display_number - 1}]",
            )
        round_id = f"round-{display_number:03d}"
        match_phase = MatchPhase.WARMUP if value.is_warmup else MatchPhase.UNKNOWN
        provenance = _safe_identifier(
            "legacy-demoparser-v1" if not value.source else f"legacy-{value.source}"
        )
        current = Round(
            round_id,
            display_number,
            TimeRange(start_us, end_us),
            value.start_tick if has_ticks else None,
            value.end_tick if has_ticks else None,
            match_phase,
            provenance,
            confidence,
            uncertainty_us,
        )
        converted.append(current)
        if has_ticks:
            anchors.append(
                TimeAnchor(
                    f"anchor-demo-{display_number:03d}",
                    SourceClock.DEMO_TICK,
                    "demo",
                    value.start_tick,
                    value.end_tick,
                    current.time_range,
                    0,
                    provenance,
                )
            )
        previous_end_us = end_us
    return tuple(converted), tuple(anchors)


def _parse_tick_rate(value: object) -> _TickRate:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise PipelinePortError(
            "pipeline_metadata_invalid",
            "Demo tick rate 无效。",
            "请检查 Demo header 或解析器输出后重试。",
            "demo.tick_rate",
        )
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise PipelinePortError(
            "pipeline_metadata_invalid",
            "Demo tick rate 无法转换为确定的有理数。",
            "请检查 Demo header 后重试。",
            "demo.tick_rate",
        ) from exc
    if result <= 0:
        raise PipelinePortError(
            "pipeline_metadata_invalid",
            "Demo tick rate 必须为正数。",
            "请检查 Demo header 后重试。",
            "demo.tick_rate",
        )
    return _TickRate(result)


def _require_demo_path(value: object) -> Path:
    if not isinstance(value, Path):
        raise PipelinePortError(
            "pipeline_input_invalid",
            "Demo 输入路径类型无效。",
            "请提供本地 Demo 文件路径。",
            "demo_path",
        )
    try:
        if not value.exists() or not value.is_file():
            raise PipelinePortError(
                "pipeline_input_invalid",
                "找不到可读取的 Demo 文件。",
                "请检查 Demo 路径后重试。",
                "demo_path",
            )
    except OSError as exc:
        raise PipelinePortError(
            "pipeline_input_invalid",
            "无法读取 Demo 输入。",
            "请检查文件权限后重试。",
            "demo_path",
        ) from exc
    return value


def _require_asset_id(value: object) -> str:
    try:
        return require_sha256(value, "demo_asset_id")
    except DomainSchemaError as exc:
        raise PipelinePortError(exc.code, "DemoAsset 身份无效。", "请使用已登记的 DemoAsset 后重试。", exc.path) from exc


def _require_positive_seconds(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise PipelinePortError("pipeline_parameter_invalid", "时间参数无效。", "请提供正数秒数后重试。", path)
    return float(value)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _seconds_to_us(value: float, *, ceil: bool) -> int:
    scaled = Fraction(str(value)) * 1_000_000
    return _ceil_fraction(scaled) if ceil else scaled.numerator // scaled.denominator


def _tick_to_us(tick: int, tick_rate: Fraction, *, ceil: bool) -> int:
    scaled = Fraction(tick * 1_000_000, 1) / tick_rate
    return _ceil_fraction(scaled) if ceil else scaled.numerator // scaled.denominator


def _ceil_fraction(value: Fraction) -> int:
    return -((-value.numerator) // value.denominator)


def _safe_identifier(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip(".-")
    return normalized[:128] or "legacy-parser"


class CurrentJobTimelineApplicationService:
    """Create and initialize a current Job through the timeline port.

    Parsing is deliberately completed before Job creation. Once the source
    contract is known to be valid, the repository owns the atomic publication
    and claim-fenced phase transition.
    """

    def __init__(
        self,
        repository: object,
        parser: DemoParserPort | None = None,
        *,
        claim_lease_us: int = 60_000_000,
    ) -> None:
        if not callable(getattr(repository, "create_job", None)) or not callable(
            getattr(repository, "acquire_write", None)
        ):
            raise TypeError("repository 不符合当前 Job 仓储接口。")
        if type(claim_lease_us) is not int or claim_lease_us <= 0:
            raise ValueError("claim_lease_us 必须为正整数。")
        self.repository = repository
        self.parser = parser or LegacyDemoParserPort()
        self.claim_lease_us = claim_lease_us

    def create_job_with_timeline(
        self,
        request: CreateJobRequest,
        demo_path: Path,
        *,
        min_duration_seconds: float = 10.0,
        fallback_end_time: float = 1.0,
    ) -> object:
        if not isinstance(request, CreateJobRequest):
            raise TypeError("request 必须是 CreateJobRequest。")
        # Parse first: a malformed Demo must not create a current-version Job.
        timeline = self.parser.parse_timeline(
            demo_path,
            request.source.asset_id,
            min_duration_seconds=min_duration_seconds,
            fallback_end_time=fallback_end_time,
        )
        self.repository.create_job(request)
        with self.repository.acquire_write(
            request.job_id,
            lease_us=self.claim_lease_us,
        ) as session:
            self.repository.save_demo_timeline(request.job_id, timeline, session.claim)
            current = self.repository.load_job(request.job_id)
            candidate = advance_job_phase(
                current.manifest,
                JobPhase.TIMELINE_READY,
                at=_next_timestamp(self.repository.clock, current.manifest.updated_at),
            )
            self.repository.replace_manifest(
                request.job_id,
                current.manifest.content_fingerprint(),
                candidate,
                session.claim,
            )
        return self.repository.load_job(request.job_id)


def _next_timestamp(clock, previous: str) -> str:
    now = clock()
    if not isinstance(now, datetime):
        raise PipelinePortError(
            "pipeline_clock_invalid",
            "当前 Job 时钟返回值无效。",
            "请使用带时区的 UTC 时钟后重试。",
            "job.updated_at",
        )
    if now.tzinfo is None or now.utcoffset() is None:
        raise PipelinePortError(
            "pipeline_clock_invalid",
            "当前 Job 时钟必须包含时区。",
            "请使用带时区的 UTC 时钟后重试。",
            "job.updated_at",
        )
    previous_dt = _parse_timestamp(previous)
    current = now.astimezone(timezone.utc)
    if current <= previous_dt:
        current = previous_dt + timedelta(microseconds=1)
    return current.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError) as exc:
        raise PipelinePortError(
            "pipeline_clock_invalid",
            "Job 的更新时间格式无效。",
            "请重新打开当前版本 Job 后重试。",
            "job.updated_at",
        ) from exc
    return parsed.replace(tzinfo=timezone.utc)
