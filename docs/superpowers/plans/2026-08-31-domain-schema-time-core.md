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
- Job/domain objects never store API keys, authorization headers, passwords, external absolute paths, URLs, or user-home paths; all direct constructors and `from_dict` factories enforce the same production privacy helper.
- No new runtime dependency is allowed in 02A.
- All tests must work without CS2, GPU, FFmpeg, Whisper, a real Demo, network access, or a paid model API.
- CI compatibility remains Ubuntu Python 3.11/3.12/3.13 and Windows Python 3.12, including repository paths containing Chinese characters and spaces.

## File Structure

New production files:

- `src/cs2pov/domain/errors.py`: stable domain error object with user-facing Chinese message and action.
- `src/cs2pov/domain/schema.py`: schema/version, exact-key, scalar, identifier, SHA-256, and secret-key validation helpers.
- `src/cs2pov/domain/fingerprint.py`: canonical JSON encoding and derived SHA-256 content fingerprints.
- `src/cs2pov/domain/timebase.py`: integer Demo ranges, source clocks, segmented anchors, source-to-Demo mapping, round-local conversion, and export rounding.
- `src/cs2pov/domain/timeline.py`: player snapshots, Demo descriptor, rounds, round collection, and validated in-memory Demo timeline aggregate.
- `src/cs2pov/domain/invocation.py`: non-secret shared model configuration snapshots and per-call invocation records.
- `src/cs2pov/domain/voice.py`: immutable integer-time voice-activity JSONL record.
- `src/cs2pov/domain/transcript.py`: immutable ASR `TranscriptCue` JSONL record.
- `src/cs2pov/domain/understanding.py`: interpretation result and per-round understanding document.
- `src/cs2pov/domain/review.py`: typed human decisions plus draft/reviewed timeline contracts.
- `src/cs2pov/domain/validation.py`: reusable cross-object reference, time-containment, and provenance validation.

New tests and fixtures:

- `tests/test_domain_schema_v1.py`
- `tests/test_domain_timebase_v1.py`
- `tests/test_domain_timeline_v1.py`
- `tests/test_domain_invocation_v1.py`
- `tests/test_domain_understanding_v1.py`
- `tests/test_domain_review_v1.py`
- `tests/test_domain_validation_v1.py`
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
- Create: `src/cs2pov/domain/fingerprint.py`
- Create: `tests/test_domain_schema_v1.py`

**Interfaces:**
- Produces: `DomainSchemaError(code: str, message: str, action: str, path: str | None = None)`.
- Produces: `CURRENT_DOMAIN_SCHEMA_VERSION: Final[int] = 1`.
- Produces: `MAX_DEMO_TIME_US = 2_592_000_000_000`, `MAX_SOURCE_POSITION = 9_223_372_036_854_775_807`, and `MAX_COUNT = 2_147_483_647`.
- Produces: `require_mapping`, `require_exact_keys`, `require_current_schema`, `require_int`, `require_optional_int`, `require_str`, `require_optional_str`, `require_identifier`, `require_sha256`, `require_probability`, `require_string_list`, `reject_secret_keys`, and `reject_private_data`.
- Produces: `canonical_json_bytes(value: object) -> bytes` and `content_fingerprint(value: object) -> str`.
- All later `from_dict` factories depend on these exact helpers and error codes.

Use these signatures throughout the batch:

```python
def require_mapping(value: object, path: str) -> Mapping[str, object]
def require_exact_keys(data: Mapping[str, object], required: set[str], optional: set[str], path: str) -> None
def require_current_schema(data: Mapping[str, object], path: str) -> int
def require_int(value: object, path: str, *, minimum: int | None = None, maximum: int | None = None) -> int
def require_optional_int(value: object, path: str, *, minimum: int | None = None, maximum: int | None = None) -> int | None
def require_str(value: object, path: str, *, allow_empty: bool = False) -> str
def require_optional_str(value: object, path: str, *, allow_empty: bool = False) -> str | None
def require_identifier(value: object, path: str) -> str
def require_sha256(value: object, path: str) -> str
def require_probability(value: object, path: str) -> float
def require_string_list(value: object, path: str, *, allow_empty: bool = True) -> tuple[str, ...]
def reject_secret_keys(value: object, path: str) -> None
def reject_private_data(value: object, path: str) -> None
```

- [ ] **Step 1: Write failing tests for error shape and strict scalar validation**

Create `tests/test_domain_schema_v1.py` with these cases:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import canonical_json_bytes, content_fingerprint
from cs2pov.domain.schema import (
    CURRENT_DOMAIN_SCHEMA_VERSION,
    MAX_DEMO_TIME_US,
    reject_private_data,
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

    for value in ("", ".", "..", "CON", "nul.txt", "COM1", "round/1", "round\\1", "B 点", "x" * 129):
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
        {"x-api-key": "secret"},
        {"headers": {"authorization": "Bearer secret"}},
        {"headers": {"proxy-authorization": "Basic secret"}},
        {"credentials": [{"access_token": "secret"}]},
        {"refresh_token": "secret"},
        {"client_secret": "secret"},
        {"password": "secret"},
    ):
        with pytest.raises(DomainSchemaError) as caught:
            reject_secret_keys(payload, "parameters")
        assert caught.value.code == "domain_secret_forbidden"


def test_durable_privacy_scan_rejects_absolute_locations_and_urls() -> None:
    reject_private_data({"text": "B, B, B", "model": "org/model-name"}, "document")

    for value in (
        r"C:\Users\private\demo.dem",
        "/home/private/demo.dem",
        r"\\server\share\demo.dem",
        "https://private.example/api",
        "~/private/demo.dem",
    ):
        with pytest.raises(DomainSchemaError) as caught:
            reject_private_data({"value": value}, "document")
        assert caught.value.code == "domain_private_data_forbidden"


def test_demo_time_has_a_bounded_current_version_range() -> None:
    assert require_int(MAX_DEMO_TIME_US, "demo_time_us", minimum=0, maximum=MAX_DEMO_TIME_US) == MAX_DEMO_TIME_US

    with pytest.raises(DomainSchemaError) as caught:
        require_int(MAX_DEMO_TIME_US + 1, "demo_time_us", minimum=0, maximum=MAX_DEMO_TIME_US)
    assert caught.value.code == "domain_field_invalid"


def test_canonical_json_fingerprint_is_derived_and_order_independent() -> None:
    left = {"translated_zh": "B点", "confidence": 0.86, "warnings": []}
    right = {"warnings": [], "confidence": 0.86, "translated_zh": "B点"}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert content_fingerprint(left) == content_fingerprint(right)
    assert len(content_fingerprint(left)) == 64

    with pytest.raises(DomainSchemaError) as caught:
        canonical_json_bytes({"confidence": float("nan")})
    assert caught.value.code == "domain_field_invalid"
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
    "api_key", "api-key", "x-api-key", "authorization", "proxy-authorization",
    "access_token", "refresh_token", "client_secret", "secret", "password"
})
FORBIDDEN_DURABLE_KEYS = FORBIDDEN_SECRET_KEYS | frozenset({
    "path", "file_path", "directory_path", "steamid", "steam_id"
})
WINDOWS_RESERVED_STEMS = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})
```

`require_exact_keys(data, required, optional, path)` must reject both missing and unknown keys with `domain_schema_invalid`. `require_current_schema` must convert missing, boolean, non-integer, and non-1 versions into `domain_schema_unsupported`. `reject_secret_keys` must recursively inspect mapping keys and list elements, compare keys case-insensitively, and never reject the legitimate key `max_tokens`.

`reject_private_data` is the reusable production boundary for every durable object. It recursively applies the expanded secret-key scan, rejects the non-secret forbidden metadata keys above, and rejects string values that begin with a Windows drive-root, UNC root, Unix root, `~/`/`~\\`, or a URI scheme followed by `://`. Direct dataclass construction validates its string-bearing fields in `__post_init__`; every `from_dict` validates the complete incoming mapping before parsing. The contract replay imports this helper instead of maintaining a fixture-only privacy implementation.

`require_identifier` must reject Windows device stems case-insensitively even when followed by an extension. `canonical_json_bytes` uses `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")`; translate unsupported values and non-finite numbers to `DomainSchemaError("domain_field_invalid", ...)`. `content_fingerprint` is always `hashlib.sha256(canonical_json_bytes(value)).hexdigest()` and never accepts a caller-supplied digest.

- [ ] **Step 4: Run focused tests and confirm they pass**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_schema_v1.py -q
```

Expected: all tests in `test_domain_schema_v1.py` pass.

- [ ] **Step 5: Commit the schema foundation**

```powershell
git add src/cs2pov/domain/errors.py src/cs2pov/domain/schema.py src/cs2pov/domain/fingerprint.py tests/test_domain_schema_v1.py
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
- Produces: `validate_anchor_sequence(anchors) -> None`.
- Produces: `map_source_range(anchors, source_clock, source_stream_id, source_start, source_end) -> MappedTime`.
- Produces: `demo_to_round_local_us(demo_time_us, round_range) -> int` and `to_export_milliseconds(time_range) -> tuple[int, int]`.

