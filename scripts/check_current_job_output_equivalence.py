from __future__ import annotations

"""Replay the v0.9.8 fixture through the current Job subtitle adapter."""

# ruff: noqa: E402

import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cs2pov.application.subtitle_ports import adapt_draft_timeline, render_current_srt  # noqa: E402
from cs2pov.domain.fingerprint import content_fingerprint  # noqa: E402
from cs2pov.domain.review import DraftCommsCue, DraftCommsTimeline  # noqa: E402


FIXTURE_PATH = ROOT / "tests" / "golden" / "fixtures" / "structured_timeline_v1.json"
EXPECTED_PATH = ROOT / "tests" / "golden" / "expected" / "v0.9.8_bilingual.srt"
MICROSECONDS_PER_SECOND = Decimal("1000000")


def _seconds_to_us(value: Any) -> int:
    try:
        decimal_value = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - fixture corruption path
        raise ValueError("golden time is not numeric") from exc
    if decimal_value < 0:
        raise ValueError("golden time must be non-negative")
    return int(
        (decimal_value * MICROSECONDS_PER_SECOND).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )


def _legacy_rows(data: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    rows = []
    for item in data["translation_segments"]:
        rows.append(
            (
                item["id"],
                item["round_number"],
                item["player_id"],
                item["player_name"],
                item["team_number"],
                _seconds_to_us(item["start_time"]),
                _seconds_to_us(item["end_time"]),
                item["original_text"],
                item["translated_text"],
            )
        )
    return tuple(sorted(rows, key=lambda row: (row[5], row[6], row[0])))


def _current_timeline(data: dict[str, Any]) -> DraftCommsTimeline:
    players = {item["id"]: item for item in data["players"]}
    cues = []
    for item in data["translation_segments"]:
        player = players[item["player_id"]]
        cue_id = item["id"]
        understanding = {
            "cue_id": cue_id,
            "translated_text": item["translated_text"],
        }
        cues.append(
            DraftCommsCue(
                cue_id,
                f"round-{int(item['round_number']):03d}",
                item["player_id"],
                _seconds_to_us(item["start_time"]),
                _seconds_to_us(item["end_time"]),
                item["original_text"],
                item["original_text"],
                item["translated_text"],
                1.0,
                ("golden_fixture",),
                content_fingerprint(understanding),
            )
        )
        if player["team_number"] != item["team_number"]:
            raise ValueError(f"fixture player metadata disagrees for {cue_id}")
    return DraftCommsTimeline(
        "a" * 64,
        "demo-microseconds",
        "b" * 64,
        tuple(sorted(cues, key=lambda cue: (cue.start_us, cue.end_us, cue.cue_id))),
    )


def _current_rows(data: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    timeline = _current_timeline(data)
    players = {item["id"]: item for item in data["players"]}
    names = {player_id: item["display_name"] for player_id, item in players.items()}
    teams = {player_id: item["team_number"] for player_id, item in players.items()}
    cues = adapt_draft_timeline(timeline, player_names=names, team_numbers=teams)
    rows = []
    for cue in cues:
        try:
            round_number = int(cue.round_id.rsplit("-", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError("current round identifier is not comparable") from exc
        rows.append(
            (
                cue.cue_id,
                round_number,
                cue.player_id,
                cue.player_name,
                cue.team_number,
                cue.start_us,
                cue.end_us,
                cue.original_text,
                cue.translated_text,
            )
        )
    return tuple(sorted(rows, key=lambda row: (row[5], row[6], row[0])))


def validate_equivalence() -> None:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if _legacy_rows(data) != _current_rows(data):
        raise ValueError("legacy and current canonical subtitle rows differ")

    timeline = _current_timeline(data)
    players = {item["id"]: item for item in data["players"]}
    current = render_current_srt(
        adapt_draft_timeline(
            timeline,
            player_names={key: value["display_name"] for key, value in players.items()},
            team_numbers={key: value["team_number"] for key, value in players.items()},
        ),
        "bilingual",
        preset="review",
    )
    expected = EXPECTED_PATH.read_text(encoding="utf-8")
    if current != expected:
        raise ValueError("current bilingual SRT differs from the v0.9.8 golden output")


def main() -> int:
    try:
        validate_equivalence()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"current Job output equivalence check failed: {exc}", file=sys.stderr)
        return 1
    print("current Job output equivalence passed: canonical rows and v0.9.8 bilingual SRT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
