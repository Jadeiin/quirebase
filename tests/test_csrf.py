from __future__ import annotations

from quirebase.web.api.auth import _normalized_origin


def test_origin_normalization_is_strict_and_default_port_aware():
    assert _normalized_origin("https://example.test") == ("https", "example.test", 443)
    assert _normalized_origin("http://EXAMPLE.test:80/") == ("http", "example.test", 80)
    assert _normalized_origin("https://example.test/path") is None
    assert _normalized_origin("https://user@example.test") is None
    assert _normalized_origin("null") is None