- [ ] **Step 1: Write failing time-range and anchor tests**

Create `tests/test_domain_timebase_v1.py` covering the exact behavior below:

```python
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


@pytest.mark.parametrize("second_demo_start", (5_000_000, 10_500_000))
def test_anchor_sequence_rejects_demo_time_reversal_and_overlap(second_demo_start: int) -> None:
    anchors = (
        _audio_anchor("anchor-a", 0, 24_000, 10_000_000),
        _audio_anchor("anchor-b", 24_000, 48_000, second_demo_start),
    )

    with pytest.raises(DomainSchemaError) as caught:
        map_source_range(
            anchors,
            SourceClock.COMPACT_AUDIO_SAMPLE,
            "player-alpha",
            0,
            48_000,
        )
    assert caught.value.code == "time_anchor_invalid"


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


def test_anchor_uncertainty_is_bounded_like_all_demo_time_values() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        TimeAnchor(
            "anchor-too-uncertain", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha",
            0, 24_000, TimeRange(10_000_000, 11_000_000),
            MAX_DEMO_TIME_US + 1, "synthetic-voice-extractor-v1",
        )
    assert caught.value.code == "domain_field_invalid"


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

- every direct constructor validates its string-bearing fields with `reject_private_data`, and every `from_dict` validates the whole incoming mapping before parsing;
- `TimeRange` validates both values through `require_int(value, path, minimum=0, maximum=MAX_DEMO_TIME_US)` and requires `end_us > start_us`.
- `TimeAnchor` bounds source positions by `MAX_SOURCE_POSITION`, requires a non-empty source span, bounds uncertainty from zero through `MAX_DEMO_TIME_US`, and requires safe identifiers for `source_stream_id` and provenance so local paths cannot be stored there.
- Source overlap is mapped linearly using integer arithmetic. Start boundaries use floor division; end boundaries use ceiling division, so the mapped range never becomes shorter through rounding.
- `map_source_range` filters by both clock and stream, sorts anchors by `source_start`, rejects overlapping source anchors, requires the full requested source range to be covered, returns each discontinuous Demo segment separately, and never silently converts gaps into continuous time.
- `validate_anchor_sequence` groups by `(source_clock, source_stream_id)` and rejects source overlap, mapped Demo overlap, and mapped Demo reversal; both `map_source_range` and `DemoTimeline` call it.
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
- Produces: `MatchPhase` values `WARMUP`, `REGULATION_FIRST_HALF`, `REGULATION_SECOND_HALF`, `OVERTIME_FIRST_HALF`, `OVERTIME_SECOND_HALF`, and `UNKNOWN`.
- Produces: `Round(round_id, display_number, time_range, start_tick, end_tick, match_phase, provenance, confidence, boundary_uncertainty_us)`.
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
    MatchPhase,
)


def _round(round_id: str, number: int, start_us: int, end_us: int) -> Round:
    return Round(
        round_id=round_id,
        display_number=number,
        time_range=TimeRange(start_us, end_us),
        start_tick=None,
        end_tick=None,
        match_phase=MatchPhase.REGULATION_FIRST_HALF,
        provenance="synthetic-round-parser-v1",
        confidence=RoundBoundaryConfidence.EXACT,
        boundary_uncertainty_us=0,
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


def test_demo_rejects_private_absolute_location_in_direct_and_decoded_values() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        DemoDescriptor("a" * 64, "de_mirage", r"C:\private\demo.dem", 64, 1, ())
    assert caught.value.code == "domain_private_data_forbidden"

    payload = _descriptor().to_dict()
    payload["server_name"] = "/home/private/demo.dem"
    with pytest.raises(DomainSchemaError) as caught:
        DemoDescriptor.from_dict(payload)
    assert caught.value.code == "domain_private_data_forbidden"


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


def test_exact_tick_boundaries_must_map_to_declared_demo_range() -> None:
    tick_anchor = TimeAnchor(
        anchor_id="anchor-demo-ticks",
        source_clock=SourceClock.DEMO_TICK,
        source_stream_id="demo",
        source_start=640,
        source_end=1280,
        demo_range=TimeRange(10_000_000, 20_000_000),
        uncertainty_us=0,
        provenance="synthetic-round-parser-v1",
    )
    mismatched = Round(
        round_id="round-001",
        display_number=1,
        time_range=TimeRange(10_000_000, 20_000_000),
        start_tick=640,
        end_tick=1200,
        match_phase=MatchPhase.REGULATION_FIRST_HALF,
        provenance="synthetic-round-parser-v1",
        confidence=RoundBoundaryConfidence.EXACT,
        boundary_uncertainty_us=0,
    )

    with pytest.raises(DomainSchemaError) as caught:
        DemoTimeline(_descriptor(), RoundCollection((mismatched,)), (tick_anchor,))
    assert caught.value.code == "round_reference_invalid"


def test_estimated_tick_boundary_may_differ_only_within_declared_uncertainty() -> None:
    tick_anchor = TimeAnchor(
        anchor_id="anchor-demo-ticks",
        source_clock=SourceClock.DEMO_TICK,
        source_stream_id="demo",
        source_start=640,
        source_end=1280,
        demo_range=TimeRange(10_000_000, 20_000_000),
        uncertainty_us=0,
        provenance="synthetic-round-parser-v1",
    )

    def estimated(uncertainty_us: int) -> Round:
        return Round(
            "round-001", 1, TimeRange(10_000_000, 20_000_000), 640, 1279,
            MatchPhase.REGULATION_FIRST_HALF, "synthetic-round-parser-v1",
            RoundBoundaryConfidence.ESTIMATED, uncertainty_us,
        )

    DemoTimeline(_descriptor(), RoundCollection((estimated(20_000),)), (tick_anchor,))
    with pytest.raises(DomainSchemaError) as caught:
        DemoTimeline(_descriptor(), RoundCollection((estimated(10_000),)), (tick_anchor,))
    assert caught.value.code == "round_reference_invalid"
```

