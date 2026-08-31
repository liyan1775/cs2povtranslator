# Domain Schema and Unified Demo Time Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the current-version, immutable domain contracts and integer-microsecond Demo time core that later Job persistence, round-parallel understanding translation, human review, subtitle/green-screen export, and optional POV rendering will share.

**Architecture:** Add focused standard-library domain modules beside the existing `domain/models.py`; do not connect them to the current Pipeline in this batch. Strict `from_dict` factories accept only schema version 1 and reject unknown or malformed data with stable domain errors. All durable times use integer Demo microseconds; ticks, compact audio samples, and future video frames map through auditable segmented anchors.

**Tech Stack:** Python 3.11–3.13, frozen/slotted dataclasses, `enum.Enum`, `fractions.Fraction`, JSON-compatible dictionaries, pytest 8+, existing golden-baseline and repository-hygiene scripts.

**Spec:** `docs/superpowers/specs/2026-08-31-new-job-domain-and-timeline-design.md`

## Global Constraints

- This is batch 02A only: do not modify `PipelineEngine`, `ArtifactStore`, CLI behavior, workspace layout, Web UI, or current v0.x serialization.
- Do not implement old v0.x Job import or any cross-version migration chain.
- Every new top-level JSON document and every JSONL record uses exact integer `schema_version: 1`; any other version returns `domain_schema_unsupported` without rewriting data.
- Durable domain time is a non-negative Python `int` in Demo microseconds; reject `bool`, negative values, reverse/empty ranges, and premature floating-point time storage.
- Source clocks retain integer ticks/samples/frames and map to Demo time only through `TimeAnchor`; compact audio gaps must remain observable.
- New identifiers are safe single path segments matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` and may not equal `.` or `..`.
- New domain values are immutable (`@dataclass(frozen=True, slots=True)`) and serialize to deterministic JSON-compatible dictionaries.
- Job/domain objects never store API keys, authorization headers, passwords, external absolute paths, or user-home paths.
- No new runtime dependency is allowed in 02A.
- All tests must work without CS2, GPU, FFmpeg, Whisper, a real Demo, network access, or a paid model API.
- CI compatibility remains Ubuntu Python 3.11/3.12/3.13 and Windows Python 3.12, including repository paths containing Chinese characters and spaces.

## File Structure

New production files:

- `src/cs2pov/domain/errors.py`: stable domain error object with user-facing Chinese message and action.
- `src/cs2pov/domain/schema.py`: schema/version, exact-key, scalar, identifier, SHA-256, and secret-key validation helpers.
- `src/cs2pov/domain/timebase.py`: integer Demo ranges, source clocks, segmented anchors, source-to-Demo mapping, round-local conversion, and export rounding.
- `src/cs2pov/domain/timeline.py`: player snapshots, Demo descriptor, rounds, round collection, and validated in-memory Demo timeline aggregate.
- `src/cs2pov/domain/invocation.py`: non-secret frozen model invocation snapshot.
- `src/cs2pov/domain/voice.py`: immutable integer-time voice-activity JSONL record.
- `src/cs2pov/domain/transcript.py`: immutable ASR `TranscriptCue` JSONL record.
- `src/cs2pov/domain/understanding.py`: interpretation result and per-round understanding document.
- `src/cs2pov/domain/review.py`: typed human decisions plus draft/reviewed timeline contracts.

New tests and fixtures:

- `tests/test_domain_schema_v1.py`
- `tests/test_domain_timebase_v1.py`
- `tests/test_domain_timeline_v1.py`
- `tests/test_domain_invocation_v1.py`
- `tests/test_domain_understanding_v1.py`
- `tests/test_domain_review_v1.py`
- `tests/test_new_domain_contract_replay.py`
- `tests/golden/fixtures/new_domain_contract_v1.json`
- `scripts/check_new_domain_contract.py`

Documentation updates:

- `docs/ARCHITECTURE.zh.md`: describe the isolated 02A domain core without claiming Pipeline integration.
- `docs/TESTING_GUIDE.zh.md`: add the deterministic contract replay command.
- `tests/golden/README.zh.md`: distinguish the new-domain fixture from the frozen v0.9.8 behavior fixture.

---

### Task 1: Stable schema validation foundation

**Files:**
- Create: `src/cs2pov/domain/errors.py`
- Create: `src/cs2pov/domain/schema.py`
- Create: `tests/test_domain_schema_v1.py`

**Interfaces:**
- Produces: `DomainSchemaError(code: str, message: str, action: str, path: str | None = None)`.
- Produces: `CURRENT_DOMAIN_SCHEMA_VERSION: Final[int] = 1`.
- Produces: `require_mapping`, `require_exact_keys`, `require_current_schema`, `require_int`, `require_optional_int`, `require_str`, `require_optional_str`, `require_identifier`, `require_sha256`, `require_probability`, `require_string_list`, and `reject_secret_keys`.
- All later `from_dict` factories depend on these exact helpers and error codes.

Use these signatures throughout the batch:

```python
def require_mapping(value: object, path: str) -> Mapping[str, object]
def require_exact_keys(data: Mapping[str, object], required: set[str], optional: set[str], path: str) -> None
def require_current_schema(data: Mapping[str, object], path: str) -> int
def require_int(value: object, path: str, *, minimum: int | None = None) -> int
def require_optional_int(value: object, path: str, *, minimum: int | None = None) -> int | None
def require_str(value: object, path: str, *, allow_empty: bool = False) -> str
def require_optional_str(value: object, path: str, *, allow_empty: bool = False) -> str | None
def require_identifier(value: object, path: str) -> str
def require_sha256(value: object, path: str) -> str
def require_probability(value: object, path: str) -> float
def require_string_list(value: object, path: str, *, allow_empty: bool = True) -> tuple[str, ...]
def reject_secret_keys(value: object, path: str) -> None
```

- [ ] **Step 1: Write failing tests for error shape and strict scalar validation**

Create `tests/test_domain_schema_v1.py` with these cases:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.schema import (
    CURRENT_DOMAIN_SCHEMA_VERSION,
    reject_secret_keys,
    require_current_schema,
    require_identifier,
    require_int,
    require_probability,
)


def test_domain_schema_error_exposes_stable_diagnostic_fields() -> None:
    error = DomainSchemaError("time_range_invalid", "时间范围无效。", "请修正后重试。", "cue.start_us")

    assert str(error) == "时间范围无效。"
    assert error.code == "time_range_invalid"
    assert error.message == "时间范围无效。"
    assert error.action == "请修正后重试。"
    assert error.path == "cue.start_us"


def test_current_schema_accepts_only_exact_integer_one() -> None:
    assert CURRENT_DOMAIN_SCHEMA_VERSION == 1
    assert require_current_schema({"schema_version": 1}, "document") == 1

    for value in (True, 0, 2, "1", 1.0, None):
        with pytest.raises(DomainSchemaError) as caught:
            require_current_schema({"schema_version": value}, "document")
        assert caught.value.code == "domain_schema_unsupported"


def test_integer_validator_rejects_bool_and_negative_values() -> None:
    assert require_int(0, "value", minimum=0) == 0

    for value in (True, -1, 1.5, "1"):
        with pytest.raises(DomainSchemaError) as caught:
            require_int(value, "value", minimum=0)
        assert caught.value.code == "domain_field_invalid"


def test_identifier_is_safe_as_one_cross_platform_path_segment() -> None:
    assert require_identifier("round-001", "round_id") == "round-001"

    for value in ("", ".", "..", "round/1", "round\\1", "B 点", "x" * 129):
        with pytest.raises(DomainSchemaError) as caught:
            require_identifier(value, "round_id")
        assert caught.value.code == "domain_identifier_invalid"


def test_probability_is_finite_and_between_zero_and_one() -> None:
    assert require_probability(0, "confidence") == 0.0
    assert require_probability(0.86, "confidence") == 0.86
    assert require_probability(1, "confidence") == 1.0

    for value in (True, -0.1, 1.1, float("inf"), float("nan"), "0.5"):
        with pytest.raises(DomainSchemaError) as caught:
            require_probability(value, "confidence")
        assert caught.value.code == "domain_field_invalid"


def test_secret_key_scan_rejects_nested_credentials_but_not_max_tokens() -> None:
    reject_secret_keys({"temperature": 0.2, "max_tokens": 512}, "parameters")

    for payload in (
        {"api_key": "secret"},
        {"headers": {"authorization": "Bearer secret"}},
        {"credentials": [{"access_token": "secret"}]},
        {"password": "secret"},
    ):
        with pytest.raises(DomainSchemaError) as caught:
            reject_secret_keys(payload, "parameters")
        assert caught.value.code == "domain_secret_forbidden"
```

