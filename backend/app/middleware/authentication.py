"""Firebase ID-token verification. Identity always comes from the verified token, never the request body."""
from dataclasses import dataclass, field
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)

FIREBASE_JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"


@dataclass(frozen=True)
class AuthUser:
    uid: str  # Firebase uid (the `sub` claim)
    email: str
    name: str | None = None
    picture: str | None = None
    claims: dict = field(default_factory=dict)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache
def _jwk_client() -> PyJWKClient:
    return PyJWKClient(FIREBASE_JWKS_URL, cache_keys=True, lifespan=3600)


def verify_token(token: str, settings: Settings) -> dict:
    if not settings.firebase_project_id:
        raise HTTPException(
            status_code=500, detail={"code": "server_misconfigured", "message": "Authentication is not configured."}
        )
    try:
        key = _jwk_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],  # Firebase signs with RS256 only; rejects "none"/HS256 confusion
            audience=settings.firebase_project_id,
            issuer=f"https://securetoken.google.com/{settings.firebase_project_id}",
            leeway=10,  # tolerate small clock differences between Google and this server
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Your session has expired. Please sign in again.")
    except Exception:
        raise _unauthorized("Invalid session.")
    if not claims.get("sub") or len(claims["sub"]) > 128:
        raise _unauthorized("Invalid session.")
    return claims


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    if settings.auth_disabled:
        if settings.env == "production":
            raise HTTPException(status_code=500, detail={"code": "server_misconfigured", "message": "Authentication cannot be disabled in production."})
        return AuthUser(uid="dev-user", email="dev@localhost.test", name="Dev User", claims={})
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized("Authentication required.")
    claims = verify_token(creds.credentials, settings)
    return AuthUser(
        uid=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name"),
        picture=claims.get("picture"),
        claims=claims,
    )
