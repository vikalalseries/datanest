"""Production safety: unsafe settings stop the app from starting; docs are hidden; security headers are present."""
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings, production_problems

BACKEND = Path(__file__).resolve().parents[1]
GOOD = dict(
    env="production", firebase_project_id="my-proj", database_url="postgresql://u:p@h:5432/db", cors_origins="https://app.example.com",
    supabase_service_role_key="k", gemini_api_key="g", gemini_model="m", auth_disabled=False,
)


def S(**over):
    return Settings(_env_file=None, **{**GOOD, **over})


def test_a_correct_production_config_has_no_errors():
    errors, warnings = production_problems(S())
    assert errors == [] and warnings == []


@pytest.mark.parametrize("over,fragment", [
    ({"auth_disabled": True}, "AUTH_DISABLED"),
    ({"firebase_project_id": ""}, "FIREBASE_PROJECT_ID"),
    ({"database_url": ""}, "DATABASE_URL"),
    ({"cors_origins": ""}, "CORS_ORIGINS"),
    ({"cors_origins": "*"}, "wildcard"),
    ({"cors_origins": "https://*.example.com"}, "wildcard"),
    ({"cors_origins": "http://localhost:5173"}, "local address"),
    ({"cors_origins": "https://app.example.com,http://127.0.0.1:3000"}, "local address"),
    ({"cors_origins": "http://app.example.com"}, "https://"),
])
def test_unsafe_production_settings_are_errors(over, fragment):
    errors, _ = production_problems(S(**over))
    assert any(fragment in e for e in errors), errors


def test_missing_optional_keys_only_warn():
    errors, warnings = production_problems(S(supabase_service_role_key="", gemini_api_key=""))
    assert errors == [] and len(warnings) == 2


def run_app(env: dict, code: str):
    full = {k: v for k, v in os.environ.items() if not k.startswith(("AUTH_DISABLED", "ENV", "FIREBASE", "CORS", "DATABASE", "SUPABASE", "GEMINI"))}
    full.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=full, capture_output=True, text=True, timeout=60)


BASE_ENV = {"ENV": "production", "AUTH_DISABLED": "false", "FIREBASE_PROJECT_ID": "my-proj", "DATABASE_URL": "postgresql://u:p@h:5432/db", "CORS_ORIGINS": "https://app.example.com"}


def test_the_app_refuses_to_start_in_production_with_auth_disabled():
    r = run_app({**BASE_ENV, "AUTH_DISABLED": "true"}, "import app.main")
    assert r.returncode != 0 and "Refusing to start with unsafe production settings" in r.stderr and "AUTH_DISABLED" in r.stderr


def test_the_app_refuses_to_start_with_a_wildcard_cors_origin():
    r = run_app({**BASE_ENV, "CORS_ORIGINS": "*"}, "import app.main")
    assert r.returncode != 0 and "wildcard" in r.stderr


def test_a_correct_production_app_starts_and_hides_its_api_docs():
    code = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        print("STATUS", c.get("/docs").status_code, c.get("/openapi.json").status_code, c.get("/health").status_code)
        h = c.get("/health").headers
        print("HSTS", h.get("strict-transport-security"))
        print("ME", c.get("/api/auth/me").status_code)
    """)
    r = run_app(BASE_ENV, code)
    assert r.returncode == 0, r.stderr
    assert "STATUS 404 404 200" in r.stdout and "HSTS max-age=31536000" in r.stdout and "ME 401" in r.stdout


def test_the_dev_bypass_still_works_outside_production():
    r = run_app({"ENV": "development", "AUTH_DISABLED": "true"}, "import app.main; print('started')")
    assert r.returncode == 0 and "started" in r.stdout


# ---------------- headers ----------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    get_settings.cache_clear()
    from app.main import app

    yield TestClient(app, raise_server_exceptions=False)
    get_settings.cache_clear()


def test_security_headers_on_every_response(client):
    for path in ("/health", "/api/auth/me"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
        assert h["x-request-id"]
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"  # API responses (personal data) are never cached
    assert "strict-transport-security" not in client.get("/health").headers  # only in production


def test_cors_allows_the_configured_origin_only(client):
    ok = client.options("/api/auth/me", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/auth/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_clock_skew_tolerance_accepts_small_skew_but_not_large(monkeypatch):
    """Firebase tokens are rejected for 'issued in the future' if the server clock lags a few seconds."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.middleware import authentication

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "p")
    get_settings.cache_clear()
    monkeypatch.setattr(authentication, "_jwk_client", lambda: SimpleNamespaceClient(key.public_key()))

    def token(iat_offset):
        now = int(time.time())
        return jwt.encode({"sub": "u", "aud": "p", "iss": "https://securetoken.google.com/p", "iat": now + iat_offset, "exp": now + 600}, key, algorithm="RS256")

    assert authentication.verify_token(token(5), get_settings())["sub"] == "u"  # 5 s ahead: fine
    with pytest.raises(Exception) as e:
        authentication.verify_token(token(120), get_settings())  # 2 minutes ahead: rejected
    assert getattr(e.value, "status_code", None) == 401
    get_settings.cache_clear()


class SimpleNamespaceClient:
    def __init__(self, pub):
        self._pub = pub

    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": self._pub})()