- [ ] **Step 2: Run the focused test and confirm the import failure**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_schema_v1.py -q
```

Expected: collection fails because `cs2pov.domain.errors` and `cs2pov.domain.schema` do not exist.

- [ ] **Step 3: Implement the stable error and exact validation helpers**

Implement `errors.py` as a `ValueError` subclass whose constructor stores the four tested fields and passes `message` to `ValueError.__init__`.

Implement `schema.py` with these exact validation policies:

```python
CURRENT_DOMAIN_SCHEMA_VERSION = 1
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SECRET_KEYS = frozenset({
    "api_key", "api-key", "authorization", "access_token", "secret", "password"
})
```

`require_exact_keys(data, required, optional, path)` must reject both missing and unknown keys with `domain_schema_invalid`. `require_current_schema` must convert missing, boolean, non-integer, and non-1 versions into `domain_schema_unsupported`. `reject_secret_keys` must recursively inspect mapping keys and list elements, compare keys case-insensitively, and never reject the legitimate key `max_tokens`.

- [ ] **Step 4: Run focused tests and confirm they pass**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_schema_v1.py -q
```

Expected: all tests in `test_domain_schema_v1.py` pass.

- [ ] **Step 5: Commit the schema foundation**

```powershell
git add src/cs2pov/domain/errors.py src/cs2pov/domain/schema.py tests/test_domain_schema_v1.py
git commit -m "feat: add strict domain schema validation"
```

---

### Task 2: Integer Demo time, segmented anchors, and export rounding

**Files:**
- Create: `src/cs2pov/domain/timebase.py`
- Create: `tests/test_domain_timebase_v1.py`

**Interfaces:**
- Consumes: Task 1 schema helpers and `DomainSchemaError`.
- Produces: `TimeRange(start_us: int, end_us: int)`.
- Produces: `SourceClock` values `DEMO_TICK`, `COMPACT_AUDIO_SAMPLE`, and `VIDEO_FRAME`.
- Produces: `TimeAnchor(anchor_id, source_clock, source_stream_id, source_start, source_end, demo_range, uncertainty_us, provenance)`.
- Produces: `MappedTime(segments, anchor_ids, uncertainty_us)` with `is_contiguous` and `envelope`.
- Produces: `map_source_range(anchors, source_clock, source_stream_id, source_start, source_end) -> MappedTime`.
- Produces: `demo_to_round_local_us(demo_time_us, round_range) -> int` and `to_export_milliseconds(time_range) -> tuple[int, int]`.

- [ ] **Step 1: Write failing time-range and anchor tests**

Create `tests/test_domain_timebase_v1.py` covering the exact behavior below:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.timebase import (
    SourceClock,
    TimeAnchor,
    TimeRange,
    demo_to_round_local_us,
    map_source_range,
    to_export_milliseconds,
)


def _audio_anchor(anchor_id: str, source_start: int, source_end: int, demo_start_us: int) -> TimeAnchor:
    return TimeAnchor(
        anchor_id=anchor_id,
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE,
        source_stream_id="player-alpha",
        source_start=source_start,
        source_end=source_end,
        demo_range=TimeRange(demo_start_us, demo_start_us + 1_000_000),
        uncertainty_us=16_000,
        provenance="synthetic-voice-extractor-v1",
    )


def test_time_range_is_non_negative_non_empty_and_half_open() -> None:
    value = TimeRange(1_000_000, 2_000_000)
    assert value.duration_us == 1_000_000
    assert value.contains(1_000_000)
    assert value.contains(1_999_999)
    assert not value.contains(2_000_000)

    for start, end in ((-1, 1), (1, 1), (2, 1)):
        with pytest.raises(DomainSchemaError) as caught:
            TimeRange(start, end)
        assert caught.value.code == "time_range_invalid"

    with pytest.raises(DomainSchemaError):
        TimeRange(True, 2)


def test_discontinuous_compact_audio_maps_to_two_demo_segments() -> None:
    anchors = (
        _audio_anchor("anchor-a", 0, 24_000, 10_000_000),
        _audio_anchor("anchor-b", 24_000, 48_000, 20_000_000),
    )

    mapped = map_source_range(
        anchors,
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        18_000,
        30_000,
    )

    assert mapped.segments == (
        TimeRange(10_750_000, 11_000_000),
        TimeRange(20_000_000, 20_250_000),
    )
    assert mapped.anchor_ids == ("anchor-a", "anchor-b")
    assert mapped.uncertainty_us == 16_000
    assert not mapped.is_contiguous
    assert mapped.envelope == TimeRange(10_750_000, 20_250_000)


@pytest.mark.parametrize(
    ("clock", "stream_id", "source_start", "source_end", "demo_start_us", "mapped_start", "mapped_end"),
    (
        (SourceClock.DEMO_TICK, "demo", 640, 704, 10_000_000, 672, 704),
        (SourceClock.VIDEO_FRAME, "render-main", 0, 30, 20_000_000, 15, 30),
    ),
)
def test_tick_and_video_frame_clocks_use_the_same_auditable_mapping(
    clock: SourceClock,
    stream_id: str,
    source_start: int,
    source_end: int,
    demo_start_us: int,
    mapped_start: int,
    mapped_end: int,
) -> None:
    anchor = TimeAnchor(
        anchor_id=f"anchor-{clock.value}",
        source_clock=clock,
        source_stream_id=stream_id,
        source_start=source_start,
        source_end=source_end,
        demo_range=TimeRange(demo_start_us, demo_start_us + 1_000_000),
        uncertainty_us=0,
        provenance="synthetic-clock-v1",
    )

    mapped = map_source_range((anchor,), clock, stream_id, mapped_start, mapped_end)
    assert mapped.segments == (TimeRange(demo_start_us + 500_000, demo_start_us + 1_000_000),)
    assert mapped.is_contiguous


def test_anchor_mapping_rejects_gaps_and_wrong_streams() -> None:
    anchors = (_audio_anchor("anchor-a", 0, 24_000, 10_000_000),)

    for stream_id, start, end in (
        ("player-bravo", 0, 1_000),
        ("player-alpha", 24_000, 25_000),
        ("player-alpha", 20_000, 25_000),
    ):
        with pytest.raises(DomainSchemaError) as caught:
            map_source_range(
                anchors,
                SourceClock.COMPACT_AUDIO_SAMPLE,
                stream_id,
                start,
                end,
            )
        assert caught.value.code == "time_anchor_gap"


def test_anchor_round_trip_uses_exact_current_schema() -> None:
    anchor = _audio_anchor("anchor-a", 0, 24_000, 10_000_000)
    payload = anchor.to_dict()

    assert payload["schema_version"] == 1
    assert payload["demo_start_us"] == 10_000_000
    assert TimeAnchor.from_dict(payload) == anchor

    payload["unexpected"] = True
    with pytest.raises(DomainSchemaError) as caught:
        TimeAnchor.from_dict(payload)
    assert caught.value.code == "domain_schema_invalid"


