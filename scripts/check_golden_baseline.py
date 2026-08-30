from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests" / "golden" / "manifest.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_KINDS = {
    "authorized_demo",
    "representative_local_demo",
    "synthetic_audio",
    "synthetic_video",
    "structured_timeline",
}


def _contains_forbidden_local_metadata(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in {"path", "steamid", "steam_id"} or normalized.endswith("_path"):
                return True
            if _contains_forbidden_local_metadata(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_local_metadata(item) for item in value)
    if isinstance(value, str):
        return bool(re.match(r"^(?:[a-zA-Z]:[\\/]|/|\\\\)", value))
    return False


def _fail(message: str) -> None:
    raise ValueError(message)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"cannot read JSON {path}: {exc}")
    if not isinstance(data, dict):
        _fail(f"JSON root must be an object: {path}")
    return data


def _checked_in_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        _fail(f"checked-in fixture path must be relative: {relative}")
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        _fail(f"checked-in fixture escapes repository: {relative}")
    return resolved


def _check_sha(path: Path, expected: str) -> None:
    if not SHA256_RE.fullmatch(expected):
        _fail(f"invalid SHA-256 declaration for {path}")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        _fail(f"cannot inspect golden input {path}: {exc}")
    if actual != expected:
        _fail(f"golden input hash mismatch: {path.relative_to(ROOT)}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_local_fixture(manifest: dict[str, Any], declaration: str) -> str:
    if "=" not in declaration:
        _fail("local fixture must use FIXTURE_ID=FILE syntax")
    fixture_id, raw_path = declaration.split("=", 1)
    fixtures = manifest.get("fixtures", [])
    fixture = next(
        (item for item in fixtures if item.get("id") == fixture_id), None
    )
    if fixture is None or fixture.get("storage") != "local-only":
        _fail(f"unknown local-only fixture ID: {fixture_id}")

    path = Path(raw_path)
    try:
        size = path.stat().st_size
        actual_hash = _file_sha256(path)
    except OSError:
        _fail(f"cannot inspect local fixture: {fixture_id}")
    if size != fixture["byte_size"] or actual_hash != fixture["sha256"]:
        _fail(f"local fixture size or hash mismatch: {fixture_id}")
    return fixture_id


def validate_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _load_json(path)
    if manifest.get("schema_version") != 1:
        _fail("golden manifest schema_version must be 1")

    baseline = manifest.get("baseline", {})
    if baseline.get("version") != "0.9.8" or not re.fullmatch(
        r"[0-9a-f]{40}", str(baseline.get("commit", ""))
    ):
        _fail("golden manifest must identify the v0.9.8 baseline commit")

    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        _fail("golden manifest fixtures must be a non-empty list")
    ids = [str(item.get("id", "")) for item in fixtures if isinstance(item, dict)]
    if len(ids) != len(fixtures) or any(not item for item in ids) or len(ids) != len(set(ids)):
        _fail("golden fixture IDs must be present and unique")
    kinds = {str(item.get("kind", "")) for item in fixtures}
    missing_kinds = REQUIRED_KINDS - kinds
    if missing_kinds:
        _fail(f"golden fixture classes missing: {sorted(missing_kinds)}")

    for fixture in fixtures:
        storage = fixture.get("storage")
        if storage == "checked-in":
            relative = fixture.get("path")
            if not isinstance(relative, str) or not relative:
                _fail(f"checked-in fixture has no path: {fixture['id']}")
            _check_sha(_checked_in_path(relative), str(fixture.get("sha256", "")))
        elif storage == "local-only":
            if not SHA256_RE.fullmatch(str(fixture.get("sha256", ""))):
                _fail(f"local fixture has invalid SHA-256: {fixture['id']}")
            if not isinstance(fixture.get("byte_size"), int) or fixture["byte_size"] <= 0:
                _fail(f"local fixture has invalid byte_size: {fixture['id']}")
            if _contains_forbidden_local_metadata(fixture):
                _fail(f"local fixture exposes forbidden location/identity fields: {fixture['id']}")
        else:
            _fail(f"unknown fixture storage for {fixture['id']}: {storage}")

    cases = manifest.get("understanding_translation_cases", [])
    if not any(
        case.get("asr_text") == "be be be" and case.get("interpreted_text") == "B, B, B"
        for case in cases
        if isinstance(case, dict)
    ):
        _fail("understanding-translation B callout case is missing")

    outputs = manifest.get("legacy_outputs")
    if not isinstance(outputs, list) or not outputs:
        _fail("legacy_outputs must be a non-empty list")
    for output in outputs:
        if output.get("storage") == "local-only":
            if not SHA256_RE.fullmatch(str(output.get("sha256", ""))):
                _fail(f"local legacy output has invalid SHA-256: {output.get('id')}")
            if _contains_forbidden_local_metadata(output):
                _fail(
                    "local legacy output exposes forbidden location/identity fields: "
                    f"{output.get('id')}"
                )
            continue
        relative = output.get("path")
        if not isinstance(relative, str) or not relative:
            _fail(f"checked-in legacy output has no path: {output.get('id')}")
        _check_sha(_checked_in_path(relative), str(output.get("sha256", "")))

    if not manifest.get("known_defects"):
        _fail("known_defects must not be empty")
    test_nodes = manifest.get("baseline_test_nodes")
    if not isinstance(test_nodes, list) or not test_nodes:
        _fail("baseline_test_nodes must be a non-empty list")
    for node in test_nodes:
        if not isinstance(node, str) or not node.startswith("tests/") or ".." in Path(node).parts:
            _fail(f"unsafe baseline test node: {node!r}")
        if not _checked_in_path(node).is_file():
            _fail(f"baseline test node does not exist: {node}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and replay the v0.9.8 golden baseline.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--local-fixture",
        action="append",
        default=[],
        metavar="FIXTURE_ID=FILE",
        help="Verify a local-only fixture without storing or printing its path.",
    )
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()

    try:
        manifest = validate_manifest(args.manifest)
    except ValueError as exc:
        print(f"golden baseline check failed: {exc}", file=sys.stderr)
        return 1

    try:
        verified = [
            verify_local_fixture(manifest, declaration)
            for declaration in args.local_fixture
        ]
    except ValueError as exc:
        print(f"golden baseline check failed: {exc}", file=sys.stderr)
        return 1
    for fixture_id in verified:
        print(f"local fixture verified: {fixture_id}")

    if args.replay:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *manifest["baseline_test_nodes"]],
            cwd=ROOT,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode
    print("golden baseline check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
