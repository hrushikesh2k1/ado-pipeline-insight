from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
load_dotenv(os.path.join(PROJECT_ROOT, "backend", ".env"))


@dataclass(frozen=True)
class Settings:
    sql_connection_string: str
    ado_pat_secret_name: str
    sql_connection_secret_name: str
    ado_pat_secret_template: str | None
    key_vault_url: str | None
    azure_openai_endpoint: str
    azure_openai_deployment: str
    azure_openai_api_version: str
    min_history_runs: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    sql_connection_string = os.environ.get("SQL_CONNECTION_STRING", "")
    sql_connection_secret_name = os.environ.get("SQL_CONNECTION_SECRET_NAME", "sql-connection-string")
    key_vault_url = os.environ.get("KEY_VAULT_URL")
    if key_vault_url and sql_connection_string.startswith("@Microsoft.KeyVault("):
        sql_connection_string = SecretClient(
            vault_url=key_vault_url,
            credential=DefaultAzureCredential(),
        ).get_secret(sql_connection_secret_name).value

    return Settings(
        sql_connection_string=sql_connection_string,
        sql_connection_secret_name=sql_connection_secret_name,
        ado_pat_secret_name=os.environ.get("ADO_PAT_SECRET_NAME", "ado-pat"),
        ado_pat_secret_template=os.environ.get("ADO_PAT_SECRET_TEMPLATE") or None,
        key_vault_url=os.environ.get("KEY_VAULT_URL"),
        azure_openai_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        azure_openai_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        azure_openai_api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        min_history_runs=int(os.environ.get("MIN_HISTORY_RUNS", "5")),
    )


@lru_cache(maxsize=1)
def get_ado_pat(organization: str | None = None) -> str:
    settings = get_settings()
    if not settings.key_vault_url:
        return os.environ["ADO_PAT"]
    secret_name = settings.ado_pat_secret_name
    if organization and settings.ado_pat_secret_template:
        normalized_organization = re.sub(
            r"-+", "-", re.sub(r"[^a-z0-9-]+", "-", organization.strip().lower())
        ).strip("-")
        secret_name = settings.ado_pat_secret_template.format(
            organization=normalized_organization
        )
    client = SecretClient(vault_url=settings.key_vault_url, credential=DefaultAzureCredential())
    return client.get_secret(secret_name).value
