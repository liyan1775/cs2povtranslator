"""Dictionary management — load, parse, index, and validate CS2 callout dictionaries.

DictionaryManager handles:
  - Built-in YAML dictionary (shipped in the wheel, always available)
  - Optional local YAML overrides (cs2tl-data/dictionaries/)
  - YAML parsing (safe_load only)
  - Building alias→term indices for LLM prompt injection
  - Terminology validation on translated output
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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
    russian_aliases: list[str] = field(default_factory=list)  # e.g., ["короткий", "шорт"]

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
        """Build alias→term lookup index (English + Russian). Must be called after loading terms."""
        self._alias_index.clear()
        for term in self.terms:
            for alias in term.aliases:
                key = alias.lower().strip()
                if key not in self._alias_index:
                    self._alias_index[key] = term
            for ra in term.russian_aliases:
                key = ra.lower().strip()
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
    """Manages CS2 callout dictionaries — built-in YAML + optional local overrides.

    Built-in dictionaries are shipped inside the wheel (``src/cs2tl/data/``)
    and are always available.  Local YAML files in ``cs2tl-data/dictionaries/``
    (one directory per map with a ``zones.yml``) can supplement or override
    the built-in data.
    """

    # The 7 active-duty competitive maps
    KNOWN_MAPS = frozenset({
        "de_dust2", "de_mirage", "de_inferno", "de_nuke",
        "de_overpass", "de_anubis", "de_ancient",
    })

    def __init__(self, repo_url: str = "", local_path: Path | str | None = None):
        # repo_url is kept for backward compatibility with existing callers;
        # it is no longer used (dictionary ships with the wheel).
        self.repo_url = repo_url
        self.local_path = Path(local_path) if local_path else Path()
        self._loaded: dict[str, MapDictionary] = {}

    # ---- loading ----

    def load_builtin(self) -> dict[str, MapDictionary]:
        """Load the built-in dictionary from the wheel's data directory."""
        from importlib import resources

        builtin_yml = resources.files("cs2tl.data") / "builtin_dictionary.yml"
        if not builtin_yml.is_file():
            logger.warning("Built-in dictionary not found in package data")
            return {}

        try:
            data = yaml.safe_load(builtin_yml.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            logger.warning("Built-in dictionary YAML error: %s", e)
            return {}

        if not isinstance(data, dict):
            return {}

        loaded: dict[str, MapDictionary] = {}
        for map_name, map_data in data.items():
            if not isinstance(map_data, dict):
                continue
            version = str(map_data.get("version", "1.0"))
            raw_terms: list[dict[str, Any]] = map_data.get("terms", [])
            if not isinstance(raw_terms, list):
                continue

            terms: list[CalloutTerm] = []
            for raw in raw_terms:
                if not isinstance(raw, dict):
                    continue
                en_aliases = raw.get("en", raw.get("aliases", []))
                if isinstance(en_aliases, str):
                    en_aliases = [en_aliases]
                zh = raw.get("zh", raw.get("chinese", ""))
                if not en_aliases or not zh:
                    continue
                category = str(raw.get("category", "zone"))
                ru = raw.get("ru", [])
                if isinstance(ru, str):
                    ru = [ru]

                terms.append(CalloutTerm(
                    aliases=[str(a) for a in en_aliases],
                    chinese_name=str(zh),
                    map_name=map_name,
                    category=category,
                    russian_aliases=[str(r) for r in ru],
                ))

            map_dict = MapDictionary(map_name=map_name, version=version, terms=terms)
            map_dict.build_index()
            loaded[map_name] = map_dict
            logger.info("Built-in dictionary for %s: %d terms", map_name, len(terms))

        return loaded

    def load_all(self) -> dict[str, MapDictionary]:
        """Load dictionaries — TSV files first, then built-in YAML fallback.

        Priority for each map:
          1. ``{local_path}/{map_name}.tsv`` — user-editable TSV file
          2. Built-in YAML (shipped with the wheel)
        """
        self._loaded.clear()

        # 1. Load built-in YAML (always available, fallback)
        self._loaded = self.load_builtin()

        # 2. Overlay TSV files if present (complete override per map)
        if self.local_path and self.local_path.exists():
            for tsv_file in sorted(self.local_path.glob("*.tsv")):
                map_name = tsv_file.stem  # e.g., "de_dust2" from "de_dust2.tsv"
                try:
                    tsv_dict = self._load_tsv(map_name, tsv_file)
                    # TSV completely replaces built-in for this map
                    self._loaded[map_name] = tsv_dict
                    logger.info(
                        "Loaded TSV dictionary for %s: %d terms (overrides built-in)",
                        map_name, len(tsv_dict.terms),
                    )
                except Exception as e:
                    logger.warning("Skipping TSV %s: %s", tsv_file.name, e)

        return self._loaded

    def _load_tsv(self, map_name: str, tsv_path: Path) -> MapDictionary:
        """Parse a TSV dictionary file.

        Format (tab-separated)::

            en_alias / en_alias \\t ru_alias / ru_alias \\t zh_name \\t category

        Lines starting with ``#`` are comments and skipped.
        Empty lines are skipped.
        """
        terms: list[CalloutTerm] = []
        with open(tsv_path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                parts = stripped.split("\t")
                if len(parts) < 3:
                    logger.warning(
                        "%s:%d: expected at least 3 tab-separated fields, got %d — skipping",
                        tsv_path.name, lineno, len(parts),
                    )
                    continue
                en_aliases = [a.strip() for a in parts[0].split("/") if a.strip()]
                ru_aliases = [a.strip() for a in parts[1].split("/") if a.strip()] if len(parts) > 1 and parts[1].strip() != "-" else []
                zh = parts[2].strip()
                category = parts[3].strip() if len(parts) > 3 else "zone"
                if not en_aliases or not zh:
                    logger.warning(
                        "%s:%d: empty en aliases or zh name — skipping",
                        tsv_path.name, lineno,
                    )
                    continue
                terms.append(CalloutTerm(
                    aliases=en_aliases,
                    chinese_name=zh,
                    map_name=map_name,
                    category=category,
                    russian_aliases=ru_aliases,
                ))

        md = MapDictionary(map_name=map_name, version="tsv", terms=terms)
        md.build_index()
        return md

    def _load_one(self, map_name: str, yml_path: Path) -> MapDictionary:
        """Parse a single zones.yml into a MapDictionary.

        .. deprecated:: 0.3.1
            YAML merge was replaced by TSV override in ``load_all()``.
            This method is kept only for test compatibility and will be
            removed in a future version.
        """
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
            russian = raw.get("ru", [])
            if isinstance(russian, str):
                russian = [russian]

            terms.append(
                CalloutTerm(
                    aliases=[str(a) for a in aliases],
                    chinese_name=str(chinese),
                    map_name=map_name,
                    category=str(category),
                    russian_aliases=[str(r) for r in russian],
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
            "total_russian_aliases": sum(len(t.russian_aliases) for t in md.terms),
            "by_category": categories,
        }

    # ---- LLM prompt support ----

    def build_term_table(self, map_name: str, max_terms: int = 50) -> str:
        """Build a trilingual markdown term table (EN / RU / ZH) for LLM prompt injection."""
        md = self.get_terms_for_map(map_name)
        if md is None or not md.terms:
            return f"No dictionary available for {map_name}."

        lines = [
            f"CS2 Callout Dictionary — {map_name}",
            "",
            "| English / Alias | Russian | Chinese Term | Category |",
            "|-----------------|---------|-------------|----------|",
        ]
        for term in md.terms[:max_terms]:
            aliases = ", ".join(term.aliases[:4])
            russian = ", ".join(term.russian_aliases[:3]) if term.russian_aliases else "—"
            lines.append(f"| {aliases} | {russian} | {term.chinese_name} | {term.category} |")

        if len(md.terms) > max_terms:
            lines.append(f"| ... and {len(md.terms) - max_terms} more terms | | | |")

        return "\n".join(lines)

    # ---- validation ----

    def validate_terms(self, translated_text: str, map_name: str) -> list[str]:
        """Check that CS terms in translated output use correct names.

        Scans both English and Russian aliases. Returns warnings for any
        untranslated callout terms found in the output.
        """
        warnings: list[str] = []
        md = self.get_terms_for_map(map_name)
        if md is None:
            return warnings

        for term in md.terms:
            all_aliases = term.aliases + term.russian_aliases
            for alias in all_aliases:
                if alias.lower() in translated_text.lower():
                    if len(alias) > 3:
                        lang = "RU" if alias in term.russian_aliases else "EN"
                        warnings.append(
                            f"Possible untranslated term: '{alias}' [{lang}] found in output. "
                            f"Expected: '{term.chinese_name}'"
                        )

        return warnings