def test_round_local_conversion_and_srt_rounding_have_one_policy() -> None:
    round_range = TimeRange(10_000_000, 20_000_000)
    assert demo_to_round_local_us(10_750_000, round_range) == 750_000
    assert to_export_milliseconds(TimeRange(10_000_001, 10_001_001)) == (10_000, 10_002)

    with pytest.raises(DomainSchemaError) as caught:
        demo_to_round_local_us(20_000_000, round_range)
    assert caught.value.code == "time_outside_round"
```

- [ ] **Step 2: Run the timebase test and confirm the missing-module failure**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_timebase_v1.py -q
```

Expected: collection fails because `cs2pov.domain.timebase` does not exist.

- [ ] **Step 3: Implement immutable time values and segmented linear mapping**

Implement these policies in `timebase.py`:

- `TimeRange` validates both values through `require_int(value, path, minimum=0)` and requires `end_us > start_us`.
- `TimeAnchor` requires a non-empty source span, one safe `source_stream_id`, non-negative uncertainty, and non-empty provenance.
- Source overlap is mapped linearly using integer arithmetic. Start boundaries use floor division; end boundaries use ceiling division, so the mapped range never becomes shorter through rounding.
- `map_source_range` filters by both clock and stream, sorts anchors by `source_start`, rejects overlapping source anchors, requires the full requested source range to be covered, returns each discontinuous Demo segment separately, and never silently converts gaps into continuous time.
- `MappedTime.is_contiguous` is true only when every adjacent Demo segment touches exactly; `envelope` spans first start to last end.
- `to_export_milliseconds` floors the start and ceilings the end with integer arithmetic.
- `TimeAnchor.to_dict()` emits only the exact tested fields: `schema_version`, IDs, clock, integer source boundaries, integer Demo boundaries, uncertainty, and provenance.

- [ ] **Step 4: Run timebase and schema tests**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_schema_v1.py tests/test_domain_timebase_v1.py -q
```

Expected: both files pass.

- [ ] **Step 5: Commit the unified time core**

```powershell
git add src/cs2pov/domain/timebase.py tests/test_domain_timebase_v1.py
git commit -m "feat: add unified demo time and anchors"
```

---

### Task 3: Demo descriptor, stable rounds, and timeline aggregate

**Files:**
- Create: `src/cs2pov/domain/timeline.py`
- Create: `tests/test_domain_timeline_v1.py`

**Interfaces:**
- Consumes: `TimeRange`, `TimeAnchor`, and Task 1 validators.
- Produces: `PlayerSnapshot(player_id, display_name, team_number)`.
- Produces: `DemoDescriptor(demo_asset_id, map_name, server_name, tick_rate_numerator, tick_rate_denominator, players)` for `timeline/demo.json`.
- Produces: `RoundBoundaryConfidence` values `EXACT`, `ESTIMATED`, and `FALLBACK`.
- Produces: `Round(round_id, display_number, time_range, start_tick, end_tick, is_warmup, provenance, confidence)`.
- Produces: `RoundCollection(rounds)` for `timeline/rounds.json`.
- Produces: `DemoTimeline(descriptor, rounds, anchors)` as a validated in-memory aggregate with `round_for_time(demo_time_us)`.

- [ ] **Step 1: Write failing descriptor, round, and aggregate tests**

Create `tests/test_domain_timeline_v1.py` with tests that assert:

```python
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
)


def _round(round_id: str, number: int, start_us: int, end_us: int) -> Round:
    return Round(
        round_id=round_id,
        display_number=number,
        time_range=TimeRange(start_us, end_us),
        start_tick=start_us // 15_625,
        end_tick=end_us // 15_625,
        is_warmup=False,
        provenance="synthetic-round-parser-v1",
        confidence=RoundBoundaryConfidence.EXACT,
    )


def _descriptor() -> DemoDescriptor:
    return DemoDescriptor(
        demo_asset_id="a" * 64,
        map_name="de_mirage",
        server_name="fixture-server",
        tick_rate_numerator=64,
        tick_rate_denominator=1,
        players=(
            PlayerSnapshot("player-alpha", "Alpha", 2),
            PlayerSnapshot("player-bravo", "Bravo", 2),
        ),
    )


def test_demo_and_round_documents_round_trip_without_float_time() -> None:
    descriptor = _descriptor()
    rounds = RoundCollection((
        _round("round-001", 1, 10_000_000, 20_000_000),
        _round("round-002", 2, 20_000_000, 30_000_000),
    ))

    demo_payload = descriptor.to_dict()
    round_payload = rounds.to_dict()

    assert demo_payload["schema_version"] == 1
    assert round_payload["schema_version"] == 1
    assert "start_time" not in str(round_payload)
    assert DemoDescriptor.from_dict(demo_payload) == descriptor
    assert RoundCollection.from_dict(round_payload) == rounds


def test_round_ids_and_player_ids_are_unique() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        DemoDescriptor(
            demo_asset_id="a" * 64,
            map_name="de_mirage",
            server_name=None,
            tick_rate_numerator=64,
            tick_rate_denominator=1,
            players=(
                PlayerSnapshot("player-alpha", "Alpha", 2),
                PlayerSnapshot("player-alpha", "Alias", 2),
            ),
        )
    assert caught.value.code == "player_reference_invalid"

    repeated = _round("round-001", 2, 20_000_000, 30_000_000)
    with pytest.raises(DomainSchemaError) as caught:
        RoundCollection((_round("round-001", 1, 10_000_000, 20_000_000), repeated))
    assert caught.value.code == "round_reference_invalid"


def test_rounds_must_be_ordered_and_non_overlapping() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        RoundCollection((
            _round("round-001", 1, 10_000_000, 21_000_000),
            _round("round-002", 2, 20_000_000, 30_000_000),
        ))
    assert caught.value.code == "round_reference_invalid"


def test_half_open_boundary_assigns_exact_end_to_next_round() -> None:
    rounds = RoundCollection((
        _round("round-001", 1, 10_000_000, 20_000_000),
        _round("round-002", 2, 20_000_000, 30_000_000),
    ))
    timeline = DemoTimeline(_descriptor(), rounds, ())

    assert timeline.round_for_time(19_999_999).round_id == "round-001"
    assert timeline.round_for_time(20_000_000).round_id == "round-002"
    assert timeline.round_for_time(30_000_000) is None


def test_anchor_stream_must_refer_to_known_player_or_demo_stream() -> None:
    anchor = TimeAnchor(
        anchor_id="anchor-a",
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE,
        source_stream_id="player-missing",
        source_start=0,
        source_end=24_000,
        demo_range=TimeRange(10_000_000, 11_000_000),
        uncertainty_us=16_000,
        provenance="synthetic-voice-extractor-v1",
    )

    with pytest.raises(DomainSchemaError) as caught:
        DemoTimeline(_descriptor(), RoundCollection((_round("round-001", 1, 10_000_000, 20_000_000),)), (anchor,))
    assert caught.value.code == "time_anchor_invalid"
```

- [ ] **Step 2: Run the focused timeline test and confirm it fails**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_timeline_v1.py -q
```

Expected: collection fails because `cs2pov.domain.timeline` does not exist.

- [ ] **Step 3: Implement strict current-version timeline documents**

Implement `timeline.py` so that:

