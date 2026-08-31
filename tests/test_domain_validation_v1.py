def test_validation_module_imports():
    from cs2pov.domain.validation import validate_draft_timeline_graph
    assert callable(validate_draft_timeline_graph)