- [ ] **Step 2: Run the focused timeline test and confirm it fails**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_timeline_v1.py -q
```

Expected: collection fails because `cs2pov.domain.timeline` does not exist.

- [ ] **Step 3: Implement strict current-version timeline documents**

Implement `timeline.py` so that:

- direct constructors and `from_dict` factories apply the Task 1 production privacy boundary;
- every non-hash domain identifier uses `require_identifier`;
- every `demo_asset_id` uses `require_sha256`, matching the existing content-addressed `DemoAssetRef` identity;
- tick-rate numerator and denominator are positive integers and remain rational, never a float;
- team number is `None` or a non-negative integer;
- Round tick fields are both present or both absent; when present, end tick must be greater than start tick;
- `EXACT` requires `boundary_uncertainty_us == 0`; estimated/fallback rounds require a non-negative bounded value. When ticks exist, `DemoTimeline` maps them through the `demo` tick anchor: exact boundaries must equal the declared Demo range, while estimated/fallback boundary differences must not exceed their declared uncertainty;
- `RoundCollection` requires unique IDs, unique display numbers, ascending time, and no overlap;
- `DemoTimeline` requires unique anchor IDs; `COMPACT_AUDIO_SAMPLE` streams refer to known player IDs; `DEMO_TICK` uses stream `demo`; future `VIDEO_FRAME` streams may use any safe renderer-generated ID;
- `DemoDescriptor.from_dict` and `RoundCollection.from_dict` reject unknown keys and unsupported versions;
- serialized times are only `start_us`/`end_us` integers.

The durable document shapes are exact:

```json
{"schema_version": 1, "demo_asset_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "map_name": "de_mirage", "server_name": null, "tick_rate": {"numerator": 64, "denominator": 1}, "players": [{"player_id": "player-alpha", "display_name": "Alpha", "team_number": 2}]}
```

```json
{"schema_version": 1, "rounds": [{"round_id": "round-001", "display_number": 1, "start_us": 10000000, "end_us": 20000000, "start_tick": 640, "end_tick": 1280, "match_phase": "regulation_first_half", "provenance": "synthetic-round-parser-v1", "confidence": "exact", "boundary_uncertainty_us": 0}]}
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

### Task 4: Shared model configuration and per-call provenance

**Files:**
- Create: `src/cs2pov/domain/invocation.py`
- Create: `tests/test_domain_invocation_v1.py`

**Interfaces:**
- Consumes: Task 1 validation and canonical fingerprint helpers.
- Produces: `ModelCapability` values `ASR` and `UNDERSTANDING_TRANSLATION`.
- Produces: `ModelConfigurationSnapshot(snapshot_id, capability, provider_kind, endpoint_profile_id, model_name, prompt_template_version, parameters, knowledge_revision_ids, adapter_version)` with derived `configuration_fingerprint`.
- Produces: `ModelInvocationRecord(invocation_id, configuration_snapshot_id, task_id, request_content_fingerprint, response_content_fingerprint)` plus `from_payloads(...)`.
- Produces deterministic strict current-version dictionaries without request text or secrets.

- [ ] **Step 1: Write failing snapshot round-trip and secret-rejection tests**

Create `tests/test_domain_invocation_v1.py`:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invocation import (
    ModelCapability,
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)


def _configuration(parameters: dict[str, object] | None = None) -> ModelConfigurationSnapshot:
    return ModelConfigurationSnapshot(
        snapshot_id="llm-config-001",
        capability=ModelCapability.UNDERSTANDING_TRANSLATION,
        provider_kind="openai-compatible",
        endpoint_profile_id="provider-local-profile",
        model_name="fixture-model",
        prompt_template_version="understanding-v1",
        parameters=parameters or {"temperature": 0.2, "max_tokens": 512},
        knowledge_revision_ids=("knowledge-global-001",),
        adapter_version="adapter-v1",
    )


def test_configuration_round_trips_without_secret_request_or_raw_url() -> None:
    configuration = _configuration()
    payload = configuration.to_dict()

    assert payload["schema_version"] == 1
    assert payload["endpoint_profile_id"] == "provider-local-profile"
    assert len(payload["configuration_fingerprint"]) == 64
    assert "api_key" not in str(payload).lower()
    assert "base_url" not in payload
    assert "request_content_fingerprint" not in payload
    assert ModelConfigurationSnapshot.from_dict(payload) == configuration


def test_configuration_copies_nested_json_parameters_to_prevent_mutation() -> None:
    source = {"response_format": {"type": "json_object"}}
    configuration = _configuration(source)
    source["response_format"] = {"type": "text"}

    assert configuration.to_dict()["parameters"] == {"response_format": {"type": "json_object"}}


def test_configuration_rejects_secret_bearing_parameters() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        _configuration({"headers": {"authorization": "Bearer private"}})
    assert caught.value.code == "domain_secret_forbidden"


def test_configuration_rejects_private_url_values() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        _configuration({"callback": "https://private.example/hook"})
    assert caught.value.code == "domain_private_data_forbidden"


def test_configuration_rejects_non_json_values_and_tampered_fingerprint() -> None:
    with pytest.raises(DomainSchemaError) as caught:
        _configuration({"temperature": object()})
    assert caught.value.code == "domain_field_invalid"

    payload = _configuration().to_dict()
    payload["model_name"] = "silently-changed-model"
    with pytest.raises(DomainSchemaError) as caught:
        ModelConfigurationSnapshot.from_dict(payload)
    assert caught.value.code == "domain_fingerprint_mismatch"


def test_rounds_share_configuration_but_have_distinct_invocation_records() -> None:
    configuration = _configuration()
    round_one = ModelInvocationRecord.from_payloads(
        invocation_id="invoke-round-001",
        configuration_snapshot_id=configuration.snapshot_id,
        task_id="round-001",
        request_payload={"round_id": "round-001", "text": "one jungle"},
        response_payload={"translated_zh": "警家一个"},
    )
    round_two = ModelInvocationRecord.from_payloads(
        invocation_id="invoke-round-002",
        configuration_snapshot_id=configuration.snapshot_id,
        task_id="round-002",
        request_payload={"round_id": "round-002", "text": "be be be"},
        response_payload={"translated_zh": "B点，B点，B点"},
    )

    assert round_one.configuration_snapshot_id == round_two.configuration_snapshot_id
    assert round_one.request_content_fingerprint != round_two.request_content_fingerprint
    assert ModelInvocationRecord.from_dict(round_one.to_dict()) == round_one


def test_retry_keeps_task_identity_but_gets_a_new_invocation_identity() -> None:
    configuration = _configuration()
    first = ModelInvocationRecord.from_payloads(
        "invoke-round-001-attempt-001", configuration.snapshot_id, "round-001",
        {"round_id": "round-001", "attempt": 1}, {"error": "provider-timeout"},
    )
    retry = ModelInvocationRecord.from_payloads(
        "invoke-round-001-attempt-002", configuration.snapshot_id, "round-001",
        {"round_id": "round-001", "attempt": 2}, {"translated_zh": "警家一个"},
    )

    assert first.task_id == retry.task_id == "round-001"
    assert first.invocation_id != retry.invocation_id
    assert first.request_content_fingerprint != retry.request_content_fingerprint


def test_local_asr_uses_same_closed_provenance_graph_without_endpoint_profile() -> None:
    configuration = ModelConfigurationSnapshot(
        snapshot_id="asr-config-001",
        capability=ModelCapability.ASR,
        provider_kind="faster-whisper-local",
        endpoint_profile_id=None,
        model_name="fixture-asr-model",
        prompt_template_version=None,
        parameters={"language": "en"},
        knowledge_revision_ids=(),
        adapter_version="faster-whisper-adapter-v1",
    )
    invocation = ModelInvocationRecord.from_payloads(
        invocation_id="asr-invoke-001",
        configuration_snapshot_id=configuration.snapshot_id,
        task_id="asr-batch-001",
        request_payload={"audio_content_fingerprint": "9" * 64},
        response_payload={"cue_ids": ["cue-b-callout"]},
    )

    assert ModelConfigurationSnapshot.from_dict(configuration.to_dict()) == configuration
    assert ModelInvocationRecord.from_dict(invocation.to_dict()) == invocation
```

- [ ] **Step 2: Run the focused snapshot test and confirm it fails**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_invocation_v1.py -q
```

Expected: collection fails because `cs2pov.domain.invocation` does not exist.

- [ ] **Step 3: Implement an immutable, JSON-only, non-secret snapshot**

Implement `invocation.py` with these policies:

- direct constructors and `from_dict` factories apply `reject_private_data` before accepting configuration or invocation content;
- all identity/version fields are non-empty strings; ID fields use `require_identifier`;
- parameters recursively accept only `None`, `bool`, finite `int`/`float`, `str`, lists, and dictionaries with string keys;
- copy parameters into an immutable internal representation on construction and return fresh JSON-compatible containers from `to_dict`, so caller mutation cannot alter the configuration;
- call `reject_secret_keys` before storage;
- compute the configuration fingerprint from the exact configuration payload excluding `schema_version` and `configuration_fingerprint`; `from_dict` recomputes and rejects mismatch;
- `ModelInvocationRecord.from_payloads` derives request/response hashes with Task 1 `content_fingerprint`; direct construction and `from_dict` only accept validated lowercase hashes because raw request/response payloads are intentionally not persisted;
- a persisted invocation collection requires unique invocation IDs; task IDs deliberately may repeat because retries of one round retain the same task identity while receiving a new invocation/attempt identity;
- emit no base URL, API key, credential value, request/response text, SteamID, or filesystem path;
- reject missing/unknown keys and unsupported schema versions.

Use these exact durable shapes:

- configuration document: `schema_version`, `snapshot_id`, `capability`, `provider_kind`, `endpoint_profile_id`, `model_name`, `prompt_template_version`, `parameters`, `knowledge_revision_ids`, `adapter_version`, derived `configuration_fingerprint`;
- invocation record: `schema_version`, `invocation_id`, `configuration_snapshot_id`, `task_id`, `request_content_fingerprint`, `response_content_fingerprint`.

The request and response fingerprints belong only to an actual invocation record. They must never be copied into the reusable configuration snapshot, and `from_dict` must reject such extra keys.

- [ ] **Step 4: Run schema and invocation tests**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_schema_v1.py tests/test_domain_invocation_v1.py -q
```

Expected: both files pass.

- [ ] **Step 5: Commit configuration and per-call provenance**

```powershell
git add src/cs2pov/domain/invocation.py tests/test_domain_invocation_v1.py
git commit -m "feat: add safe model invocation provenance"
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
- Produces: `TranscriptCue(cue_id, player_id, round_id, time_range, source_clock, source_stream_id, source_start, source_end, asr_original, language, confidence, anchor_ids, voice_activity_ids, asr_invocation_record_id)` plus `from_source_span(...)`.
- Produces: `UnderstandingResult(cue_id, round_id, asr_original, interpreted_source, translated_zh, confidence, evidence, warnings, model_invocation_record_id)` with derived `content_fingerprint()`.
- Produces: `RoundUnderstandingDocument(round_id, input_fingerprint, model_configuration_snapshot_id, invocation_record_id, results)`; empty successful results require `invocation_record_id=None`.
- Produces: `validate_understanding_against_transcript(result, cue) -> None`.

- [ ] **Step 1: Write failing three-layer meaning and source-integrity tests**

Create `tests/test_domain_understanding_v1.py`:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
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
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE,
        source_stream_id="player-bravo",
        source_start=0,
        source_end=28_800,
        asr_original="be be be",
        language="en",
        confidence=0.62,
        anchor_ids=("anchor-bravo-001",),
        voice_activity_ids=("activity-bravo-001",),
        asr_invocation_record_id="asr-invoke-001",
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
        model_invocation_record_id="invoke-round-002",
    )


def test_transcript_jsonl_record_preserves_original_asr_and_integer_time() -> None:
    cue = _cue()
    payload = cue.to_dict()

    assert payload["schema_version"] == 1
    assert payload["asr_original"] == "be be be"
    assert payload["start_us"] == 20_500_000
    assert isinstance(payload["start_us"], int)
    assert TranscriptCue.from_dict(payload) == cue


