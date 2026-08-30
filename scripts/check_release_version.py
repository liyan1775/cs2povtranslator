from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


VERSION_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)


def load_versions(root: Path) -> tuple[str, str]:
    with (root / "pyproject.toml").open("rb") as stream:
        project_version = str(tomllib.load(stream)["project"]["version"])
    module_text = (root / "src" / "cs2pov" / "__init__.py").read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(module_text)
    if match is None:
        raise ValueError("src/cs2pov/__init__.py does not define __version__")
    return project_version, match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a release tag matches package version markers.")
    parser.add_argument("tag", help="Git tag in vMAJOR.MINOR.PATCH form")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    expected_tag = args.tag.removeprefix("v")
    try:
        project_version, module_version = load_versions(args.root.resolve())
    except (OSError, KeyError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"release version check could not run: {exc}")
        return 2

    if project_version != module_version or expected_tag != project_version:
        print(
            "release version check failed: "
            f"tag={args.tag}, pyproject={project_version}, module={module_version}"
        )
        return 1

    print(f"release version check passed: {args.tag} -> {project_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
