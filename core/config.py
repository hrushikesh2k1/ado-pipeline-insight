from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient


@dataclass(frozen=True)
class Settings:
    sql_connection_string: str
    ado_pat_secret_name: str
    key_vault_url: str | None
    azure_openai_endpoint: str
    azure_openai_deployment: str
    azure_openai_api_version: str
    min_history_runs: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        sql_connection_string=os.environ["SQL_CONNECTION_STRING"],
        ado_pat_secret_name=os.environ.get("ADO_PAT_SECRET_NAME", "ado-pat"),
        key_vault_url=os.environ.get("KEY_VAULT_URL"),
        azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        azure_openai_api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        min_history_runs=int(os.environ.get("MIN_HISTORY_RUNS", "5")),
    )


@lru_cache(maxsize=1)
def get_ado_pat() -> str:
    settings = get_settings()
    if not settings.key_vault_url:
        return os.environ["ADO_PAT"]
    client = SecretClient(vault_url=settings.key_vault_url, credential=DefaultAzureCredential())
    return client.get_secret(settings.ado_pat_secret_name).value