def test_unassigned_transcript_is_explicit_and_round_trips() -> None:
    payload = _cue().to_dict()
    payload["round_id"] = None

    cue = TranscriptCue.from_dict(payload)
    assert cue.round_id is None


def test_transcript_rejects_private_location_disguised_as_source_text() -> None:
    payload = _cue().to_dict()
    payload["asr_original"] = r"C:\Users\private\recording.wav"

    with pytest.raises(DomainSchemaError) as caught:
        TranscriptCue.from_dict(payload)
    assert caught.value.code == "domain_private_data_forbidden"


def test_transcript_factory_rejects_discontinuous_compact_audio_span() -> None:
    anchors = (
        TimeAnchor("anchor-a", SourceClock.COMPACT_AUDIO_SAMPLE, "player-bravo", 0, 24_000, TimeRange(10_000_000, 11_000_000), 16_000, "voice-extractor-v1"),
        TimeAnchor("anchor-b", SourceClock.COMPACT_AUDIO_SAMPLE, "player-bravo", 24_000, 48_000, TimeRange(20_000_000, 21_000_000), 16_000, "voice-extractor-v1"),
    )

    with pytest.raises(DomainSchemaError) as caught:
        TranscriptCue.from_source_span(
            cue_id="cue-discontinuous",
            player_id="player-bravo",
            round_id=None,
            source_clock=SourceClock.COMPACT_AUDIO_SAMPLE,
            source_stream_id="player-bravo",
            source_start=18_000,
            source_end=30_000,
            anchors=anchors,
            asr_original="crosses a silence gap",
            language="en",
            confidence=0.5,
            voice_activity_ids=("activity-bravo-001",),
            asr_invocation_record_id="asr-invoke-001",
        )
    assert caught.value.code == "cue_time_discontinuous"


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


def test_understanding_content_fingerprint_changes_with_meaning() -> None:
    original = _result()
    payload = original.to_dict()
    payload["translated_zh"] = "改写后的翻译"
    changed = UnderstandingResult.from_dict(payload)

    assert original.content_fingerprint() != changed.content_fingerprint()


def test_round_document_requires_one_result_per_cue_and_matching_round() -> None:
    document = RoundUnderstandingDocument(
        round_id="round-002",
        input_fingerprint="b" * 64,
        model_configuration_snapshot_id="llm-config-001",
        invocation_record_id="invoke-round-002",
        results=(_result(),),
    )
    assert RoundUnderstandingDocument.from_dict(document.to_dict()) == document

    with pytest.raises(DomainSchemaError) as caught:
        RoundUnderstandingDocument(
            round_id="round-001",
            input_fingerprint="b" * 64,
            model_configuration_snapshot_id="llm-config-001",
            invocation_record_id="invoke-round-002",
            results=(_result(),),
        )
    assert caught.value.code == "round_reference_invalid"


def test_speechless_round_is_successful_without_fake_model_call() -> None:
    document = RoundUnderstandingDocument(
        round_id="round-003",
        input_fingerprint="3" * 64,
        model_configuration_snapshot_id="llm-config-001",
        invocation_record_id=None,
        results=(),
    )

    assert RoundUnderstandingDocument.from_dict(document.to_dict()) == document


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

- direct constructors and `from_dict` factories apply `reject_private_data` to the complete durable content, including ASR/interpreted/translated text;
- cue and round/player/configuration/invocation/anchor IDs use safe identifiers; only TranscriptCue permits `round_id=None`;
- voice activity has a positive packet count no greater than `MAX_COUNT`, at least one anchor ID, and non-negative uncertainty no greater than `MAX_DEMO_TIME_US`;
- `TranscriptCue.asr_original` is non-empty and frozen;
- transcript source positions are non-negative and no greater than `MAX_SOURCE_POSITION`;
- confidence is optional only on `TranscriptCue`; `UnderstandingResult.confidence` is required;
- `TranscriptCue.from_source_span` maps its integer source span through anchors and rejects non-contiguous `MappedTime` with `cue_time_discontinuous`; adapters must split before retrying and no warning-only bypass exists;
- evidence is a non-empty tuple of non-empty strings; warnings may be empty;
- `RoundUnderstandingDocument` results have unique cue IDs and all reference its round/invocation record. Non-empty results require one invocation record; empty results require `invocation_record_id=None` and remain a valid successful no-speech round;
- source validation compares cue ID, round ID, and exact `asr_original` without normalization or rewriting.

The four durable shapes use these exact keys:

```json
{"schema_version": 1, "activity_id": "activity-bravo-001", "player_id": "player-bravo", "start_us": 20500000, "end_us": 21700000, "packet_count": 12, "anchor_ids": ["anchor-bravo-001"], "uncertainty_us": 16000}
```

```json
{"schema_version": 1, "cue_id": "cue-b-callout", "player_id": "player-bravo", "round_id": "round-002", "start_us": 20500000, "end_us": 21700000, "source_clock": "compact_audio_sample", "source_stream_id": "player-bravo", "source_start": 0, "source_end": 28800, "asr_original": "be be be", "language": "en", "confidence": 0.62, "anchor_ids": ["anchor-bravo-001"], "voice_activity_ids": ["activity-bravo-001"], "asr_invocation_record_id": "asr-invoke-001"}
```

```json
{"schema_version": 1, "cue_id": "cue-b-callout", "round_id": "round-002", "asr_original": "be be be", "interpreted_source": "B, B, B", "translated_zh": "B点，B点，B点", "confidence": 0.86, "evidence": ["same-round-context"], "warnings": [], "model_invocation_record_id": "invoke-round-002"}
```

The RoundUnderstandingDocument top level has exactly `schema_version`, `round_id`, `input_fingerprint`, `model_configuration_snapshot_id`, `invocation_record_id`, and `results`. An empty `results` list is valid only with a null invocation record.

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
- Create: `src/cs2pov/domain/validation.py`
- Create: `tests/test_domain_review_v1.py`
- Create: `tests/test_domain_validation_v1.py`

**Interfaces:**
- Consumes: `TimeRange`, `UnderstandingResult`, identifiers, SHA-256, and current schema helpers.
- Produces: `ReviewAction` values `ACCEPT`, `EDIT`, and `EXCLUDE`.
- Produces: `ReviewDecision(decision_id, cue_id, source_result_fingerprint, action, reviewed_at, reviewer_label, reason, revised_time_range, revised_interpreted_source, revised_translated_zh)`.
- Produces: `DraftCommsCue.from_transcript_and_understanding(...)` and `ReviewedCommsCue` preserving source, interpreted, and translated layers.
- Produces: `DraftCommsTimeline.content_fingerprint()` and `ReviewedCommsTimeline` with explicit `timebase` and deterministic ordering validation.
- Produces: `compose_draft_timeline(timeline, transcripts, documents, configurations, invocations) -> DraftCommsTimeline` as the only application-facing Draft construction path, plus `validate_draft_timeline_graph` for reopened documents.
- Produces: `compose_reviewed_timeline(draft, decisions) -> ReviewedCommsTimeline` as the only public composition path.
- Produces: `validate_voice_activity_against_timeline`, `validate_transcript_against_timeline`, `validate_understanding_document_graph(document, transcripts, configurations, invocations)`, and `validate_reviewed_timeline_graph`.

- [ ] **Step 1: Write failing review action, preservation, and timebase tests**

Create `tests/test_domain_review_v1.py` with the following core cases:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.review import (
    DraftCommsCue,
    DraftCommsTimeline,
    ReviewAction,
    ReviewDecision,
    ReviewedCommsTimeline,
    compose_reviewed_timeline,
)
from cs2pov.domain.timebase import SourceClock, TimeRange
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import UnderstandingResult


PERSISTENCE_TEST_INPUT_FINGERPRINT = content_fingerprint({"round_understanding": []})


def _draft(cue_id: str = "cue-b-callout", start_us: int = 20_500_000) -> DraftCommsCue:
    transcript = TranscriptCue(
        cue_id=cue_id,
        player_id="player-bravo",
        round_id="round-002",
        time_range=TimeRange(start_us, start_us + 1_200_000),
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE,
        source_stream_id="player-bravo",
        source_start=0,
        source_end=28_800,
        asr_original="be be be",
        language="en",
        confidence=0.62,
        anchor_ids=("anchor-bravo-001",),
        voice_activity_ids=("activity-bravo-001",),
        asr_invocation_record_id="asr-invoke-001",
    )
    result = UnderstandingResult(
        cue_id=cue_id,
        round_id="round-002",
        asr_original="be be be",
        interpreted_source="B, B, B",
        translated_zh="B点，B点，B点",
        confidence=0.86,
        evidence=("same-round-context",),
        warnings=(),
        model_invocation_record_id="invoke-round-002",
    )
    return DraftCommsCue.from_transcript_and_understanding(transcript, result)


