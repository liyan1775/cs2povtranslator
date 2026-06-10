from cs2pov.cli.encoding import configure_utf8_stdio


def test_configure_utf8_stdio_is_safe_to_call_twice():
    configure_utf8_stdio()
    configure_utf8_stdio()
