from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cs2pov.domain.models import TranslationSegment
from cs2pov.domain.subtitle import bilingual_text, render_srt


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = ROOT / "tests" / "golden"
MANIFEST_PATH = GOLDEN_ROOT / "manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_golden_manifest_covers_all_required_fixture_classes():
    manifest = _manifest()

    assert manifest["schema_version"] == 1
    assert manifest["baseline"] == {
        "version": "0.9.8",
        "commit": "7f26212dc46b4a0a710ffef2fd69902f5e80bb5d",
    }

    fixtures = {fixture["id"]: fixture for fixture in manifest["fixtures"]}
    assert {fixture["kind"] for fixture in fixtures.values()} >= {
        "authorized_demo",
        "representative_local_demo",
        "synthetic_audio",
        "synthetic_video",
        "structured_timeline",
    }

    demo_fixtures = [
        fixture
        for fixture in fixtures.values()
        if fixture["kind"] in {"authorized_demo", "representative_local_demo"}
    ]
    assert len(demo_fixtures) >= 2
    for fixture in demo_fixtures:
        assert fixture["storage"] == "local-only"
        assert len(fixture["sha256"]) == 64
        assert fixture["byte_size"] > 0
        assert "path" not in fixture
        assert "steamid" not in json.dumps(fixture).lower()


def test_checked_in_golden_inputs_match_declared_hashes():
    manifest = _manifest()

    checked_in = [
        fixture for fixture in manifest["fixtures"] if fixture["storage"] == "checked-in"
    ]
    assert checked_in
    for fixture in checked_in:
        relative_path = Path(fixture["path"])
        assert not relative_path.is_absolute()
        payload = (ROOT / relative_path).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == fixture["sha256"]


def test_golden_files_are_checked_out_with_lf_on_every_platform():
    manifest = _manifest()
    paths = [
        fixture["path"]
        for fixture in manifest["fixtures"]
        if fixture["storage"] == "checked-in"
    ] + [
        output["path"]
        for output in manifest["legacy_outputs"]
        if output.get("storage") != "local-only"
    ]

    result = subprocess.run(
        ["git", "check-attr", "eol", "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count(": eol: lf") == len(paths), result.stdout


def test_timeline_records_round_players_speech_and_understanding_case():
    manifest = _manifest()
    fixture = next(
        item for item in manifest["fixtures"] if item["kind"] == "structured_timeline"
    )
    timeline = json.loads((ROOT / fixture["path"]).read_text(encoding="utf-8"))

    assert timeline["rounds"]
    assert timeline["players"]
    assert timeline["speech_segments"]
    for segment in timeline["speech_segments"]:
        assert segment["start_time"] < segment["end_time"]
        assert segment["player_id"] in {player["id"] for player in timeline["players"]}

    understanding_cases = manifest["understanding_translation_cases"]
    assert any(
        case["asr_text"] == "be be be" and case["interpreted_text"] == "B, B, B"
        for case in understanding_cases
    )


def test_v098_subtitle_golden_output_replays_exactly():
    manifest = _manifest()
    timeline_fixture = next(
        item for item in manifest["fixtures"] if item["kind"] == "structured_timeline"
    )
    timeline = json.loads(
        (ROOT / timeline_fixture["path"]).read_text(encoding="utf-8")
    )
    segments = [
        TranslationSegment(
            **{key: value for key, value in item.items() if key != "player_id"},
            steamid=item["player_id"],
        )
        for item in timeline["translation_segments"]
    ]
    actual = render_srt(segments, bilingual_text)

    expected = manifest["legacy_outputs"][0]
    expected_path = ROOT / expected["path"]
    assert hashlib.sha256(expected_path.read_bytes()).hexdigest() == expected["sha256"]
    assert actual == expected_path.read_text(encoding="utf-8")
    assert manifest["known_defects"]


def test_golden_checker_validates_manifest_without_replaying_pytest():
    result = subprocess.run(
        [sys.executable, "scripts/check_golden_baseline.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "golden baseline check passed" in result.stdout


def test_golden_checker_fails_closed_on_hash_mismatch(tmp_path):
    manifest = _manifest()
    fixture = next(
        item for item in manifest["fixtures"] if item["storage"] == "checked-in"
    )
    fixture["sha256"] = "0" * 64
    tampered_manifest = tmp_path / "manifest.json"
    tampered_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_golden_baseline.py",
            "--manifest",
            str(tampered_manifest),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 1
    assert "hash mismatch" in result.stderr
    assert fixture["sha256"] not in result.stdout + result.stderr


def test_golden_checker_matches_local_demo_by_id_without_echoing_path_or_hash(tmp_path):
    local_demo = tmp_path / "authorized-fixture.dem"
    local_demo.write_bytes(b"small authorized fixture for validator test")
    local_hash = hashlib.sha256(local_demo.read_bytes()).hexdigest()

    manifest = _manifest()
    fixture = next(
        item for item in manifest["fixtures"] if item["kind"] == "authorized_demo"
    )
    fixture["sha256"] = local_hash
    fixture["byte_size"] = local_demo.stat().st_size
    local_manifest = tmp_path / "manifest.json"
    local_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_golden_baseline.py",
            "--manifest",
            str(local_manifest),
            "--local-fixture",
            f"{fixture['id']}={local_demo}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert f"local fixture verified: {fixture['id']}" in result.stdout
    assert str(local_demo) not in output
    assert local_hash not in output


def test_golden_checker_rejects_nested_local_path_metadata(tmp_path):
    manifest = _manifest()
    fixture = next(
        item for item in manifest["fixtures"] if item["storage"] == "local-only"
    )
    fixture["expected"]["input_path"] = "D:/private/demo.dem"
    leaking_manifest = tmp_path / "manifest.json"
    leaking_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_golden_baseline.py",
            "--manifest",
            str(leaking_manifest),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 1
    assert "forbidden location/identity" in result.stderr
    assert "D:/private/demo.dem" not in result.stdout + result.stderr