def test_accept_decision_cannot_smuggle_revised_content() -> None:
    draft = _draft()
    with pytest.raises(DomainSchemaError) as caught:
        ReviewDecision(
            decision_id="decision-001",
            cue_id="cue-b-callout",
            source_result_fingerprint=draft.understanding_result_fingerprint,
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
    draft = _draft()
    with pytest.raises(DomainSchemaError) as caught:
        ReviewDecision(
            decision_id="decision-001",
            cue_id="cue-b-callout",
            source_result_fingerprint=draft.understanding_result_fingerprint,
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
            source_result_fingerprint=draft.understanding_result_fingerprint,
            action=ReviewAction.EXCLUDE,
            reviewed_at="2026-08-31T12:00:00+00:00",
            reviewer_label="local-user",
            reason=None,
            revised_time_range=None,
            revised_interpreted_source=None,
            revised_translated_zh=None,
        )
    assert caught.value.code == "review_decision_invalid"


def test_review_reason_rejects_private_location() -> None:
    draft = _draft()
    with pytest.raises(DomainSchemaError) as caught:
        ReviewDecision(
            "decision-private", draft.cue_id, draft.understanding_result_fingerprint,
            ReviewAction.EXCLUDE, "2026-08-31T12:00:00.000000Z", "local-user",
            "/home/private/evidence.txt", None, None, None,
        )
    assert caught.value.code == "domain_private_data_forbidden"


def test_composition_preserves_original_and_records_final_values() -> None:
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
    draft_timeline = DraftCommsTimeline(
        "a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (draft,),
    )
    reviewed_timeline = compose_reviewed_timeline(draft_timeline, (decision,))
    cue = reviewed_timeline.cues[0]

    assert cue.asr_original == "be be be"
    assert cue.interpreted_source == "B, B, B"
    assert cue.model_translated_zh == "B点，B点，B点"
    assert cue.model_confidence == 0.86
    assert cue.evidence == ("same-round-context",)
    assert cue.final_translated_zh == "B点！B点！B点！"
    assert cue.review_decision_id == "decision-001"
    assert reviewed_timeline.source_draft_fingerprint == draft_timeline.content_fingerprint()


def test_valid_exclude_removes_cue_and_preserves_decision_id() -> None:
    draft = _draft()
    decision = ReviewDecision(
        "decision-exclude", draft.cue_id, draft.understanding_result_fingerprint,
        ReviewAction.EXCLUDE, "2026-08-31T12:00:00.000000Z", "local-user",
        "与目标队伍交流无关", None, None, None,
    )
    source = DraftCommsTimeline(
        "a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (draft,),
    )

    reviewed = compose_reviewed_timeline(source, (decision,))

    assert reviewed.cues == ()
    assert reviewed.excluded_decision_ids == ("decision-exclude",)


def test_timeline_requires_explicit_demo_timebase_and_sorted_cues() -> None:
    first = _draft("cue-first", 20_500_000)
    second = _draft("cue-second", 22_000_000)
    timeline = DraftCommsTimeline(
        demo_asset_id="a" * 64,
        timebase="demo-microseconds",
        input_fingerprint=PERSISTENCE_TEST_INPUT_FINGERPRINT,
        cues=(first, second),
    )
    assert DraftCommsTimeline.from_dict(timeline.to_dict()) == timeline

    with pytest.raises(DomainSchemaError) as caught:
        DraftCommsTimeline(
            demo_asset_id="a" * 64,
            timebase="round-local-milliseconds",
            input_fingerprint=PERSISTENCE_TEST_INPUT_FINGERPRINT,
            cues=(first, second),
        )
    assert caught.value.code == "timeline_invalid"


    with pytest.raises(DomainSchemaError) as caught:
        DraftCommsTimeline(
            demo_asset_id="a" * 64,
            timebase="demo-microseconds",
            input_fingerprint=PERSISTENCE_TEST_INPUT_FINGERPRINT,
            cues=(second, first),
        )
    assert caught.value.code == "timeline_invalid"


def test_reviewed_timeline_round_trips_from_verified_composition() -> None:
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
    source = DraftCommsTimeline(
        "a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (draft,),
    )
    timeline = compose_reviewed_timeline(source, (decision,))

    assert ReviewedCommsTimeline.from_dict(timeline.to_dict()) == timeline


def test_composition_rejects_missing_extra_stale_and_noop_decisions() -> None:
    draft = _draft()
    source = DraftCommsTimeline(
        "a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (draft,),
    )

    with pytest.raises(DomainSchemaError) as caught:
        compose_reviewed_timeline(source, ())
    assert caught.value.code == "review_decision_invalid"

    extra = ReviewDecision(
        "decision-extra", "cue-extra", "0" * 64, ReviewAction.ACCEPT,
        "2026-08-31T12:00:00.000000Z", "local-user", None, None, None, None,
    )
    with pytest.raises(DomainSchemaError) as caught:
        compose_reviewed_timeline(source, (extra,))
    assert caught.value.code == "review_decision_invalid"

    stale = ReviewDecision(
        "decision-stale", draft.cue_id, "0" * 64, ReviewAction.ACCEPT,
        "2026-08-31T12:00:00.000000Z", "local-user", None, None, None, None,
    )
    with pytest.raises(DomainSchemaError) as caught:
        compose_reviewed_timeline(source, (stale,))
    assert caught.value.code == "domain_fingerprint_mismatch"

    noop = ReviewDecision(
        "decision-noop", draft.cue_id, draft.understanding_result_fingerprint, ReviewAction.EDIT,
        "2026-08-31T12:00:00.000000Z", "local-user", "重复原译文", None, None, draft.translated_zh,
    )
    with pytest.raises(DomainSchemaError) as caught:
        compose_reviewed_timeline(source, (noop,))
    assert caught.value.code == "review_decision_invalid"


def test_tampered_draft_payload_cannot_keep_old_content_fingerprint() -> None:
    source = DraftCommsTimeline(
        "a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (_draft(),),
    )
    payload = source.to_dict()
    original_fingerprint = source.content_fingerprint()
    payload["cues"][0]["translated_zh"] = "被篡改"
    changed = DraftCommsTimeline.from_dict(payload)

    assert changed.content_fingerprint() != original_fingerprint


def test_direct_reviewed_document_rejects_duplicate_cues() -> None:
    draft = _draft()
    decision = ReviewDecision(
        "decision-001", draft.cue_id, draft.understanding_result_fingerprint, ReviewAction.ACCEPT,
        "2026-08-31T12:00:00.000000Z", "local-user", None, None, None, None,
    )
    composed = compose_reviewed_timeline(
        DraftCommsTimeline(
            "a" * 64, "demo-microseconds", PERSISTENCE_TEST_INPUT_FINGERPRINT, (draft,),
        ),
        (decision,),
    )
    reviewed = composed.cues[0]

    with pytest.raises(DomainSchemaError) as caught:
        ReviewedCommsTimeline(
            "a" * 64, "demo-microseconds", composed.source_draft_fingerprint,
            (reviewed, reviewed), (),
        )
    assert caught.value.code == "timeline_invalid"
```

- [ ] **Step 2: Write failing cross-object containment and provenance tests**

Create `tests/test_domain_validation_v1.py` with one closed graph plus reference, privacy-adjacent, containment, and fingerprint tamper cases:

```python
from __future__ import annotations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import ModelCapability, ModelConfigurationSnapshot, ModelInvocationRecord
from cs2pov.domain.review import DraftCommsCue, DraftCommsTimeline, ReviewAction, ReviewDecision, compose_reviewed_timeline
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.timeline import DemoDescriptor, DemoTimeline, MatchPhase, PlayerSnapshot, Round, RoundBoundaryConfidence, RoundCollection
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import RoundUnderstandingDocument, UnderstandingResult
from cs2pov.domain.validation import (
    compose_draft_timeline,
    validate_draft_timeline_graph,
    validate_reviewed_timeline_graph,
    validate_transcript_against_timeline,
    validate_understanding_document_graph,
    validate_voice_activity_against_timeline,
)
from cs2pov.domain.voice import VoiceActivityCue


def _closed_graph() -> tuple[DemoTimeline, VoiceActivityCue, TranscriptCue, ModelConfigurationSnapshot, ModelInvocationRecord]:
    descriptor = DemoDescriptor("a" * 64, "de_mirage", None, 64, 1, (PlayerSnapshot("player-alpha", "Alpha", 2),))
    rounds = RoundCollection((Round(
        "round-001", 1, TimeRange(10_000_000, 11_000_000), None, None,
        MatchPhase.REGULATION_FIRST_HALF, "round-parser-v1", RoundBoundaryConfidence.EXACT, 0,
    ),))
    anchor = TimeAnchor(
        "anchor-alpha-001", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 0, 24_000,
        TimeRange(10_000_000, 11_000_000), 16_000, "voice-extractor-v1",
    )
    timeline = DemoTimeline(descriptor, rounds, (anchor,))
    activity = VoiceActivityCue(
        "activity-alpha-001", "player-alpha", TimeRange(10_000_000, 10_500_000),
        8, ("anchor-alpha-001",), 16_000,
    )
    configuration = ModelConfigurationSnapshot(
        "asr-config-001", ModelCapability.ASR, "faster-whisper-local", None,
        "fixture-asr-model", None, {"language": "en"}, (), "asr-adapter-v1",
    )
    invocation = ModelInvocationRecord.from_payloads(
        "asr-invoke-001", configuration.snapshot_id, "asr-batch-001",
        {"audio_content_fingerprint": "9" * 64}, {"cue_ids": ["cue-alpha-001"]},
    )
    transcript = TranscriptCue.from_source_span(
        cue_id="cue-alpha-001", player_id="player-alpha", round_id="round-001",
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE, source_stream_id="player-alpha",
        source_start=0, source_end=12_000, anchors=(anchor,), asr_original="one jungle",
        language="en", confidence=0.9, voice_activity_ids=(activity.activity_id,),
        asr_invocation_record_id=invocation.invocation_id,
    )
    return timeline, activity, transcript, configuration, invocation


def test_transcript_graph_validates_player_round_activity_anchor_and_asr_call() -> None:
    timeline, activity, transcript, configuration, invocation = _closed_graph()

    validate_transcript_against_timeline(
        transcript, timeline, (activity,), (configuration,), (invocation,),
    )


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    (
        ("player_id", "player-missing", "player_reference_invalid"),
        ("anchor_ids", ["anchor-missing"], "time_anchor_invalid"),
        ("start_us", 9_000_000, "cue_reference_invalid"),
    ),
)
def test_voice_activity_graph_rejects_unknown_or_unmapped_evidence(
    field: str,
    value: object,
    error_code: str,
) -> None:
    timeline, activity, _, _, _ = _closed_graph()
    payload = activity.to_dict()
    payload[field] = value
    if field == "start_us":
        payload["end_us"] = 9_500_000

    with pytest.raises(DomainSchemaError) as caught:
        validate_voice_activity_against_timeline(VoiceActivityCue.from_dict(payload), timeline)
    assert caught.value.code == error_code


