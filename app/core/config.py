from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    sql_connection_string: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    min_history_runs: int = 5
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_api_key: str = ""
    ingest_function_url: str = ""
    require_easy_auth: bool = False
    enable_api_docs: bool = False
    allowed_ado_orgs: str = ""
    max_request_bytes: int = 65536
    # File uploads travel as base64 inside JSON: a 5 MB file is about 6.7 MB. Only the upload routes get this larger limit.
    max_upload_request_bytes: int = 7_200_000
    # Username/password sign-in. Credentials live in Key Vault; auth_username/auth_password are a local-dev fallback
    # used only when key_vault_url is empty. Set REQUIRE_LOGIN=false to run without sign-in (local development).
    require_login: bool = True
    key_vault_url: str = ""
    auth_username_secret_name: str = "app-auth-username"
    auth_password_secret_name: str = "app-auth-password"
    auth_session_secret_name: str = "app-auth-session-secret"
    auth_username: str = ""  # empty means closed: with no Key Vault and no AUTH_USERNAME/AUTH_PASSWORD nobody can sign in
    auth_password: str = ""
    auth_session_secret: str = ""
    session_hours: int = 8
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env",),
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [v.strip() for v in self.cors_origins.split(",") if v.strip() and v.strip() != "*"]

    @property
    def allowed_ado_org_list(self) -> list[str]:
        return [v.strip().lower() for v in self.allowed_ado_orgs.split(",") if v.strip()]

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
