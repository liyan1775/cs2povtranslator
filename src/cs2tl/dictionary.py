"""Dictionary management — clone, parse, index, and validate CS2 callout dictionaries.

The dictionary is a separate Git repository with per-map directories.
Each map directory contains a zones.yml with callout term definitions.

DictionaryManager handles:
  - git clone / git pull lifecycle
  - YAML parsing (safe_load only)
  - Building alias→term indices for LLM prompt injection
  - Terminology validation on translated output
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CalloutTerm:
    """A single callout / map position with its aliases and canonical Chinese name."""

    aliases: list[str]  # e.g., ["A short", "catwalk", "cat"]
    chinese_name: str  # e.g., "A小道"
    map_name: str  # e.g., "de_dust2"
    category: str = "zone"  # zone | bombsite | spawn | landmark | position | nade

    @property
    def primary_alias(self) -> str:
        return self.aliases[0] if self.aliases else ""


@dataclass
class MapDictionary:
    """Loaded dictionary for one CS2 map."""

    map_name: str
    version: str  # from zones.yml
    terms: list[CalloutTerm] = field(default_factory=list)
    _alias_index: dict[str, CalloutTerm] = field(default_factory=dict, repr=False)

    def build_index(self) -> None:
        """Build alias→term lookup index. Must be called after loading terms."""
        self._alias_index.clear()
        for term in self.terms:
            for alias in term.aliases:
                key = alias.lower().strip()
                if key not in self._alias_index:
                    self._alias_index[key] = term

    def lookup(self, alias: str) -> CalloutTerm | None:
        """Look up a term by any of its aliases (case-insensitive)."""
        return self._alias_index.get(alias.lower().strip())

    def get_chinese_names(self) -> set[str]:
        """Return the set of canonical Chinese names in this dictionary."""
        return {t.chinese_name for t in self.terms}


# ---------------------------------------------------------------------------
# DictionaryManager
# ---------------------------------------------------------------------------

class DictionaryManager:
    """Manages the lifecycle of the callout dictionary repository."""

    def __init__(self, repo_url: str, local_path: Path):
        self.repo_url = repo_url
        self.local_path = Path(local_path)
        self._loaded: dict[str, MapDictionary] = {}

    # ---- git operations ----

    def ensure_cloned(self) -> None:
        """Clone the dictionary repo if it doesn't exist; pull if auto_update is on."""
        if not self.local_path.exists():
            self.local_path.mkdir(parents=True, exist_ok=True)

        # Check if the directory is a git repo
        git_dir = self.local_path / ".git"
        if not git_dir.exists():
            self._clone()
        else:
            # Already cloned — pull is handled by update()
            pass

    def _clone(self) -> None:
        """Clone the repository. Uses GitPython if available, subprocess fallback."""
        from cs2tl.errors import dictionary_clone_failed

        try:
            import git as _git_mod
            from git import GitCommandError

            logger.info("Cloning dictionary repo from %s...", self.repo_url)
            _git_mod.Repo.clone_from(self.repo_url, str(self.local_path), depth=1)
            logger.info("Dictionary cloned successfully.")
        except ImportError:
            # Fallback to subprocess
            import subprocess
            result = subprocess.run(
                ["git", "clone", "--depth=1", self.repo_url, str(self.local_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise dictionary_clone_failed(self.repo_url, result.stderr.strip())
        except Exception as e:
            raise dictionary_clone_failed(self.repo_url, str(e)) from e

    def update(self) -> bool:
        """Pull latest changes. Returns True if there were updates, False if already current."""
        from cs2tl.errors import dictionary_clone_failed

        try:
            import git as _git_mod
            from git import GitCommandError

            if not (self.local_path / ".git").exists():
                self.ensure_cloned()
                return True  # fresh clone counts as updated

            repo = _git_mod.Repo(str(self.local_path))
            before = repo.head.commit.hexsha
            origin = repo.remotes.origin
            origin.pull()
            after = repo.head.commit.hexsha
            updated = before != after
            if updated:
                logger.info("Dictionary updated: %s → %s", before[:7], after[:7])
            return updated
        except ImportError:
            import subprocess
            if not (self.local_path / ".git").exists():
                self.ensure_cloned()
                return True
            before = self._git_head()
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(self.local_path),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise dictionary_clone_failed(self.repo_url, result.stderr.strip())
            after = self._git_head()
            return before != after
        except Exception as e:
            if "GitCommandError" in type(e).__name__ or "GitError" in type(e).__name__:
                raise dictionary_clone_failed(self.repo_url, str(e)) from e
            raise

    def _git_head(self) -> str:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.local_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"

    # ---- loading + indexing ----

    def load_all(self) -> dict[str, MapDictionary]:
        """Load all map dictionaries from the local repo. Returns {map_name: MapDictionary}."""
        from cs2tl.errors import dictionary_yaml_error

        self._loaded.clear()

        if not self.local_path.exists():
            logger.warning("Dictionary path does not exist: %s", self.local_path)
            return {}

        for entry in sorted(self.local_path.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") or entry.name == "schemas":
                continue
            zones_yml = entry / "zones.yml"
            if not zones_yml.exists():
                continue

            try:
                map_dict = self._load_one(entry.name, zones_yml)
                self._loaded[entry.name] = map_dict
                logger.info(
                    "Loaded dictionary for %s: %d terms",
                    entry.name,
                    len(map_dict.terms),
                )
            except Exception as e:
                logger.warning("Skipping %s: %s", entry.name, e)
                continue

        return self._loaded

    def _load_one(self, map_name: str, yml_path: Path) -> MapDictionary:
        """Parse a single zones.yml into a MapDictionary."""
        import yaml

        from cs2tl.errors import dictionary_yaml_error

        try:
            with open(yml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise dictionary_yaml_error(map_name, f"YAML parse error: {e}") from e

        if not isinstance(data, dict):
            raise dictionary_yaml_error(map_name, "Expected a YAML mapping at top level")

        version = str(data.get("version", "unknown"))
        raw_terms: list[dict[str, Any]] = data.get("terms", [])
        if not isinstance(raw_terms, list):
            raise dictionary_yaml_error(map_name, "'terms' must be a list")

        terms: list[CalloutTerm] = []
        for i, raw in enumerate(raw_terms):
            if not isinstance(raw, dict):
                raise dictionary_yaml_error(map_name, f"Term {i}: expected a mapping")
            aliases = raw.get("aliases", [])
            if not aliases:
                raise dictionary_yaml_error(map_name, f"Term {i}: missing 'aliases'")
            chinese = raw.get("chinese", "")
            if not chinese:
                raise dictionary_yaml_error(map_name, f"Term {i}: missing 'chinese'")
            category = raw.get("category", "zone")

            terms.append(
                CalloutTerm(
                    aliases=[str(a) for a in aliases],
                    chinese_name=str(chinese),
                    map_name=map_name,
                    category=str(category),
                )
            )

        map_dict = MapDictionary(map_name=map_name, version=version, terms=terms)
        map_dict.build_index()
        return map_dict

    # ---- query helpers ----

    def get_terms_for_map(self, map_name: str) -> MapDictionary | None:
        """Return the loaded dictionary for a specific map, or None."""
        if not self._loaded:
            self.load_all()
        return self._loaded.get(map_name)

    def list_maps(self) -> list[str]:
        """List all available map dictionaries."""
        if not self._loaded:
            self.load_all()
        return sorted(self._loaded.keys())

    def show_coverage(self, map_name: str) -> dict:
        """Return coverage stats for a map dictionary."""
        md = self.get_terms_for_map(map_name)
        if md is None:
            return {"map": map_name, "error": "Dictionary not found"}

        categories: dict[str, int] = {}
        for term in md.terms:
            categories[term.category] = categories.get(term.category, 0) + 1

        return {
            "map": map_name,
            "version": md.version,
            "total_terms": len(md.terms),
            "total_aliases": sum(len(t.aliases) for t in md.terms),
            "by_category": categories,
        }

    # ---- LLM prompt support ----

    def build_term_table(self, map_name: str, max_terms: int = 50) -> str:
        """Build a markdown term table for injection into the LLM system prompt."""
        md = self.get_terms_for_map(map_name)
        if md is None or not md.terms:
            return f"No dictionary available for {map_name}."

        lines = [
            f"CS2 Callout Dictionary — {map_name}",
            "",
            "| English / Alias | Chinese Term | Category |",
            "|-----------------|-------------|----------|",
        ]
        for term in md.terms[:max_terms]:
            aliases = ", ".join(term.aliases[:4])
            lines.append(f"| {aliases} | {term.chinese_name} | {term.category} |")

        if len(md.terms) > max_terms:
            lines.append(f"| ... and {len(md.terms) - max_terms} more terms | | |")

        return "\n".join(lines)

    # ---- validation ----

    def validate_terms(self, translated_text: str, map_name: str) -> list[str]:
        """Check that CS terms in translated output use correct names. Returns warnings."""
        warnings: list[str] = []
        md = self.get_terms_for_map(map_name)
        if md is None:
            return warnings

        # Check: if the output contains an English alias that exists in the
        # dictionary but wasn't translated to Chinese, that's a warning.
        for term in md.terms:
            for alias in term.aliases:
                if alias.lower() in translated_text.lower():
                    # The English alias appears untranslated — but this could be
                    # intentional (e.g., the player said "B" and we want it as is).
                    # Only warn for longer aliases (>3 chars) that are clearly
                    # meant to be translated.
                    if len(alias) > 3:
                        warnings.append(
                            f"Possible untranslated term: '{alias}' found in output. "
                            f"Expected: '{term.chinese_name}'"
                        )

        return warnings