def test_transcript_graph_rejects_unknown_player_dangling_call_and_round_crossing() -> None:
    timeline, activity, transcript, configuration, invocation = _closed_graph()

    payload = transcript.to_dict()
    payload["player_id"] = "player-missing"
    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(
            TranscriptCue.from_dict(payload), timeline, (activity,), (configuration,), (invocation,),
        )
    assert caught.value.code == "player_reference_invalid"

    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(transcript, timeline, (activity,), (configuration,), ())
    assert caught.value.code == "invocation_reference_invalid"

    payload = transcript.to_dict()
    payload["end_us"] = 11_000_001
    with pytest.raises(DomainSchemaError) as caught:
        validate_transcript_against_timeline(
            TranscriptCue.from_dict(payload), timeline, (activity,), (configuration,), (invocation,),
        )
    assert caught.value.code == "cue_reference_invalid"


def test_understanding_and_draft_graph_derive_all_source_fingerprints() -> None:
    timeline, _, transcript, asr_configuration, _ = _closed_graph()
    configuration = ModelConfigurationSnapshot(
        "llm-config-001", ModelCapability.UNDERSTANDING_TRANSLATION, "openai-compatible",
        "provider-local-profile", "fixture-model", "understanding-v1",
        {"temperature": 0.2}, (), "adapter-v1",
    )
    result = UnderstandingResult(
        transcript.cue_id, "round-001", transcript.asr_original, "one jungle", "警家一个",
        0.93, ("same-round-context",), (), "invoke-round-001",
    )
    request = {"round_id": "round-001", "transcript_cues": [transcript.to_dict()]}
    response = {"round_id": "round-001", "results": [result.to_dict()]}
    invocation = ModelInvocationRecord.from_payloads(
        "invoke-round-001", configuration.snapshot_id, "round-001", request, response,
    )
    document = RoundUnderstandingDocument(
        "round-001", content_fingerprint(request), configuration.snapshot_id,
        invocation.invocation_id, (result,),
    )

    validate_understanding_document_graph(
        document, (transcript,), (configuration,), (invocation,),
    )
    draft = compose_draft_timeline(
        timeline, (transcript,), (document,), (configuration,), (invocation,),
    )
    validate_draft_timeline_graph(
        draft, timeline, (transcript,), (document,), (configuration,), (invocation,),
    )

    tampered_payload = draft.to_dict()
    tampered_payload["input_fingerprint"] = "0" * 64
    with pytest.raises(DomainSchemaError) as caught:
        validate_draft_timeline_graph(
            DraftCommsTimeline.from_dict(tampered_payload), timeline, (transcript,),
            (document,), (configuration,), (invocation,),
        )
    assert caught.value.code == "domain_fingerprint_mismatch"

    changed_payload = result.to_dict()
    changed_payload["asr_original"] = "B B B"
    changed_document = RoundUnderstandingDocument(
        "round-001", document.input_fingerprint, configuration.snapshot_id,
        invocation.invocation_id, (UnderstandingResult.from_dict(changed_payload),),
    )
    with pytest.raises(DomainSchemaError) as caught:
        validate_understanding_document_graph(
            changed_document, (transcript,), (configuration,), (invocation,),
        )
    assert caught.value.code == "cue_reference_invalid"

    with pytest.raises(DomainSchemaError) as caught:
        validate_understanding_document_graph(
            document, (transcript,), (asr_configuration,), (invocation,),
        )
    assert caught.value.code == "invocation_reference_invalid"


def test_reviewed_time_edit_must_remain_inside_declared_round() -> None:
    timeline, _, transcript, _, _ = _closed_graph()
    result = UnderstandingResult(
        transcript.cue_id, "round-001", transcript.asr_original, "one jungle", "警家一个",
        0.93, ("same-round-context",), (), "invoke-round-001",
    )
    draft_cue = DraftCommsCue.from_transcript_and_understanding(transcript, result)
    draft = DraftCommsTimeline(
        "a" * 64, "demo-microseconds",
        content_fingerprint({"round_understanding": []}), (draft_cue,),
    )
    decision = ReviewDecision(
        "decision-001", draft_cue.cue_id, draft_cue.understanding_result_fingerprint,
        ReviewAction.EDIT, "2026-08-31T12:00:00.000000Z", "local-user",
        "调整显示时间", TimeRange(9_000_000, 9_500_000), None, None,
    )
    reviewed = compose_reviewed_timeline(draft, (decision,))

    with pytest.raises(DomainSchemaError) as caught:
        validate_reviewed_timeline_graph(reviewed, draft, timeline)
    assert caught.value.code == "cue_reference_invalid"
```

- [ ] **Step 3: Run the focused review/validation tests and confirm they fail**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_review_v1.py tests/test_domain_validation_v1.py -q
```

Expected: collection fails because `cs2pov.domain.review` and `cs2pov.domain.validation` do not exist.

- [ ] **Step 4: Implement typed decisions, composition, and aggregate validation**

Apply these exact policies:

- review/timeline direct constructors and `from_dict` factories apply `reject_private_data` to every durable field, including reviewer labels, reasons, source text, and translated text;
- parse `reviewed_at` with `datetime.fromisoformat` after accepting a terminal `Z`, require a timezone-aware timestamp, convert to UTC, and serialize exactly `YYYY-MM-DDTHH:MM:SS.ffffffZ`;
- `ACCEPT` permits no revision fields; `EDIT` requires at least one revised field; `EXCLUDE` permits no revisions and requires a non-empty reason;
- `UnderstandingResult.content_fingerprint()` derives from its exact `to_dict()` with Task 1 canonical JSON; `DraftCommsCue.from_transcript_and_understanding` computes and stores that value rather than accepting one from its caller;
- `compose_draft_timeline` orders documents by the authoritative `DemoTimeline.rounds`, validates every document through `validate_understanding_document_graph`, rejects missing/extra round documents and results, joins each assigned result to its exact transcript, derives each Draft cue, sorts cues by Demo time, and computes `input_fingerprint` from `{"round_understanding": [document.to_dict(), ...]}` in that canonical round order;
- `DraftCommsTimeline` direct construction and `from_dict` exist only as persistence primitives. Application code must create new drafts through `compose_draft_timeline`; reopened drafts remain untrusted until `validate_draft_timeline_graph` recomposes the expected draft and compares the entire value, including `input_fingerprint` and cue order;
- `DraftCommsTimeline.content_fingerprint()` derives from its exact serialized document;
- `compose_reviewed_timeline` requires exactly one unique decision per draft cue, rejects missing/extra/stale decisions, rejects an EDIT whose resolved values equal the draft, derives `source_draft_fingerprint`, and is the only application-facing composition path;
- `ReviewedCommsCue` retains ASR original, interpreted source, and model translation even when final time/text changes;
- excluded cues do not appear in reviewed cues but their decision IDs are retained in `excluded_decision_ids`;
- timeline timebase is exactly `demo-microseconds`; per-round/local export timebases are later exporter manifests, not stored as core truth;
- draft/reviewed timeline `demo_asset_id` values use `require_sha256`;
- cue IDs are unique, cues are sorted by `(start_us, end_us, cue_id)`, and all serialized documents reject unknown keys and unsupported versions.
- aggregate validation uses production functions, not fixture-only checks: it recomputes transcript source mapping, validates known players/rounds/activities/anchors, requires the referenced invocation and configuration with `ASR` capability, verifies cue containment in its declared half-open round, and verifies reviewed edits remain in their original round;
- `validate_understanding_document_graph` derives the canonical request payload as `{"round_id": document.round_id, "transcript_cues": [cue.to_dict(), ...]}` from the sorted assigned cues in that round and the response payload as `{"round_id": document.round_id, "results": [result.to_dict(), ...]}`; it requires the document input fingerprint, invocation request/response fingerprints, configuration reference, `UNDERSTANDING_TRANSLATION` capability, invocation task ID, result set, cue source fields, and invocation IDs all to match. A speechless round uses the same empty request fingerprint but has no invocation and an empty result set;
- unassigned transcript cues are valid members of the transcript collection but are intentionally absent from every per-round understanding document until a later routing stage assigns or dismisses them.

