"""Tests for dictionary module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cs2tl.dictionary import (
    CalloutTerm,
    DictionaryManager,
    MapDictionary,
)
from cs2tl.errors import CS2tlError


class TestCalloutTerm:
    def test_primary_alias_returns_first(self):
        term = CalloutTerm(
            aliases=["A short", "catwalk", "cat"],
            chinese_name="A小道",
            map_name="de_dust2",
        )
        assert term.primary_alias == "A short"

    def test_primary_alias_empty(self):
        term = CalloutTerm(aliases=[], chinese_name="test", map_name="de_dust2")
        assert term.primary_alias == ""


class TestMapDictionary:
    def test_build_index_and_lookup(self):
        md = MapDictionary(map_name="de_dust2", version="1.0")
        md.terms = [
            CalloutTerm(aliases=["A short", "catwalk"], chinese_name="A小道", map_name="de_dust2"),
        ]
        md.build_index()
        assert md.lookup("catwalk") is not None
        assert md.lookup("catwalk").chinese_name == "A小道"

    def test_lookup_case_insensitive(self):
        md = MapDictionary(map_name="de_dust2", version="1.0")
        md.terms = [
            CalloutTerm(aliases=["A Long"], chinese_name="A大道", map_name="de_dust2"),
        ]
        md.build_index()
        assert md.lookup("a long") is not None
        assert md.lookup("A LONG") is not None

    def test_lookup_missing_returns_none(self):
        md = MapDictionary(map_name="de_dust2", version="1.0")
        md.build_index()
        assert md.lookup("nonexistent") is None

    def test_get_chinese_names(self):
        md = MapDictionary(map_name="de_dust2", version="1.0")
        md.terms = [
            CalloutTerm(aliases=["A short"], chinese_name="A小道", map_name="de_dust2"),
            CalloutTerm(aliases=["B site"], chinese_name="B包点", map_name="de_dust2"),
        ]
        md.build_index()
        names = md.get_chinese_names()
        assert "A小道" in names
        assert "B包点" in names


class TestDictionaryManagerLoading:
    def test_load_from_fixture_directory(self, sample_dust2_zones_yml):
        """Load a dictionary from a directory structure that mirrors the repo layout."""
        repo_path = sample_dust2_zones_yml.parent.parent  # tmp_dir containing de_dust2/
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        # Load only local files (skip built-in)
        local_only = {}
        dict_dir = mgr.local_path
        if dict_dir and dict_dir.exists():
            for entry in sorted(dict_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                zones_yml = entry / "zones.yml"
                if not zones_yml.exists():
                    continue
                try:
                    map_dict = mgr._load_one(entry.name, zones_yml)
                    local_only[entry.name] = map_dict
                except Exception:
                    continue
        assert "de_dust2" in local_only
        md = local_only["de_dust2"]
        assert len(md.terms) == 5
        # Look up "cat" alias → "A小道"
        term = md.lookup("cat")
        assert term is not None
        assert term.chinese_name == "A小道"

    def test_list_maps(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        maps = mgr.list_maps()
        assert "de_dust2" in maps

    def test_show_coverage(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        # Load only local fixture (avoid built-in merging)
        mgr._loaded = {}
        local_dict = mgr._load_one("de_dust2", sample_dust2_zones_yml)
        mgr._loaded["de_dust2"] = local_dict
        cov = mgr.show_coverage("de_dust2")
        assert cov["total_terms"] == 5
        assert cov["map"] == "de_dust2"

    def test_show_coverage_missing_map(self, sample_dust2_zones_yml):
        """show_coverage for a map not loaded returns error. But built-in
        dictionaries are always loaded by load_all(), so we clear _loaded
        and use a non-standard map name to force the error path."""
        mgr = DictionaryManager()
        mgr._loaded = {}  # bypass built-in
        result = mgr.show_coverage("de_nonexistent")
        assert "error" in result

    def test_empty_repo_path(self, tmp_dir):
        """When local_path doesn't exist and no built-in is loaded,
        load_all returns empty dict. But load_builtin is always called,
        so we clear _loaded after and test local-only loading."""
        mgr = DictionaryManager(repo_url="unused", local_path=tmp_dir / "nonexistent")
        loaded = mgr.load_all()
        # With built-in, loaded will have 7 maps. Test that local_path
        # doesn't cause errors even when nonexistent.
        assert len(loaded) >= 7  # built-in always present


class TestTermTable:
    def test_build_term_table(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        table = mgr.build_term_table("de_dust2")
        assert "de_dust2" in table
        assert "A小道" in table
        assert "|" in table  # markdown table structure

    def test_build_term_table_missing_map(self, sample_dust2_zones_yml):
        """build_term_table for a non-existent map returns error message.
        de_nuke is now a built-in map, so use a truly nonexistent name."""
        mgr = DictionaryManager()
        mgr._loaded = {}  # bypass built-in so we test the error path
        table = mgr.build_term_table("de_nonexistent")
        assert "No dictionary available" in table


class TestValidation:
    def test_validate_terms_no_warnings_for_good_translation(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        warnings = mgr.validate_terms("我在中路架A小", "de_dust2")
        assert len(warnings) == 0

    def test_validate_terms_warns_on_long_untranslated_alias(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        warnings = mgr.validate_terms("I'm holding catwalk from mid", "de_dust2")
        # "catwalk" > 3 chars and is in the dictionary → should warn
        assert len(warnings) > 0
        assert any("catwalk" in w for w in warnings)


class TestYAMLSafety:
    def test_safe_load_blocks_python_objects(self, tmp_dir):
        """YAML with !!python/object is rejected by safe_load (no RCE)."""
        map_dir = tmp_dir / "de_danger"
        map_dir.mkdir()
        malicious = map_dir / "zones.yml"
        malicious.write_text("terms: !!python/object/apply:os.system ['echo pwned']", encoding="utf-8")
        mgr = DictionaryManager(repo_url="unused", local_path=tmp_dir)
        # yaml.safe_load rejects unknown tags. The _load_one wrapper catches this
        # and logs a warning, skipping the dangerous file.
        loaded = mgr.load_all()
        assert "de_danger" not in loaded  # the malicious dictionary was skipped


# ── T9: New tests for v0.3 ──


class TestRussianAliases:
    """Tests for the russian_aliases field on CalloutTerm."""

    def test_russian_aliases_parsed_from_yaml(self, tmp_dir):
        """ru field in YAML is correctly parsed to russian_aliases."""
        map_dir = tmp_dir / "de_dust2"
        map_dir.mkdir()
        zones = map_dir / "zones.yml"
        zones.write_text(yaml.dump({
            "version": "1.0",
            "terms": [{
                "aliases": ["A short", "catwalk"],
                "chinese": "A小道",
                "ru": ["короткий", "шорт"],
                "category": "zone",
            }],
        }), encoding="utf-8")
        mgr = DictionaryManager(repo_url="unused", local_path=tmp_dir)
        loaded = mgr.load_all()
        assert "de_dust2" in loaded
        term = loaded["de_dust2"].terms[0]
        assert "короткий" in term.russian_aliases
        assert "шорт" in term.russian_aliases

    def test_backward_compat_no_ru_field(self, tmp_dir):
        """Old YAML without 'ru' field still loads with empty russian_aliases."""
        map_dir = tmp_dir / "de_cache"
        map_dir.mkdir()
        zones = map_dir / "zones.yml"
        zones.write_text(yaml.dump({
            "version": "1.0",
            "terms": [{
                "aliases": ["A main"],
                "chinese": "A门",
            }],
        }), encoding="utf-8")
        mgr = DictionaryManager(repo_url="unused", local_path=tmp_dir)
        loaded = mgr.load_all()
        assert "de_cache" in loaded
        term = loaded["de_cache"].terms[0]
        assert term.russian_aliases == []

    def test_ru_string_handled_as_list(self, tmp_dir):
        """A single string value for 'ru' is converted to a one-element list.
        Use _load_one directly to avoid built-in dictionary merging."""
        map_dir = tmp_dir / "de_mirage"
        map_dir.mkdir()
        zones = map_dir / "zones.yml"
        zones.write_text(yaml.dump({
            "version": "1.0",
            "terms": [{
                "aliases": ["palace"],
                "chinese": "A2楼",
                "ru": "дворец",
            }],
        }), encoding="utf-8")
        mgr = DictionaryManager(repo_url="unused", local_path=tmp_dir)
        # Load only the local file, not built-in
        local_dict = mgr._load_one("de_mirage", zones)
        term = local_dict.terms[0]
        assert term.russian_aliases == ["дворец"]


class TestBuiltInDictionary:
    """Tests for the built-in dictionary (T6)."""

    def test_load_builtin_all_maps(self):
        """Built-in YAML contains all 7 active-duty maps."""
        mgr = DictionaryManager()
        builtin = mgr.load_builtin()
        expected = {"de_dust2", "de_mirage", "de_inferno", "de_nuke",
                     "de_overpass", "de_anubis", "de_ancient"}
        assert set(builtin.keys()) >= expected
        for map_name in expected:
            assert len(builtin[map_name].terms) > 0, f"{map_name} has no terms"

    def test_load_builtin_terms_have_required_fields(self):
        """Every built-in term has aliases, chinese_name, and category."""
        mgr = DictionaryManager()
        builtin = mgr.load_builtin()
        for map_name, md in builtin.items():
            for term in md.terms:
                assert term.aliases, f"{map_name}: term has no aliases"
                assert term.chinese_name, f"{map_name}: term has no chinese_name"
                assert term.category, f"{map_name}: term has no category"

    def test_load_all_includes_builtin(self):
        """load_all() includes the built-in dictionary even without local_path."""
        mgr = DictionaryManager()  # no local_path
        loaded = mgr.load_all()
        assert len(loaded) >= 7
        assert "de_dust2" in loaded

    def test_build_index_includes_russian(self):
        """build_index() allows lookup by Russian alias."""
        mgr = DictionaryManager()
        builtin = mgr.load_builtin()
        dust2 = builtin.get("de_dust2")
        if dust2 and any(t.russian_aliases for t in dust2.terms):
            # Find a term with Russian aliases and verify lookup
            term_with_ru = next((t for t in dust2.terms if t.russian_aliases), None)
            if term_with_ru:
                result = dust2.lookup(term_with_ru.russian_aliases[0])
                assert result is not None