- every non-hash domain identifier uses `require_identifier`;
- every `demo_asset_id` uses `require_sha256`, matching the existing content-addressed `DemoAssetRef` identity;
- tick-rate numerator and denominator are positive integers and remain rational, never a float;
- team number is `None` or a non-negative integer;
- Round tick fields are both present or both absent; when present, end tick must be greater than start tick;
- `RoundCollection` requires unique IDs, unique display numbers, ascending time, and no overlap;
- `DemoTimeline` requires unique anchor IDs; `COMPACT_AUDIO_SAMPLE` streams refer to known player IDs; `DEMO_TICK` uses stream `demo`; future `VIDEO_FRAME` streams may use any safe renderer-generated ID;
- `DemoDescriptor.from_dict` and `RoundCollection.from_dict` reject unknown keys and unsupported versions;
- serialized times are only `start_us`/`end_us` integers.

The durable document shapes are exact:

```json
{"schema_version": 1, "demo_asset_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "map_name": "de_mirage", "server_name": null, "tick_rate": {"numerator": 64, "denominator": 1}, "players": [{"player_id": "player-alpha", "display_name": "Alpha", "team_number": 2}]}
```

```json
{"schema_version": 1, "rounds": [{"round_id": "round-001", "display_number": 1, "start_us": 10000000, "end_us": 20000000, "start_tick": 640, "end_tick": 1280, "is_warmup": false, "provenance": "synthetic-round-parser-v1", "confidence": "exact"}]}
```

- [ ] **Step 4: Run all domain tests created so far**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_schema_v1.py tests/test_domain_timebase_v1.py tests/test_domain_timeline_v1.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the Demo timeline contracts**

```powershell
git add src/cs2pov/domain/timeline.py tests/test_domain_timeline_v1.py
git commit -m "feat: add demo timeline domain contracts"
```

---

### Task 4: Non-secret model invocation snapshot

**Files:**
- Create: `src/cs2pov/domain/invocation.py`
- Create: `tests/test_domain_invocation_v1.py`

**Interfaces:**
- Consumes: Task 1 validation helpers.
- Produces: `ModelInvocationSnapshot(snapshot_id, provider_kind, endpoint_profile_id, model_name, prompt_template_version, parameters, knowledge_revision_ids, adapter_version, request_content_fingerprint)`.
- Produces deterministic `to_dict()` and strict `from_dict()` for the Job-safe snapshot.

- [ ] **Step 1: Write failing snapshot round-trip and secret-rejection tests**

Create `tests/test_domain_invocation_v1.py`:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invocation import ModelInvocationSnapshot


def _snapshot(parameters: dict[str, object] | None = None) -> ModelInvocationSnapshot:
    return ModelInvocationSnapshot(
        snapshot_id="invoke-001",
        provider_kind="openai-compatible",
        endpoint_profile_id="provider-local-profile",
        model_name="fixture-model",
        prompt_template_version="understanding-v1",
        parameters=parameters or {"temperature": 0.2, "max_tokens": 512},
        knowledge_revision_ids=("knowledge-global-001",),
        adapter_version="adapter-v1",
        request_content_fingerprint="a" * 64,
    )


def test_invocation_snapshot_round_trips_without_secret_or_raw_url() -> None:
    snapshot = _snapshot()
    payload = snapshot.to_dict()

    assert payload["schema_version"] == 1
    assert payload["endpoint_profile_id"] == "provider-local-profile"
    assert "api_key" not in str(payload).lower()
    assert "base_url" not in payload
    assert ModelInvocationSnapshot.from_dict(payload) == snapshot


def test_snapshot_copies_nested_json_parameters_to_prevent_mutation() -> None:
    source = {"response_format": {"type": "json_object"}}
    snapshot = _snapshot(source)
    source["response_format"] = {"type": "text"}

    assert snapshot.to_dict()["parameters"] == {"response_format": {"type": "json_object"}}


def test_snapshot_rejects_secret_bearing_parameters() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        _snapshot({"headers": {"authorization": "Bearer private"}})
    assert caught.value.code == "domain_secret_forbidden"


def test_snapshot_rejects_non_json_values_and_bad_fingerprint() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        _snapshot({"temperature": object()})
    assert caught.value.code == "domain_field_invalid"

    payload = _snapshot().to_dict()
    payload["request_content_fingerprint"] = "not-a-sha256"
    with pytest.raises(DomainSchemaError) as caught:
        ModelInvocationSnapshot.from_dict(payload)
    assert caught.value.code == "domain_field_invalid"
```

- [ ] **Step 2: Run the focused snapshot test and confirm it fails**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_invocation_v1.py -q
```

Expected: collection fails because `cs2pov.domain.invocation` does not exist.

- [ ] **Step 3: Implement an immutable, JSON-only, non-secret snapshot**

Implement `invocation.py` with these policies:

- all identity/version fields are non-empty strings; ID fields use `require_identifier`;
- `request_content_fingerprint` is exactly lower-case SHA-256;
- parameters recursively accept only `None`, `bool`, finite `int`/`float`, `str`, lists, and dictionaries with string keys;
- copy parameters into an immutable internal representation on construction and return fresh JSON-compatible containers from `to_dict`, so caller mutation cannot alter the snapshot;
- call `reject_secret_keys` before storage;
- emit no base URL, API key, credential value, request text, SteamID, or filesystem path;
- reject missing/unknown keys and unsupported schema versions.