Use these exact top-level keys:

- ReviewDecision JSONL record: `schema_version`, `decision_id`, `cue_id`, `source_result_fingerprint`, `action`, `reviewed_at`, `reviewer_label`, `reason`, `revised_start_us`, `revised_end_us`, `revised_interpreted_source`, `revised_translated_zh`.
- Draft timeline document: `schema_version`, `demo_asset_id`, `timebase`, `input_fingerprint`, `cues`.
- Each draft cue: `cue_id`, `round_id`, `player_id`, `start_us`, `end_us`, `asr_original`, `interpreted_source`, `translated_zh`, `confidence`, `evidence`, `understanding_result_fingerprint`.
- Reviewed timeline document: `schema_version`, `demo_asset_id`, `timebase`, derived `source_draft_fingerprint`, `cues`, `excluded_decision_ids`.
- Each reviewed cue: `cue_id`, `round_id`, `player_id`, `start_us`, `end_us`, `asr_original`, `interpreted_source`, `model_translated_zh`, `model_confidence`, `evidence`, `final_interpreted_source`, `final_translated_zh`, `review_decision_id`.

- [ ] **Step 5: Run review, validation, understanding, and timebase tests**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_timebase_v1.py tests/test_domain_understanding_v1.py tests/test_domain_review_v1.py tests/test_domain_validation_v1.py -q
```

Expected: all four files pass.

- [ ] **Step 6: Commit the review and aggregate validation contracts**

```powershell
git add src/cs2pov/domain/review.py src/cs2pov/domain/validation.py tests/test_domain_review_v1.py tests/test_domain_validation_v1.py
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
    Round("round-001", 1, TimeRange(10_000_000, 20_000_000), 640, 1280, MatchPhase.REGULATION_FIRST_HALF, "synthetic-round-parser-v1", RoundBoundaryConfidence.EXACT, 0),
    Round("round-002", 2, TimeRange(20_000_000, 30_000_000), 1280, 1920, MatchPhase.REGULATION_FIRST_HALF, "synthetic-round-parser-v1", RoundBoundaryConfidence.EXACT, 0),
    Round("round-003", 3, TimeRange(30_000_000, 40_000_000), 1920, 2560, MatchPhase.REGULATION_SECOND_HALF, "synthetic-round-parser-v1", RoundBoundaryConfidence.EXACT, 0),
))
anchors = (
    TimeAnchor("anchor-demo-ticks", SourceClock.DEMO_TICK, "demo", 640, 2560, TimeRange(10_000_000, 40_000_000), 0, "synthetic-round-parser-v1"),
    TimeAnchor("anchor-alpha-001", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 0, 24_000, TimeRange(10_500_000, 11_500_000), 16_000, "synthetic-voice-extractor-v1"),
    TimeAnchor("anchor-alpha-002", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 24_000, 48_000, TimeRange(20_000_000, 21_000_000), 16_000, "synthetic-voice-extractor-v1"),
    TimeAnchor("anchor-alpha-unassigned", SourceClock.COMPACT_AUDIO_SAMPLE, "player-alpha", 48_000, 67_200, TimeRange(40_500_000, 41_300_000), 16_000, "synthetic-voice-extractor-v1"),
    TimeAnchor("anchor-bravo-001", SourceClock.COMPACT_AUDIO_SAMPLE, "player-bravo", 0, 28_800, TimeRange(20_500_000, 21_700_000), 16_000, "synthetic-voice-extractor-v1"),
)
timeline = DemoTimeline(descriptor, rounds, anchors)
asr_configuration = ModelConfigurationSnapshot(
    "asr-config-001", ModelCapability.ASR, "faster-whisper-local", None,
    "fixture-asr-model", None, {"language": "en"}, (), "asr-adapter-v1",
)
llm_configuration = ModelConfigurationSnapshot(
    "llm-config-001", ModelCapability.UNDERSTANDING_TRANSLATION, "openai-compatible",
    "provider-local-profile", "fixture-model", "understanding-v1",
    {"temperature": 0.2, "max_tokens": 512}, ("knowledge-global-001",), "adapter-v1",
)
voice_activities = (
    VoiceActivityCue("activity-alpha-001", "player-alpha", TimeRange(10_750_000, 11_250_000), 8, ("anchor-alpha-001",), 16_000),
    VoiceActivityCue("activity-bravo-001", "player-bravo", TimeRange(20_500_000, 21_700_000), 12, ("anchor-bravo-001",), 16_000),
    VoiceActivityCue("activity-alpha-002", "player-alpha", TimeRange(20_650_000, 20_950_000), 5, ("anchor-alpha-002",), 16_000),
    VoiceActivityCue("activity-alpha-unassigned", "player-alpha", TimeRange(40_500_000, 41_300_000), 7, ("anchor-alpha-unassigned",), 16_000),
)
transcripts = (
    TranscriptCue.from_source_span(
        cue_id="cue-first", player_id="player-alpha", round_id="round-001",
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE, source_stream_id="player-alpha",
        source_start=6_000, source_end=18_000, anchors=(anchors[1],),
        asr_original="one jungle", language="en", confidence=0.91,
        voice_activity_ids=("activity-alpha-001",), asr_invocation_record_id="asr-invoke-001",
    ),
    TranscriptCue.from_source_span(
        cue_id="cue-b-callout", player_id="player-bravo", round_id="round-002",
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE, source_stream_id="player-bravo",
        source_start=0, source_end=28_800, anchors=(anchors[4],),
        asr_original="be be be", language="en", confidence=0.62,
        voice_activity_ids=("activity-bravo-001",), asr_invocation_record_id="asr-invoke-001",
    ),
    TranscriptCue.from_source_span(
        cue_id="cue-overlap", player_id="player-alpha", round_id="round-002",
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE, source_stream_id="player-alpha",
        source_start=39_600, source_end=46_800, anchors=(anchors[2],),
        asr_original="two short", language="en", confidence=0.84,
        voice_activity_ids=("activity-alpha-002",), asr_invocation_record_id="asr-invoke-001",
    ),
    TranscriptCue.from_source_span(
        cue_id="cue-unassigned", player_id="player-alpha", round_id=None,
        source_clock=SourceClock.COMPACT_AUDIO_SAMPLE, source_stream_id="player-alpha",
        source_start=48_000, source_end=67_200, anchors=(anchors[3],),
        asr_original="after round chatter", language="en", confidence=0.74,
        voice_activity_ids=("activity-alpha-unassigned",), asr_invocation_record_id="asr-invoke-001",
    ),
)
results = (
    UnderstandingResult("cue-first", "round-001", "one jungle", "one jungle", "警家一个", 0.93, ("same-round-context",), (), "invoke-round-001"),
    UnderstandingResult("cue-b-callout", "round-002", "be be be", "B, B, B", "B点，B点，B点", 0.86, ("same-round-context", "case-letter-b-v1"), (), "invoke-round-002"),
    UnderstandingResult("cue-overlap", "round-002", "two short", "two short", "短箱两个", 0.88, ("same-round-context",), (), "invoke-round-002"),
)
round_one_request = {"round_id": "round-001", "transcript_cues": [transcripts[0].to_dict()]}
round_two_request = {"round_id": "round-002", "transcript_cues": [transcripts[1].to_dict(), transcripts[2].to_dict()]}
round_three_request = {"round_id": "round-003", "transcript_cues": []}
invocations = (
    ModelInvocationRecord.from_payloads(
        "asr-invoke-001", asr_configuration.snapshot_id, "asr-batch-001",
        {"audio_content_fingerprint": "9" * 64},
        {"cue_ids": [cue.cue_id for cue in transcripts]},
    ),
    ModelInvocationRecord.from_payloads(
        "invoke-round-001", llm_configuration.snapshot_id, "round-001", round_one_request,
        {"round_id": "round-001", "results": [results[0].to_dict()]},
    ),
    ModelInvocationRecord.from_payloads(
        "invoke-round-002", llm_configuration.snapshot_id, "round-002", round_two_request,
        {"round_id": "round-002", "results": [results[1].to_dict(), results[2].to_dict()]},
    ),
)
round_documents = (
    RoundUnderstandingDocument("round-001", content_fingerprint(round_one_request), llm_configuration.snapshot_id, "invoke-round-001", (results[0],)),
    RoundUnderstandingDocument("round-002", content_fingerprint(round_two_request), llm_configuration.snapshot_id, "invoke-round-002", (results[1], results[2])),
    RoundUnderstandingDocument("round-003", content_fingerprint(round_three_request), llm_configuration.snapshot_id, None, ()),
)
draft_timeline = compose_draft_timeline(
    timeline,
    transcripts,
    round_documents,
    (asr_configuration, llm_configuration),
    invocations,
)
draft_cues = draft_timeline.cues
decisions = (
    ReviewDecision("decision-first", "cue-first", draft_cues[0].understanding_result_fingerprint, ReviewAction.ACCEPT, "2026-08-31T12:00:00.000000Z", "local-user", None, None, None, None),
    ReviewDecision("decision-b-callout", "cue-b-callout", draft_cues[1].understanding_result_fingerprint, ReviewAction.EDIT, "2026-08-31T12:01:00.000000Z", "local-user", "将呼叫翻译调整为更自然的中文", None, None, "B点！B点！B点！"),
    ReviewDecision("decision-overlap", "cue-overlap", draft_cues[2].understanding_result_fingerprint, ReviewAction.ACCEPT, "2026-08-31T12:02:00.000000Z", "local-user", None, None, None, None),
)
reviewed_timeline = compose_reviewed_timeline(draft_timeline, decisions)
payload = {
    "schema_version": 1,
    "fixture_id": "new-domain-three-round-v1",
    "demo": descriptor.to_dict(),
    "rounds": rounds.to_dict(),
    "time_anchors": [item.to_dict() for item in anchors],
    "model_configurations": [asr_configuration.to_dict(), llm_configuration.to_dict()],
    "model_invocations": [item.to_dict() for item in invocations],
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
        "reviewed_cue_order": ["cue-first", "cue-b-callout", "cue-overlap"],
        "speechless_round_id": "round-003",
        "unassigned_cue_id": "cue-unassigned",
    },
}
```

The fixture must contain no SteamID, absolute path, URL, API key, credential, real Demo hash, or private media. Round 3 is deliberately a successful speechless round and `cue-unassigned` deliberately remains outside every round document; neither condition is represented by a fake result or fake invocation. `round_completion_order` proves that persisted aggregation ignores worker completion order, but it is not an attempt/failure log. Retriable failure state belongs to the later scheduler batch and must not be invented in 02A.

- [ ] **Step 4: Implement the standalone replay validator**

Create `scripts/check_new_domain_contract.py` that:

1. resolves the fixture relative to repository root;
2. loads JSON as UTF-8, rejects duplicate JSON object keys, and requires the exact transport keys shown in Step 3 with transport `schema_version == 1`;
3. calls Task 1 production `reject_private_data` on the complete payload before object construction; do not maintain a second fixture-only key/path list;
4. reconstructs every configuration, invocation, Demo, round, anchor, activity, transcript, understanding document, decision, draft timeline, and reviewed timeline exclusively through production `from_dict` factories; reject duplicate IDs in every collection and dangling configuration IDs in every invocation;
5. builds `DemoTimeline`, which applies production anchor-sequence and exact-round/tick validation, then calls `validate_voice_activity_against_timeline` and `validate_transcript_against_timeline` for every activity and transcript;
6. requires exactly one understanding document per known round, calls `validate_understanding_document_graph` for each, requires the expected speechless round to have zero results and no invocation, and requires the expected unassigned cue to have `round_id=None` and appear in no round document;
7. builds the expected draft only through production `compose_draft_timeline`, calls `validate_draft_timeline_graph` on the stored draft, recomposes the reviewed timeline only through `compose_reviewed_timeline`, compares it to the stored reviewed document, and calls `validate_reviewed_timeline_graph`;
8. checks the B callout source/interpretation/final translation against `expected` and checks reviewed cues are in expected Demo-time order despite the declared parallel completion order;
9. requires `round_completion_order` to be a duplicate-free permutation of all round IDs but never uses completion order to determine persisted cue order or fingerprints;
10. normalizes all schema, JSON, reference, privacy, and fingerprint failures to a concise `ContractValidationError` from the public `validate_contract(path: Path) -> None` function;
11. prints exactly `new domain contract replay passed` on success and returns 0; the CLI catches `ContractValidationError`, prints one concise line to stderr, and returns 1 without a traceback.

- [ ] **Step 5: Add adversarial tamper tests against the public validator**

Extend `tests/test_new_domain_contract_replay.py` with imports for `copy`, `json`, `pytest`, `Any`, `Callable`, and `validate_contract`/`ContractValidationError`. Define named mutators and this parameterized test; do not use a broad `pytest.raises(Exception)` assertion:

```python
FIXTURE = ROOT / "tests" / "golden" / "fixtures" / "new_domain_contract_v1.json"


