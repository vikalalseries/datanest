"""Supabase Storage (private bucket) for uploaded originals. Uses the service-role key, server-side only."""
import logging
import uuid

import httpx

from app.config import get_settings

log = logging.getLogger("datanest.storage")
BUCKET = "uploads"
_bucket_ready = False


def _headers() -> dict:
    key = get_settings().supabase_service_role_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def configured() -> bool:
    s = get_settings()
    return bool(s.supabase_url and s.supabase_service_role_key)


async def _ensure_bucket(client: httpx.AsyncClient, base: str) -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    r = await client.post(f"{base}/storage/v1/bucket", headers=_headers(), json={"id": BUCKET, "name": BUCKET, "public": False})
    if r.status_code in (200, 201) or "already exists" in r.text.lower() or r.status_code == 409:
        _bucket_ready = True
    else:
        raise RuntimeError(f"bucket create failed ({r.status_code})")


async def upload(user_id: str, data: bytes, mime: str, ext: str) -> str | None:
    """Store bytes under {user_id}/{uuid}.{ext}. Returns the object path, or None if storage is unavailable."""
    if not configured():
        return None
    base = get_settings().supabase_url.rstrip("/")
    path = f"{user_id}/{uuid.uuid4().hex}.{ext}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            await _ensure_bucket(client, base)
            r = await client.post(f"{base}/storage/v1/object/{BUCKET}/{path}", headers={**_headers(), "Content-Type": mime}, content=data)
            if r.status_code not in (200, 201):
                raise RuntimeError(f"upload failed ({r.status_code})")
        return path
    except Exception as e:  # storage problems must never block extraction
        log.warning("storage upload failed: %s", type(e).__name__)
        return None


async def signed_url(path: str, expires_in: int = 300) -> str | None:
    """Short-lived download link for a private object, or None if storage is unavailable."""
    if not configured():
        return None
    base = get_settings().supabase_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{base}/storage/v1/object/sign/{BUCKET}/{path}", headers=_headers(), json={"expiresIn": expires_in})
            if r.status_code != 200:
                raise RuntimeError(f"sign failed ({r.status_code})")
            rel = r.json().get("signedURL") or r.json().get("signedUrl")
            if not rel:
                raise RuntimeError("no url")
            return rel if rel.startswith("http") else f"{base}/storage/v1{rel}"
    except Exception as e:
        log.warning("storage sign failed: %s", type(e).__name__)
        return None
