import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.middleware import authentication

PROJECT = "datanest-test"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeSigningKey:
    key = KEY.public_key()


class FakeJwkClient:
    def get_signing_key_from_jwt(self, token):
        return FakeSigningKey()


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setenv("AUTH_DISABLED", "false")  # tests must exercise real auth even if .env enables the dev bypass
    get_settings.cache_clear()
    monkeypatch.setattr(authentication, "_jwk_client", lambda: FakeJwkClient())
    yield
    get_settings.cache_clear()


def make_token(key=KEY, alg="RS256", **over):
    now = int(time.time())
    claims = {
        "sub": "firebase-uid-123",
        "aud": PROJECT,
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "iat": now - 5,
        "exp": now + 600,
        "email": "a@example.com",
    }
    claims.update(over)
    return jwt.encode(claims, key, algorithm=alg)


client = TestClient(app, raise_server_exceptions=False)


def get_me(token):
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_health_is_public():
    assert client.get("/health").json() == {"status": "ok"}


def test_me_requires_token():
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_rejects_garbage_token():
    assert get_me("nope").status_code == 401


def test_rejects_expired_token():
    r = get_me(make_token(exp=int(time.time()) - 10))
    assert r.status_code == 401
    assert "expired" in r.json()["error"]["message"].lower()


def test_rejects_wrong_signature():
    assert get_me(make_token(key=OTHER_KEY)).status_code == 401


def test_rejects_wrong_audience_and_issuer():
    assert get_me(make_token(aud="another-project")).status_code == 401
    assert get_me(make_token(iss="https://securetoken.google.com/evil")).status_code == 401


def test_rejects_alg_none_and_hs256():
    now = int(time.time())
    base = {"sub": "x", "aud": PROJECT, "iss": f"https://securetoken.google.com/{PROJECT}", "iat": now, "exp": now + 60}
    assert get_me(jwt.encode(base, None, algorithm="none")).status_code == 401
    assert get_me(jwt.encode(base, "a-long-enough-shared-secret-value-123456", algorithm="HS256")).status_code == 401


def test_rejects_missing_sub():
    now = int(time.time())
    token = jwt.encode({"aud": PROJECT, "iss": f"https://securetoken.google.com/{PROJECT}", "iat": now, "exp": now + 60}, KEY, algorithm="RS256")
    assert get_me(token).status_code == 401


def test_valid_token_yields_user():
    claims = authentication.verify_token(make_token(name="Ada", picture="http://p"), get_settings())
    assert claims["sub"] == "firebase-uid-123"
    assert claims["name"] == "Ada"


def test_unconfigured_project_is_server_error_not_open_access(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "")
    get_settings.cache_clear()
    assert get_me(make_token()).status_code == 500


def test_dev_bypass_works_in_development_but_is_refused_in_production(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("ENV", "development")
    get_settings.cache_clear()
    from app.middleware.authentication import get_current_user
    import asyncio

    user = asyncio.run(get_current_user(None, get_settings()))
    assert user.uid == "dev-user"
    monkeypatch.setenv("ENV", "production")
    get_settings.cache_clear()
    with pytest.raises(Exception) as e:
        asyncio.run(get_current_user(None, get_settings()))
    assert getattr(e.value, "status_code", None) == 500


def test_error_responses_keep_structured_hints():
    """Extra detail fields (e.g. `missing` columns) must reach the client alongside code/message."""
    from fastapi import HTTPException

    from app.main import app as _app

    @_app.get("/_t/extra", include_in_schema=False)
    async def _extra():
        raise HTTPException(status_code=409, detail={"code": "columns_missing", "message": "m", "missing": ["A", "B"]})

    r = client.get("/_t/extra")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "columns_missing" and err["missing"] == ["A", "B"] and err["request_id"]
