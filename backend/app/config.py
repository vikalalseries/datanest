from functools import lru_cache
from urllib.parse import quote, unquote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    firebase_project_id: str = ""
    database_url: str = ""
    gemini_api_key: str = ""
    gemini_model: str = ""
    # Tried in order when the main model is overloaded / over quota / slow (comma separated model ids)
    gemini_fallback_models: str = "gemini-3.1-flash-lite,gemini-3.5-flash,gemini-3.6-flash,gemini-3.7-flash"
    cors_origins: str = "http://localhost:5173"
    max_upload_mb: int = 5
    # DEV ONLY: skip login and act as a fixed local user. Refused when ENV=production.
    auth_disabled: bool = False

    @property
    def gemini_fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_fallback_models.split(",") if m.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def async_database_url(self) -> str:
        url = self.database_url.strip().strip("\"'")
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                rest = url[len(prefix):]
                # Passwords often contain '@', ':' or '/' unescaped; the host is after the LAST '@'.
                if "@" in rest:
                    creds, hostpart = rest.rsplit("@", 1)
                    user, _, password = creds.partition(":")
                    creds = f"{quote(user, safe='.')}:{quote(unquote(password), safe='')}"
                    rest = f"{creds}@{hostpart}"
                return "postgresql+asyncpg://" + rest
        return url


def production_problems(s: "Settings") -> tuple[list[str], list[str]]:
    """(errors, warnings) for running with ENV=production. Errors must stop startup; warnings are logged."""
    errors: list[str] = []
    warnings: list[str] = []
    if s.auth_disabled:
        errors.append("AUTH_DISABLED must not be set in production (it turns login off for everyone).")
    if not s.firebase_project_id:
        errors.append("FIREBASE_PROJECT_ID is required in production (otherwise nobody can sign in).")
    if not s.database_url:
        errors.append("DATABASE_URL is required.")
    origins = s.cors_origin_list
    if not origins:
        errors.append("CORS_ORIGINS must list your frontend's https:// URL.")
    for o in origins:
        if o == "*" or "*" in o:
            errors.append(f"CORS_ORIGINS must not contain a wildcard ({o}).")
        elif "localhost" in o or "127.0.0.1" in o:
            errors.append(f"CORS_ORIGINS must not contain a local address in production ({o}).")
        elif not o.startswith("https://"):
            errors.append(f"CORS_ORIGINS entries must use https:// in production ({o}).")
    if not s.supabase_service_role_key:
        warnings.append("SUPABASE_SERVICE_ROLE_KEY is not set: screenshot originals can't be stored.")
    if not s.gemini_api_key or not s.gemini_model:
        warnings.append("GEMINI_API_KEY / GEMINI_MODEL not set: AI features will be unavailable.")
    return errors, warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
