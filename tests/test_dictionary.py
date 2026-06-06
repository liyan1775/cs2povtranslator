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
        loaded = mgr.load_all()
        assert "de_dust2" in loaded
        md = loaded["de_dust2"]
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
        cov = mgr.show_coverage("de_dust2")
        assert cov["total_terms"] == 5
        assert cov["map"] == "de_dust2"

    def test_show_coverage_missing_map(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        result = mgr.show_coverage("de_nuke")
        assert "error" in result

    def test_empty_repo_path(self, tmp_dir):
        mgr = DictionaryManager(repo_url="unused", local_path=tmp_dir / "nonexistent")
        loaded = mgr.load_all()
        assert loaded == {}


class TestTermTable:
    def test_build_term_table(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        table = mgr.build_term_table("de_dust2")
        assert "de_dust2" in table
        assert "A小道" in table
        assert "|" in table  # markdown table structure

    def test_build_term_table_missing_map(self, sample_dust2_zones_yml):
        repo_path = sample_dust2_zones_yml.parent.parent
        mgr = DictionaryManager(repo_url="unused", local_path=repo_path)
        table = mgr.build_term_table("de_nuke")
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