- [ ] **Step 4: Run schema and invocation tests**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_schema_v1.py tests/test_domain_invocation_v1.py -q
```

Expected: both files pass.

- [ ] **Step 5: Commit the invocation snapshot**

```powershell
git add src/cs2pov/domain/invocation.py tests/test_domain_invocation_v1.py
git commit -m "feat: add safe model invocation snapshots"
```

---

### Task 5: Immutable transcript and understanding-result contracts

**Files:**
- Create: `src/cs2pov/domain/voice.py`
- Create: `src/cs2pov/domain/transcript.py`
- Create: `src/cs2pov/domain/understanding.py`
- Create: `tests/test_domain_understanding_v1.py`

**Interfaces:**
- Consumes: `TimeRange`, current schema validators, and SHA-256/identifier helpers.
- Produces: `VoiceActivityCue(activity_id, player_id, time_range, packet_count, anchor_ids, uncertainty_us)`.
- Produces: `TranscriptCue(cue_id, player_id, round_id, time_range, asr_original, language, confidence, anchor_ids, voice_activity_ids, asr_invocation_snapshot_id)`.
- Produces: `UnderstandingResult(cue_id, round_id, asr_original, interpreted_source, translated_zh, confidence, evidence, warnings, model_invocation_snapshot_id)`.
- Produces: `RoundUnderstandingDocument(round_id, input_fingerprint, model_invocation_snapshot_id, results)`.
- Produces: `validate_understanding_against_transcript(result, cue) -> None`.

- [ ] **Step 1: Write failing three-layer meaning and source-integrity tests**

Create `tests/test_domain_understanding_v1.py`:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.timebase import TimeRange
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.voice import VoiceActivityCue
from cs2pov.domain.understanding import (
    RoundUnderstandingDocument,
    UnderstandingResult,
    validate_understanding_against_transcript,
)


def _cue() -> TranscriptCue:
    return TranscriptCue(
        cue_id="cue-b-callout",
        player_id="player-bravo",
        round_id="round-002",
        time_range=TimeRange(20_500_000, 21_700_000),
        asr_original="be be be",
        language="en",
        confidence=0.62,
        anchor_ids=("anchor-bravo-001",),
        voice_activity_ids=("activity-bravo-001",),
        asr_invocation_snapshot_id="asr-001",
    )


def _result() -> UnderstandingResult:
    return UnderstandingResult(
        cue_id="cue-b-callout",
        round_id="round-002",
        asr_original="be be be",
        interpreted_source="B, B, B",
        translated_zh="B点，B点，B点",
        confidence=0.86,
        evidence=("same-round-context", "case-letter-b-v1"),
        warnings=(),
        model_invocation_snapshot_id="invoke-001",
    )


def test_transcript_jsonl_record_preserves_original_asr_and_integer_time() -> None:
    cue = _cue()
    payload = cue.to_dict()

    assert payload["schema_version"] == 1
    assert payload["asr_original"] == "be be be"
    assert payload["start_us"] == 20_500_000
    assert isinstance(payload["start_us"], int)
    assert TranscriptCue.from_dict(payload) == cue


def test_voice_activity_jsonl_record_preserves_anchor_evidence() -> None:
    activity = VoiceActivityCue(
        activity_id="activity-bravo-001",
        player_id="player-bravo",
        time_range=TimeRange(20_500_000, 21_700_000),
        packet_count=12,
        anchor_ids=("anchor-bravo-001",),
        uncertainty_us=16_000,
    )
    payload = activity.to_dict()

    assert payload["schema_version"] == 1
    assert payload["start_us"] == 20_500_000
    assert payload["anchor_ids"] == ["anchor-bravo-001"]
    assert VoiceActivityCue.from_dict(payload) == activity


def test_understanding_keeps_asr_interpretation_and_translation_separate() -> None:
    result = _result()
    payload = result.to_dict()

    assert payload["asr_original"] == "be be be"
    assert payload["interpreted_source"] == "B, B, B"
    assert payload["translated_zh"] == "B点，B点，B点"
    assert UnderstandingResult.from_dict(payload) == result
    validate_understanding_against_transcript(result, _cue())


def test_understanding_cannot_silently_change_source_cue() -> None:
    payload = _result().to_dict()
    payload["asr_original"] = "B B B"
    changed = UnderstandingResult.from_dict(payload)

    with pytest.raises(DomainSchemaError) as caught:
        validate_understanding_against_transcript(changed, _cue())
    assert caught.value.code == "cue_reference_invalid"


def test_round_document_requires_one_result_per_cue_and_matching_round() -> None:
    document = RoundUnderstandingDocument(
        round_id="round-002",
        input_fingerprint="b" * 64,
        model_invocation_snapshot_id="invoke-001",
        results=(_result(),),
    )
    assert RoundUnderstandingDocument.from_dict(document.to_dict()) == document

    with pytest.raises(DomainSchemaError) as caught:
        RoundUnderstandingDocument(
            round_id="round-001",
            input_fingerprint="b" * 64,
            model_invocation_snapshot_id="invoke-001",
            results=(_result(),),
        )
    assert caught.value.code == "round_reference_invalid"


def test_empty_interpretation_translation_or_evidence_is_invalid() -> None:
    for field in ("interpreted_source", "translated_zh"):
        payload = _result().to_dict()
        payload[field] = ""
        with pytest.raises(DomainSchemaError) as caught:
            UnderstandingResult.from_dict(payload)
        assert caught.value.code == "domain_field_invalid"

    payload = _result().to_dict()
    payload["evidence"] = []
    with pytest.raises(DomainSchemaError) as caught:
        UnderstandingResult.from_dict(payload)
    assert caught.value.code == "domain_field_invalid"
```

- [ ] **Step 2: Run the focused tests and confirm missing-module failures**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_understanding_v1.py -q
```

Expected: collection fails because voice/transcript/understanding modules do not exist.

- [ ] **Step 3: Implement immutable source and interpretation contracts**

Implement the three modules with exact-key `to_dict`/`from_dict` factories. Apply these rules:

- cue and round/player/snapshot/anchor IDs use safe identifiers;
- voice activity has a positive packet count, at least one anchor ID, and non-negative uncertainty;
- `TranscriptCue.asr_original` is non-empty and frozen;
- confidence is optional only on `TranscriptCue`; `UnderstandingResult.confidence` is required;
- one cue has one contiguous Demo `TimeRange`; adapters receiving discontinuous `MappedTime` must split or warn before creating a cue;
- evidence is a non-empty tuple of non-empty strings; warnings may be empty;
- `RoundUnderstandingDocument` results have unique cue IDs, all reference its round, and all reference its frozen model snapshot;
- source validation compares cue ID, round ID, and exact `asr_original` without normalization or rewriting.

The four durable shapes use these exact keys:

```json
{"schema_version": 1, "activity_id": "activity-bravo-001", "player_id": "player-bravo", "start_us": 20500000, "end_us": 21700000, "packet_count": 12, "anchor_ids": ["anchor-bravo-001"], "uncertainty_us": 16000}
```

```json
{"schema_version": 1, "cue_id": "cue-b-callout", "player_id": "player-bravo", "round_id": "round-002", "start_us": 20500000, "end_us": 21700000, "asr_original": "be be be", "language": "en", "confidence": 0.62, "anchor_ids": ["anchor-bravo-001"], "voice_activity_ids": ["activity-bravo-001"], "asr_invocation_snapshot_id": "asr-001"}
```

```json
{"schema_version": 1, "cue_id": "cue-b-callout", "round_id": "round-002", "asr_original": "be be be", "interpreted_source": "B, B, B", "translated_zh": "B点，B点，B点", "confidence": 0.86, "evidence": ["same-round-context"], "warnings": [], "model_invocation_snapshot_id": "invoke-001"}
```

The RoundUnderstandingDocument top level has exactly `schema_version`, `round_id`, `input_fingerprint`, `model_invocation_snapshot_id`, and `results`; `results` must contain at least one full UnderstandingResult dictionary in its tested serialized shape.

- [ ] **Step 4: Run transcript/understanding and timebase tests**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_timebase_v1.py tests/test_domain_understanding_v1.py -q
```

Expected: both files pass.

- [ ] **Step 5: Commit transcript and understanding contracts**

```powershell
git add src/cs2pov/domain/voice.py src/cs2pov/domain/transcript.py src/cs2pov/domain/understanding.py tests/test_domain_understanding_v1.py
git commit -m "feat: add transcript and understanding contracts"
```

---

### Task 6: Typed human review and final timeline contracts

**Files:**
- Create: `src/cs2pov/domain/review.py`
- Create: `tests/test_domain_review_v1.py`

**Interfaces:**
- Consumes: `TimeRange`, `UnderstandingResult`, identifiers, SHA-256, and current schema helpers.
- Produces: `ReviewAction` values `ACCEPT`, `EDIT`, and `EXCLUDE`.
- Produces: `ReviewDecision(decision_id, cue_id, source_result_fingerprint, action, reviewed_at, reviewer_label, reason, revised_time_range, revised_interpreted_source, revised_translated_zh)`.
- Produces: `DraftCommsCue` and `ReviewedCommsCue` preserving source, interpreted, and translated layers.
- Produces: `DraftCommsTimeline` and `ReviewedCommsTimeline` with explicit `timebase` and deterministic ordering validation.

- [ ] **Step 1: Write failing review action, preservation, and timebase tests**

Create `tests/test_domain_review_v1.py` with the following core cases:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.review import (
    DraftCommsCue,
    DraftCommsTimeline,
    ReviewAction,
    ReviewDecision,
    ReviewedCommsCue,
    ReviewedCommsTimeline,
)
from cs2pov.domain.timebase import TimeRange


def _draft(cue_id: str = "cue-b-callout", start_us: int = 20_500_000) -> DraftCommsCue:
    return DraftCommsCue(
        cue_id=cue_id,
        round_id="round-002",
        player_id="player-bravo",
        time_range=TimeRange(start_us, start_us + 1_200_000),
        asr_original="be be be",
        interpreted_source="B, B, B",
        translated_zh="B点，B点，B点",
        confidence=0.86,
        evidence=("same-round-context",),
        understanding_result_fingerprint="c" * 64,
    )


