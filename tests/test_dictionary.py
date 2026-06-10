from cs2pov.services.dictionary_service import format_glossary_for_prompt


def test_mirage_glossary_contains_connector():
    glossary = format_glossary_for_prompt("de_mirage")
    assert {item["source"] for item in glossary} >= {"connector", "jungle"}
