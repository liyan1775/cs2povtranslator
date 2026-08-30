from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import copyfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
HYGIENE_SCRIPT = ROOT / "scripts" / "check_repository_hygiene.py"


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run_hygiene(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HYGIENE_SCRIPT), "--root", str(repo)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def test_hygiene_rejects_unignored_api_key_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    (repo / "README.md").write_text("safe\n", encoding="utf-8")
    (repo / "apikey.txt").write_text("placeholder\n", encoding="utf-8")

    result = _run_hygiene(repo)

    assert result.returncode == 1, result.stderr
    assert "apikey.txt" in result.stdout


def test_hygiene_reports_probable_secret_without_echoing_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    fake_secret = "sk-" + "a" * 32
    (repo / "settings.txt").write_text(f"token={fake_secret}\n", encoding="utf-8")

    result = _run_hygiene(repo)

    assert result.returncode == 1, result.stderr
    assert "settings.txt" in result.stdout
    assert fake_secret not in result.stdout
    assert fake_secret not in result.stderr


@pytest.mark.parametrize("filename", ["match.dem", "voice.wav", "release.zip", "model.safetensors"])
def test_hygiene_rejects_generated_and_large_asset_types(tmp_path: Path, filename: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    (repo / filename).write_bytes(b"fixture")

    result = _run_hygiene(repo)

    assert result.returncode == 1, result.stderr
    assert filename in result.stdout


def test_hygiene_rejects_unexpected_large_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    large_file = repo / "large.dat"
    with large_file.open("wb") as stream:
        stream.seek(10 * 1024 * 1024)
        stream.write(b"x")

    result = _run_hygiene(repo)

    assert result.returncode == 1, result.stderr
    assert "large.dat" in result.stdout


def test_project_gitignore_excludes_secrets_workspace_and_generated_assets(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    copyfile(ROOT / ".gitignore", repo / ".gitignore")
    protected_paths = [
        "apikey.txt",
        ".env.local",
        "workspace/jobs/job.json",
        "models/whisper/model.bin",
        "cache/temp.bin",
        "jobs/demo/manifest.json",
        "renders/round-01.mp4",
        "release.zip",
    ]
    for relative in protected_paths:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"local-only")

    missing = []
    for relative in protected_paths:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative],
            cwd=repo,
            check=False,
        )
        if result.returncode != 0:
            missing.append(relative)

    assert missing == []


@pytest.mark.parametrize(
    "relative",
    [
        "workspace/jobs/job.json",
        "models/whisper/config.json",
        "cache/transcript.json",
        "jobs/demo/manifest.json",
        "renders/round-01.json",
    ],
)
def test_hygiene_rejects_force_added_local_workspace_paths(tmp_path: Path, relative: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    copyfile(ROOT / ".gitignore", repo / ".gitignore")
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    _run_git(repo, "add", "--force", "--", relative)

    result = _run_hygiene(repo)

    assert result.returncode == 1, result.stderr
    assert relative in result.stdout