def test_accept_decision_cannot_smuggle_revised_content() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        ReviewDecision(
            decision_id="decision-001",
            cue_id="cue-b-callout",
            source_result_fingerprint="c" * 64,
            action=ReviewAction.ACCEPT,
            reviewed_at="2026-08-31T12:00:00+00:00",
            reviewer_label="local-user",
            reason=None,
            revised_time_range=None,
            revised_interpreted_source=None,
            revised_translated_zh="被偷偷替换",
        )
    assert caught.value.code == "review_decision_invalid"


def test_edit_requires_a_change_and_exclude_requires_reason() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        ReviewDecision(
            decision_id="decision-001",
            cue_id="cue-b-callout",
            source_result_fingerprint="c" * 64,
            action=ReviewAction.EDIT,
            reviewed_at="2026-08-31T12:00:00+00:00",
            reviewer_label="local-user",
            reason="修正点位呼叫",
            revised_time_range=None,
            revised_interpreted_source=None,
            revised_translated_zh=None,
        )
    assert caught.value.code == "review_decision_invalid"

    with pytest.raises(DomainSchemaError) as caught:
        ReviewDecision(
            decision_id="decision-002",
            cue_id="cue-b-callout",
            source_result_fingerprint="c" * 64,
            action=ReviewAction.EXCLUDE,
            reviewed_at="2026-08-31T12:00:00+00:00",
            reviewer_label="local-user",
            reason=None,
            revised_time_range=None,
            revised_interpreted_source=None,
            revised_translated_zh=None,
        )
    assert caught.value.code == "review_decision_invalid"


def test_reviewed_cue_preserves_original_and_records_final_values() -> None:
    draft = _draft()
    decision = ReviewDecision(
        decision_id="decision-001",
        cue_id=draft.cue_id,
        source_result_fingerprint=draft.understanding_result_fingerprint,
        action=ReviewAction.EDIT,
        reviewed_at="2026-08-31T12:00:00+00:00",
        reviewer_label="local-user",
        reason="将呼叫翻译调整为更自然的中文",
        revised_time_range=None,
        revised_interpreted_source=None,
        revised_translated_zh="B点！B点！B点！",
    )
    cue = ReviewedCommsCue.from_draft_and_decision(draft, decision)

    assert cue.asr_original == "be be be"
    assert cue.interpreted_source == "B, B, B"
    assert cue.model_translated_zh == "B点，B点，B点"
    assert cue.model_confidence == 0.86
    assert cue.evidence == ("same-round-context",)
    assert cue.final_translated_zh == "B点！B点！B点！"
    assert cue.review_decision_id == "decision-001"


def test_timeline_requires_explicit_demo_timebase_and_sorted_cues() -> None:
    first = _draft("cue-first", 20_500_000)
    second = _draft("cue-second", 22_000_000)
    timeline = DraftCommsTimeline(
        demo_asset_id="a" * 64,
        timebase="demo-microseconds",
        input_fingerprint="d" * 64,
        cues=(first, second),
    )
    assert DraftCommsTimeline.from_dict(timeline.to_dict()) == timeline

    with pytest.raises(DomainSchemaError) as caught:
        DraftCommsTimeline(
            demo_asset_id="a" * 64,
            timebase="round-local-milliseconds",
            input_fingerprint="d" * 64,
            cues=(first, second),
        )
    assert caught.value.code == "timeline_invalid"


    with pytest.raises(DomainSchemaError) as caught:
        DraftCommsTimeline(
            demo_asset_id="a" * 64,
            timebase="demo-microseconds",
            input_fingerprint="d" * 64,
            cues=(second, first),
        )
    assert caught.value.code == "timeline_invalid"


def test_reviewed_timeline_round_trips_and_rejects_duplicate_cues() -> None:
    draft = _draft()
    decision = ReviewDecision(
        decision_id="decision-001",
        cue_id=draft.cue_id,
        source_result_fingerprint=draft.understanding_result_fingerprint,
        action=ReviewAction.ACCEPT,
        reviewed_at="2026-08-31T12:00:00+00:00",
        reviewer_label="local-user",
        reason=None,
        revised_time_range=None,
        revised_interpreted_source=None,
        revised_translated_zh=None,
    )
    reviewed = ReviewedCommsCue.from_draft_and_decision(draft, decision)
    timeline = ReviewedCommsTimeline(
        demo_asset_id="a" * 64,
        timebase="demo-microseconds",
        source_draft_fingerprint="d" * 64,
        cues=(reviewed,),
        excluded_decision_ids=(),
    )

    assert ReviewedCommsTimeline.from_dict(timeline.to_dict()) == timeline

    with pytest.raises(DomainSchemaError) as caught:
        ReviewedCommsTimeline(
            demo_asset_id="a" * 64,
            timebase="demo-microseconds",
            source_draft_fingerprint="d" * 64,
            cues=(reviewed, reviewed),
            excluded_decision_ids=(),
        )
    assert caught.value.code == "timeline_invalid"
```

- [ ] **Step 2: Run the focused review test and confirm it fails**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_review_v1.py -q
```

Expected: collection fails because `cs2pov.domain.review` does not exist.

- [ ] **Step 3: Implement typed decisions and immutable draft/reviewed timelines**

Apply these exact policies:

- parse `reviewed_at` with `datetime.fromisoformat`, require a timezone-aware timestamp, and serialize the original normalized ISO text;
- `ACCEPT` permits no revision fields; `EDIT` requires at least one revised field; `EXCLUDE` permits no revisions and requires a non-empty reason;
- every decision fingerprint must match the draft result fingerprint before composition;
- `ReviewedCommsCue` retains ASR original, interpreted source, and model translation even when final time/text changes;
- excluded cues do not appear in reviewed cues but their decision IDs are retained in `excluded_decision_ids`;
- timeline timebase is exactly `demo-microseconds`; per-round/local export timebases are later exporter manifests, not stored as core truth;
- draft/reviewed timeline `demo_asset_id` values use `require_sha256`;
- cue IDs are unique, cues are sorted by `(start_us, end_us, cue_id)`, and all serialized documents reject unknown keys and unsupported versions.

Use these exact top-level keys:

- ReviewDecision JSONL record: `schema_version`, `decision_id`, `cue_id`, `source_result_fingerprint`, `action`, `reviewed_at`, `reviewer_label`, `reason`, `revised_start_us`, `revised_end_us`, `revised_interpreted_source`, `revised_translated_zh`.
- Draft timeline document: `schema_version`, `demo_asset_id`, `timebase`, `input_fingerprint`, `cues`.
- Each draft cue: `cue_id`, `round_id`, `player_id`, `start_us`, `end_us`, `asr_original`, `interpreted_source`, `translated_zh`, `confidence`, `evidence`, `understanding_result_fingerprint`.
- Reviewed timeline document: `schema_version`, `demo_asset_id`, `timebase`, `source_draft_fingerprint`, `cues`, `excluded_decision_ids`.
- Each reviewed cue: `cue_id`, `round_id`, `player_id`, `start_us`, `end_us`, `asr_original`, `interpreted_source`, `model_translated_zh`, `model_confidence`, `evidence`, `final_interpreted_source`, `final_translated_zh`, `review_decision_id`.

