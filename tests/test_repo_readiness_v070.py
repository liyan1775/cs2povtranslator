from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_readiness_docs_exist():
    required = [
        "README.zh.md",
        "README.md",
        "CHANGELOG.md",
        "ROADMAP.md",
        "CONTRIBUTING.md",
        "LICENSE",
        ".gitignore",
        "docs/ARCHITECTURE.zh.md",
        "docs/TESTING_GUIDE.zh.md",
        "docs/SECURITY_AND_PRIVACY.zh.md",
        "docs/RELEASE_CHECKLIST.zh.md",
        "docs/DEVELOPMENT_WORKFLOW.zh.md",
        "docs/SHOWCASE.zh.md",
        "docs/GLOSSARY_MIRAGE_PILOT.zh.md",
    ]
    missing = [name for name in required if not (ROOT / name).exists()]
    assert missing == []


def test_version_markers_are_updated_to_v070():
    assert 'version = "0.7.1"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '__version__ = "0.7.1"' in (ROOT / "src/cs2pov/__init__.py").read_text(encoding="utf-8")
    assert "CS2 POV Translator v0.7.1" in (ROOT / "README.zh.md").read_text(encoding="utf-8")
    assert "CS2 POV Translator v0.7.1" in (ROOT / "Start_CS2_POV_Translator.bat").read_text(encoding="utf-8")


def test_docs_describe_privacy_and_feedback_boundaries():
    privacy = (ROOT / "docs/SECURITY_AND_PRIVACY.zh.md").read_text(encoding="utf-8")
    assert "API key" in privacy
    assert "原始 demo" in privacy
    assert "本地绝对路径" in privacy
    testing = (ROOT / "docs/TESTING_GUIDE.zh.md").read_text(encoding="utf-8")
    assert "反馈包" in testing
    assert "不应包含" in testing


def test_changelog_and_roadmap_include_v070():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert "v0.7.1" in changelog
    assert "v0.7.x" in roadmap
    assert "GitHub" in roadmap
