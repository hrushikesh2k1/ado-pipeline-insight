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
