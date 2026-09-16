from __future__ import annotations

from pathlib import Path

from quirebase.models import LoginSession
from quirebase.web.api.auth import _normalized_origin

ROOT = Path(__file__).parents[1]


def test_origin_normalization_is_strict_and_default_port_aware():
    assert _normalized_origin("https://example.test") == ("https", "example.test", 443)
    assert _normalized_origin("http://EXAMPLE.test:80/") == ("http", "example.test", 80)
    assert _normalized_origin("https://example.test/path") is None
    assert _normalized_origin("https://user@example.test") is None
    assert _normalized_origin("null") is None


def test_synchronizer_token_state_and_frontend_headers_are_removed():
    assert "csrf_token" not in LoginSession.__table__.columns
    client = (ROOT / "frontend/src/lib/api/client.ts").read_text(encoding="utf-8")
    assert "X-CSRF-Token" not in client
    assert "localStorage" not in client


def test_origin_policy_is_centralized_in_unified_api_authentication():
    source = (ROOT / "src/quirebase/web/api/auth.py").read_text(encoding="utf-8")
    assert "require_same_origin(request)" in source
    assert 'request.method in {"POST", "PUT", "PATCH", "DELETE"}' in source
    assert not (ROOT / "src/quirebase/web/deps.py").exists()
