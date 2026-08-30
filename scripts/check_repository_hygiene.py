from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


PROHIBITED_FILE_NAMES = {"api_key.txt", "apikey.txt"}
PROHIBITED_ROOT_DIRECTORIES = {"cache", "jobs", "models", "renders", "workspace", "workspaces"}
PROHIBITED_SUFFIXES = (
    ".7z",
    ".avi",
    ".ckpt",
    ".dem",
    ".dem.zst",
    ".flac",
    ".gguf",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".onnx",
    ".pt",
    ".pth",
    ".rar",
    ".safetensors",
    ".wav",
    ".zip",
)
PROBABLE_SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
)
MAX_FILE_BYTES = 10 * 1024 * 1024


def repository_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [Path(item.decode("utf-8", errors="surrogateescape")) for item in result.stdout.split(b"\0") if item]


def scan_repository(root: Path) -> list[str]:
    findings: list[str] = []
    for relative_path in repository_files(root):
        root_directory = relative_path.parts[0].casefold() if len(relative_path.parts) > 1 else ""
        if root_directory in PROHIBITED_ROOT_DIRECTORIES:
            findings.append(f"prohibited local-data path: {relative_path.as_posix()}")
            continue
        normalized_name = relative_path.name.casefold()
        if normalized_name in PROHIBITED_FILE_NAMES:
            findings.append(f"prohibited filename: {relative_path.as_posix()}")
            continue
        if normalized_name.endswith(PROHIBITED_SUFFIXES):
            findings.append(f"prohibited asset type: {relative_path.as_posix()}")
            continue
        path = root / relative_path
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                findings.append(f"file exceeds 10 MiB: {relative_path.as_posix()}")
                continue
            content = path.read_bytes()
        except OSError:
            continue
        if any(pattern.search(content) for pattern in PROBABLE_SECRET_PATTERNS):
            findings.append(f"probable secret content: {relative_path.as_posix()}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject secrets and generated assets before they enter Git.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    try:
        findings = scan_repository(args.root.resolve())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"repository hygiene check could not run: {exc}")
        return 2

    if findings:
        print("repository hygiene check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("repository hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