- [ ] **Step 4: Run review, understanding, and timebase tests**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_timebase_v1.py tests/test_domain_understanding_v1.py tests/test_domain_review_v1.py -q
```

Expected: all three files pass.

- [ ] **Step 5: Commit the review contracts**

```powershell
git add src/cs2pov/domain/review.py tests/test_domain_review_v1.py
git commit -m "feat: add human review timeline contracts"
```

---

### Task 7: Deterministic three-round contract replay and documentation

**Files:**
- Create: `tests/golden/fixtures/new_domain_contract_v1.json`
- Create: `scripts/check_new_domain_contract.py`
- Create: `tests/test_new_domain_contract_replay.py`
- Modify: `docs/ARCHITECTURE.zh.md`
- Modify: `docs/TESTING_GUIDE.zh.md`
- Modify: `tests/golden/README.zh.md`

**Interfaces:**
- Consumes: every domain type from Tasks 1–6.
- Produces: one checked-in, anonymous, deterministic contract fixture and one subprocess-replay command.
- Produces: stable success line `new domain contract replay passed`.

- [ ] **Step 1: Add a failing subprocess replay test before the script exists**

Create `tests/test_new_domain_contract_replay.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_new_domain_contract_replays_in_a_fresh_python_process() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_new_domain_contract.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "new domain contract replay passed"
    assert result.stderr == ""
```

- [ ] **Step 2: Run the subprocess test and confirm the missing-script failure**

Run:

```powershell
py -3.12 -m pytest tests/test_new_domain_contract_replay.py -q
```

Expected: FAIL because `scripts/check_new_domain_contract.py` does not exist.

- [ ] **Step 3: Create the anonymous three-round fixture from one exact object graph**

Create `tests/golden/fixtures/new_domain_contract_v1.json` by serializing the following normative object graph with `ensure_ascii=False`, `indent=2`, and one trailing newline. Use `apply_patch` to add the literal generated JSON; do not add a fixture-generation dependency or runtime write path.

```python
descriptor = DemoDescriptor(
    demo_asset_id="a" * 64,
    map_name="de_mirage",
    server_name="fixture-server",
    tick_rate_numerator=64,
    tick_rate_denominator=1,
    players=(PlayerSnapshot("player-alpha", "Alpha", 2), PlayerSnapshot("player-bravo", "Bravo", 2)),
)
rounds = RoundCollection((
    Round("round-001", 1, TimeRange(10_000_000, 20_000_000), 640, 1280, False, "synthetic-round-parser-v1", RoundBoundaryConfidence.EXACT),
    Round("round-002", 2, TimeRange(20_000_000, 30_000_000), 1280, 1920, False, "synthetic-round-parser-v1", RoundBoundaryConfidence.EXACT),
    Round("round-003", 3, TimeRange(30_000_000, 40_000_000), 1920, 2560, False, "synthetic-round-parser-v1", RoundBoundaryConfidence.EXACT),
))
anchors = (
    TimeAnchor("anchor-demo-ticks", SourceClock.DEMO_TICK, "demo", 640, 2560, TimeRange(10_000_000, 40_000_000), 0, "synthetic-round-parser-v1"),
    TimeAnchor("anchor-alpha-001", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 0, 24_000, TimeRange(10_500_000, 11_500_000), 16_000, "synthetic-voice-extractor-v1"),
    TimeAnchor("anchor-alpha-002", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 24_000, 48_000, TimeRange(20_000_000, 21_000_000), 16_000, "synthetic-voice-extractor-v1"),
    TimeAnchor("anchor-alpha-003", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 48_000, 67_200, TimeRange(30_500_000, 31_300_000), 16_000, "synthetic-voice-extractor-v1"),
    TimeAnchor("anchor-bravo-001", SourceClock.COMPACT_AUDIO_SAMPLE, "player-bravo", 0, 28_800, TimeRange(20_500_000, 21_700_000), 16_000, "synthetic-voice-extractor-v1"),
)
invocation = ModelInvocationSnapshot(
    "invoke-001", "openai-compatible", "provider-local-profile", "fixture-model", "understanding-v1",
    {"temperature": 0.2, "max_tokens": 512}, ("knowledge-global-001",), "adapter-v1", "a" * 64,
)
voice_activities = (
    VoiceActivityCue("activity-alpha-001", "player-alpha", TimeRange(10_750_000, 11_250_000), 8, ("anchor-alpha-001",), 16_000),
    VoiceActivityCue("activity-bravo-001", "player-bravo", TimeRange(20_500_000, 21_700_000), 12, ("anchor-bravo-001",), 16_000),
    VoiceActivityCue("activity-alpha-002", "player-alpha", TimeRange(20_650_000, 20_950_000), 5, ("anchor-alpha-002",), 16_000),
    VoiceActivityCue("activity-alpha-003", "player-alpha", TimeRange(30_500_000, 31_300_000), 7, ("anchor-alpha-003",), 16_000),
)
transcripts = (
    TranscriptCue("cue-first", "player-alpha", "round-001", TimeRange(10_750_000, 11_250_000), "one jungle", "en", 0.91, ("anchor-alpha-001",), ("activity-alpha-001",), "asr-001"),
    TranscriptCue("cue-b-callout", "player-bravo", "round-002", TimeRange(20_500_000, 21_700_000), "be be be", "en", 0.62, ("anchor-bravo-001",), ("activity-bravo-001",), "asr-001"),
    TranscriptCue("cue-overlap", "player-alpha", "round-002", TimeRange(20_650_000, 20_950_000), "two short", "en", 0.84, ("anchor-alpha-002",), ("activity-alpha-002",), "asr-001"),
    TranscriptCue("cue-third", "player-alpha", "round-003", TimeRange(30_500_000, 31_300_000), "save awp", "en", 0.88, ("anchor-alpha-003",), ("activity-alpha-003",), "asr-001"),
)
results = (
    UnderstandingResult("cue-first", "round-001", "one jungle", "one jungle", "警家一个", 0.93, ("same-round-context",), (), "invoke-001"),
    UnderstandingResult("cue-b-callout", "round-002", "be be be", "B, B, B", "B点，B点，B点", 0.86, ("same-round-context", "case-letter-b-v1"), (), "invoke-001"),
    UnderstandingResult("cue-overlap", "round-002", "two short", "two short", "短箱两个", 0.88, ("same-round-context",), (), "invoke-001"),
    UnderstandingResult("cue-third", "round-003", "save awp", "save AWP", "保大狙", 0.9, ("same-round-context",), (), "invoke-001"),
)
round_documents = (
    RoundUnderstandingDocument("round-001", "1" * 64, "invoke-001", (results[0],)),
    RoundUnderstandingDocument("round-002", "2" * 64, "invoke-001", (results[1], results[2])),
    RoundUnderstandingDocument("round-003", "3" * 64, "invoke-001", (results[3],)),
)
draft_cues = (
    DraftCommsCue("cue-first", "round-001", "player-alpha", TimeRange(10_750_000, 11_250_000), "one jungle", "one jungle", "警家一个", 0.93, ("same-round-context",), "e" * 64),
    DraftCommsCue("cue-b-callout", "round-002", "player-bravo", TimeRange(20_500_000, 21_700_000), "be be be", "B, B, B", "B点，B点，B点", 0.86, ("same-round-context", "case-letter-b-v1"), "c" * 64),
    DraftCommsCue("cue-overlap", "round-002", "player-alpha", TimeRange(20_650_000, 20_950_000), "two short", "two short", "短箱两个", 0.88, ("same-round-context",), "b" * 64),
    DraftCommsCue("cue-third", "round-003", "player-alpha", TimeRange(30_500_000, 31_300_000), "save awp", "save AWP", "保大狙", 0.9, ("same-round-context",), "f" * 64),
)
decisions = (
    ReviewDecision("decision-first", "cue-first", "e" * 64, ReviewAction.ACCEPT, "2026-08-31T12:00:00+00:00", "local-user", None, None, None, None),
    ReviewDecision("decision-b-callout", "cue-b-callout", "c" * 64, ReviewAction.EDIT, "2026-08-31T12:01:00+00:00", "local-user", "将呼叫翻译调整为更自然的中文", None, None, "B点！B点！B点！"),
    ReviewDecision("decision-overlap", "cue-overlap", "b" * 64, ReviewAction.ACCEPT, "2026-08-31T12:02:00+00:00", "local-user", None, None, None, None),
    ReviewDecision("decision-third", "cue-third", "f" * 64, ReviewAction.ACCEPT, "2026-08-31T12:03:00+00:00", "local-user", None, None, None, None),
)
reviewed_cues = tuple(
    ReviewedCommsCue.from_draft_and_decision(draft, decision)
    for draft, decision in zip(draft_cues, decisions, strict=True)
)
draft_timeline = DraftCommsTimeline("a" * 64, "demo-microseconds", "d" * 64, draft_cues)
reviewed_timeline = ReviewedCommsTimeline("a" * 64, "demo-microseconds", "d" * 64, reviewed_cues, ())
payload = {
    "schema_version": 1,
    "fixture_id": "new-domain-three-round-v1",
    "demo": descriptor.to_dict(),
    "rounds": rounds.to_dict(),
    "time_anchors": [item.to_dict() for item in anchors],
    "invocation_snapshot": invocation.to_dict(),
    "voice_activities": [item.to_dict() for item in voice_activities],
    "transcript_cues": [item.to_dict() for item in transcripts],
    "round_understanding": [item.to_dict() for item in round_documents],
    "review_decisions": [item.to_dict() for item in decisions],
    "draft_timeline": draft_timeline.to_dict(),
    "reviewed_timeline": reviewed_timeline.to_dict(),
    "round_completion_order": ["round-003", "round-001", "round-002"],
    "expected": {
        "round_ids": ["round-001", "round-002", "round-003"],
        "b_callout_cue_id": "cue-b-callout",
        "asr_original": "be be be",
        "interpreted_source": "B, B, B",
        "final_translated_zh": "B点！B点！B点！",
        "reviewed_cue_order": ["cue-first", "cue-b-callout", "cue-overlap", "cue-third"],
    },
}
```

The fixture must contain no SteamID, absolute path, URL, API key, credential, real Demo hash, or private media.

- [ ] **Step 4: Implement the standalone replay validator**

Create `scripts/check_new_domain_contract.py` that:

1. resolves the fixture relative to repository root;
2. loads JSON as UTF-8 and requires exact transport keys and transport `schema_version == 1`;
3. reconstructs all production domain objects exclusively through their `from_dict` factories;
4. validates every VoiceActivityCue anchor/player reference and every TranscriptCue activity/anchor/player reference;
5. validates each UnderstandingResult against its TranscriptCue;
6. builds `DemoTimeline` and checks all cue round references;
7. checks the B callout source/interpretation/final translation against `expected`;
8. checks reviewed cues are in expected Demo-time order despite the declared completion order;
9. recursively rejects dictionary keys `path`, `steamid`, `steam_id`, `api_key`, `authorization`, `access_token`, `password`, and `secret`;
10. recursively rejects string values beginning with a Windows drive, `/`, `\\`, `http://`, or `https://`;
11. prints exactly `new domain contract replay passed` on success and returns 0; on validation failure it prints one concise line to stderr and returns 1 without a traceback.