def _secret(payload: dict[str, Any]) -> None:
    payload["model_configurations"][0]["api_key"] = "private"


def _windows_path(payload: dict[str, Any]) -> None:
    payload["demo"]["server_name"] = r"C:\private\demo.dem"


def _unix_path(payload: dict[str, Any]) -> None:
    payload["demo"]["server_name"] = "/home/private/demo.dem"


def _unc_path(payload: dict[str, Any]) -> None:
    payload["demo"]["server_name"] = r"\\server\share\demo.dem"


def _unknown_player(payload: dict[str, Any]) -> None:
    payload["transcript_cues"][0]["player_id"] = "player-missing"


def _dangling_invocation(payload: dict[str, Any]) -> None:
    payload["transcript_cues"][0]["asr_invocation_record_id"] = "asr-call-missing"


def _changed_asr(payload: dict[str, Any]) -> None:
    payload["round_understanding"][1]["results"][0]["asr_original"] = "B B B"


def _stale_review_fingerprint(payload: dict[str, Any]) -> None:
    payload["review_decisions"][0]["source_result_fingerprint"] = "0" * 64


def _stale_draft_input_fingerprint(payload: dict[str, Any]) -> None:
    payload["draft_timeline"]["input_fingerprint"] = "0" * 64


def _stale_configuration_fingerprint(payload: dict[str, Any]) -> None:
    payload["model_configurations"][1]["model_name"] = "tampered-model"


def _unsupported_schema(payload: dict[str, Any]) -> None:
    payload["schema_version"] = 2


def _reversed_cues(payload: dict[str, Any]) -> None:
    payload["draft_timeline"]["cues"].reverse()


def _overlapping_anchor_sources(payload: dict[str, Any]) -> None:
    payload["time_anchors"][2]["source_start"] = 12_000


TAMPERS: tuple[Callable[[dict[str, Any]], None], ...] = (
    _secret,
    _windows_path,
    _unix_path,
    _unc_path,
    _unknown_player,
    _dangling_invocation,
    _changed_asr,
    _stale_review_fingerprint,
    _stale_draft_input_fingerprint,
    _stale_configuration_fingerprint,
    _unsupported_schema,
    _reversed_cues,
    _overlapping_anchor_sources,
)


@pytest.mark.parametrize("mutate", TAMPERS, ids=lambda item: item.__name__)
def test_contract_tampering_is_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    payload = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    mutate(payload)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ContractValidationError):
        validate_contract(tampered)
```

- [ ] **Step 6: Run the fresh-process replay, tamper tests, and direct script**

Run:

```powershell
py -3.12 -m pytest tests/test_new_domain_contract_replay.py -q
py -3.12 scripts/check_new_domain_contract.py
```

Expected: test passes and direct script prints the unique success line.

- [ ] **Step 7: Document the isolated core and its verification command**

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

- [ ] **Step 8: Run documentation, fixture, and focused tests**

Run:

```powershell
git diff --check
py -3.12 -m pytest tests/test_domain_schema_v1.py tests/test_domain_timebase_v1.py tests/test_domain_timeline_v1.py tests/test_domain_invocation_v1.py tests/test_domain_understanding_v1.py tests/test_domain_review_v1.py tests/test_domain_validation_v1.py tests/test_new_domain_contract_replay.py -q
py -3.12 scripts/check_new_domain_contract.py
py -3.12 scripts/check_repository_hygiene.py
```

Expected: every command exits 0; the replay script prints its unique success line; hygiene reports pass.

- [ ] **Step 9: Commit the contract fixture and documentation**

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
rg -n "start_time|end_time" src/cs2pov/domain/errors.py src/cs2pov/domain/schema.py src/cs2pov/domain/fingerprint.py src/cs2pov/domain/timebase.py src/cs2pov/domain/timeline.py src/cs2pov/domain/invocation.py src/cs2pov/domain/voice.py src/cs2pov/domain/transcript.py src/cs2pov/domain/understanding.py src/cs2pov/domain/review.py src/cs2pov/domain/validation.py
rg -n "api_key|authorization|access_token|password" tests/golden/fixtures/new_domain_contract_v1.json
```

Expected:

- changed production files are limited to the eleven new domain modules;
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