Keep a callable `validate_contract(path: Path) -> None` so the test suite can add focused tamper cases later.

- [ ] **Step 5: Run the fresh-process replay test and direct script**

Run:

```powershell
py -3.12 -m pytest tests/test_new_domain_contract_replay.py -q
py -3.12 scripts/check_new_domain_contract.py
```

Expected: test passes and direct script prints the unique success line.

- [ ] **Step 6: Document the isolated core and its verification command**

Update `docs/ARCHITECTURE.zh.md` with a section titled `新版领域与统一时间内核（02A）` that states:

- the new modules are isolated contracts and are not yet wired to Pipeline;
- Demo microseconds are canonical and source clocks use segmented anchors;
- original ASR, interpretation, translation, and review remain separate;
- old Job migration and cross-version compatibility are not implemented.

Update `docs/TESTING_GUIDE.zh.md` with:

```powershell
py -3.12 scripts/check_new_domain_contract.py
```

State that it uses anonymous JSON only and needs no CS2/GPU/model/API. Update `tests/golden/README.zh.md` to say `structured_timeline_v1.json` remains the frozen v0.9.8 baseline while `new_domain_contract_v1.json` validates the new current-version contract and must not be presented as legacy output equivalence.

- [ ] **Step 7: Run documentation, fixture, and focused tests**

Run:

```powershell
git diff --check
py -3.12 -m pytest tests/test_domain_schema_v1.py tests/test_domain_timebase_v1.py tests/test_domain_timeline_v1.py tests/test_domain_invocation_v1.py tests/test_domain_understanding_v1.py tests/test_domain_review_v1.py tests/test_new_domain_contract_replay.py -q
py -3.12 scripts/check_new_domain_contract.py
py -3.12 scripts/check_repository_hygiene.py
```

Expected: every command exits 0; the replay script prints its unique success line; hygiene reports pass.

- [ ] **Step 8: Commit the contract fixture and documentation**

```powershell
git add tests/golden/fixtures/new_domain_contract_v1.json scripts/check_new_domain_contract.py tests/test_new_domain_contract_replay.py docs/ARCHITECTURE.zh.md docs/TESTING_GUIDE.zh.md tests/golden/README.zh.md
git commit -m "test: gate new domain contract replay"
```

---

### Task 8: Full batch verification and handoff evidence

**Files:**
- Modify only if verification exposes a 02A defect: files already introduced in Tasks 1–7.
- Do not add unrelated refactors, compatibility shims, or Pipeline wiring during this task.

**Interfaces:**
- Consumes: the complete 02A implementation.
- Produces: reviewable evidence for strong-model code review and GitHub PR gating.

- [ ] **Step 1: Run compile, full tests, golden replay, new contract replay, and hygiene**

Run each command separately and preserve its exit code/output in the implementation handoff:

```powershell
py -3.12 -m compileall -q src scripts tests
py -3.12 -m pytest -q
py -3.12 scripts/check_golden_baseline.py --replay
py -3.12 scripts/check_new_domain_contract.py
py -3.12 scripts/check_repository_hygiene.py
git diff --check master...HEAD
```

Expected:

- compileall exits 0;
- the full existing and new suite has zero failures;
- frozen v0.9.8 golden replay still reports 15 passed;
- new contract prints `new domain contract replay passed`;
- hygiene passes;
- no whitespace errors are reported.

- [ ] **Step 2: Verify scope and forbidden work with repository searches**

Run:

```powershell
git diff --name-only master...HEAD
rg -n "start_time|end_time" src/cs2pov/domain/errors.py src/cs2pov/domain/schema.py src/cs2pov/domain/timebase.py src/cs2pov/domain/timeline.py src/cs2pov/domain/invocation.py src/cs2pov/domain/voice.py src/cs2pov/domain/transcript.py src/cs2pov/domain/understanding.py src/cs2pov/domain/review.py
rg -n "api_key|authorization|access_token|password" tests/golden/fixtures/new_domain_contract_v1.json
```

Expected:

- changed production files are limited to the nine new domain modules;
- no new domain serialization field uses ambiguous `start_time`/`end_time` (method names or explanatory comments must be reviewed manually if matched);
- the anonymous fixture contains no secret-bearing keys;
- `src/cs2pov/pipeline/engine.py`, CLI files, existing `domain/models.py`, and storage code are unchanged.

- [ ] **Step 3: Prepare the implementation handoff for independent review**

The handoff must list:

- commit hashes for Tasks 1–7;
- exact verification commands and fresh results;
- all stable error codes added;
- any deliberate difference from the plan with technical evidence;
- confirmation that old Job migration, cross-version migration, Pipeline integration, Web UI, and POV recording were not implemented.

Do not claim 02A complete until an independent strong-model review has checked the diff against the spec and this plan and all Critical/Important findings are resolved.
