from types import SimpleNamespace

import pytest

import app.core.db as app_db
import app.services.ai_service as ai_module
import core.config as core_config
from app.core.errors import ServiceConfigError
from app.services.ai_service import AIService, _telemetry_fallback
from core.models import Finding, RecommendationResponse
from core.validation import validate_organization, validate_pat, validate_project

SUMMARY = {
    "stages": [
        {"name": "Build", "avg_duration_s": 600, "tasks": [
            {"name": "npm install", "avg_duration_s": 400, "pct_of_parent_duration": 66.7, "failure_rate_pct": 20, "retry_rate_pct": 0,
             "error_excerpt": "ETIMEDOUT"},
            {"name": "compile", "avg_duration_s": 100, "pct_of_parent_duration": 16.7, "failure_rate_pct": 0, "retry_rate_pct": 25},
        ]},
        {"name": "Deploy", "avg_duration_s": 60, "tasks": []},
    ]
}


def test_telemetry_fallback_reports_flaky_and_slow_steps():
    findings = _telemetry_fallback(SUMMARY)
    categories = {f["category"] for f in findings}
    assert "flaky_step" in categories and findings[0]["severity"] == "high"
    assert "ETIMEDOUT" in findings[0]["evidence"]
    assert _telemetry_fallback({"stages": []}) == []


def test_telemetry_fallback_flags_caching_for_install_steps():
    quiet = {"stages": [{"name": "Build", "avg_duration_s": 300, "tasks": [
        {"name": "npm install", "avg_duration_s": 250, "pct_of_parent_duration": 83, "failure_rate_pct": 0, "retry_rate_pct": 0}]}]}
    assert _telemetry_fallback(quiet)[0]["category"] == "caching_opportunity"


def _settings(**overrides):
    base = dict(sql_connection_string="conn", min_history_runs=5, azure_openai_endpoint="https://x", azure_openai_deployment="d",
                azure_openai_api_version="v", azure_openai_api_key="")
    return SimpleNamespace(**{**base, **overrides})


def test_analyze_requires_configuration(monkeypatch):
    monkeypatch.setattr(ai_module, "get_settings", lambda: _settings(sql_connection_string=""))
    with pytest.raises(ServiceConfigError):
        AIService().analyze(1, 30)
    monkeypatch.setattr(ai_module, "get_settings", lambda: _settings(azure_openai_endpoint=""))
    monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: SimpleNamespace(count_runs=lambda pid, days: 10))
    with pytest.raises(ServiceConfigError):
        AIService().analyze(1, 30)


def test_analyze_skips_when_history_is_short(monkeypatch):
    monkeypatch.setattr(ai_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: SimpleNamespace(count_runs=lambda pid, days: 2))
    result = AIService().analyze(1, 30)
    assert result["findings"] == [] and "Not enough" in result["message"]


def test_analyze_uses_model_findings_then_falls_back(monkeypatch):
    saved = []
    repo = SimpleNamespace(count_runs=lambda pid, days: 10, get_pipeline_metrics=lambda pid, days: [],
                           upsert_recommendations=lambda pid, findings: saved.append(findings))
    monkeypatch.setattr(ai_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: repo)
    monkeypatch.setattr(ai_module, "build_analysis_summary", lambda rows, window_days: SUMMARY)
    finding = Finding("bottleneck", "low", "Build", None, "r", "e")
    holder = {"findings": [finding]}

    class Client:
        def __init__(self, *args):
            pass

        def recommend(self, summary):
            return RecommendationResponse(findings=holder["findings"])

    monkeypatch.setattr(ai_module, "PipelineRecommendationClient", Client)
    kept = AIService().analyze(1, 30)["findings"]
    assert "bottleneck" in {f["category"] for f in kept}  # the model's own finding is kept...
    assert kept[0]["category"] == "flaky_step" and kept[0]["task_name"] == "npm install"  # ...and the 20%-failing step it skipped is added, first
    holder["findings"] = []
    assert AIService().analyze(1, 30)["findings"][0]["category"] == "flaky_step"
    assert len(saved) == 2


def test_connection_string_normalisation_and_driver_variants():
    raw = "Driver={ODBC Driver 18 for SQL Server};Server=s;User ID=u;Password=p;Initial Catalog=d;Encrypt=True;TrustServerCertificate=False"
    normalized = app_db.normalize_connection_string(raw)
    assert "UID=u" in normalized and "PWD=p" in normalized and "Database=d" in normalized and "Encrypt=yes" in normalized
    variants = app_db.connection_variants(raw)
    assert variants[0] == normalized and any("Driver 17" in v for v in variants)


class FakeCursor:
    description = [("id",), ("name",)]

    def execute(self, query, *params):
        self.seen = (query, params)

    def fetchall(self):
        return [(1, "a"), (2, "b")]


class FakeConn:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def close(self):
        self.closed = True


def test_get_connection_retries_with_other_driver_and_closes(monkeypatch):
    attempts = []

    def connect(value):
        attempts.append(value)
        if len(attempts) == 1:
            raise RuntimeError("driver missing")
        return FakeConn()

    monkeypatch.setattr(app_db, "get_settings", lambda: SimpleNamespace(sql_connection_string="Driver={ODBC Driver 18 for SQL Server};Server=s"))
    monkeypatch.setattr(app_db.pyodbc, "connect", connect)
    with app_db.get_connection() as conn:
        assert isinstance(conn, FakeConn)
    assert conn.closed and len(attempts) == 2


def test_get_connection_errors(monkeypatch):
    monkeypatch.setattr(app_db, "get_settings", lambda: SimpleNamespace(sql_connection_string=""))
    with pytest.raises(RuntimeError, match="not configured"), app_db.get_connection():
        pass
    monkeypatch.setattr(app_db, "get_settings", lambda: SimpleNamespace(sql_connection_string="Server=s"))

    def refuse(_value):
        raise RuntimeError("refused")

    monkeypatch.setattr(app_db.pyodbc, "connect", refuse)
    with pytest.raises(RuntimeError, match="Unable to connect"), app_db.get_connection():
        pass


def test_fetch_helpers_map_rows_to_dicts(monkeypatch):
    monkeypatch.setattr(app_db, "get_settings", lambda: SimpleNamespace(sql_connection_string="Server=s"))
    monkeypatch.setattr(app_db.pyodbc, "connect", lambda value: FakeConn())
    assert app_db.fetch_all("SELECT 1", (1,)) == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert app_db.fetch_one("SELECT 1") == {"id": 1, "name": "a"}


@pytest.fixture
def clean_config(monkeypatch):
    for name in ("SQL_CONNECTION_STRING", "KEY_VAULT_URL", "ADO_PAT", "ADO_PAT_SECRET_TEMPLATE", "ADO_PAT_SECRET_NAME"):
        monkeypatch.delenv(name, raising=False)
    core_config.get_settings.cache_clear()
    core_config.get_ado_pat.cache_clear()
    yield monkeypatch
    core_config.get_settings.cache_clear()
    core_config.get_ado_pat.cache_clear()


def test_pat_comes_from_environment_without_key_vault(clean_config):
    clean_config.setenv("ADO_PAT", "env-pat")
    assert core_config.get_ado_pat("org") == "env-pat"


def test_pat_and_sql_secret_come_from_key_vault(clean_config):
    requested = []

    class Client:
        def __init__(self, vault_url, credential):
            pass

        def get_secret(self, name):
            requested.append(name)
            return SimpleNamespace(value=f"value-of-{name}")

    clean_config.setattr(core_config, "SecretClient", Client)
    clean_config.setattr(core_config, "DefaultAzureCredential", lambda: None)
    clean_config.setenv("KEY_VAULT_URL", "https://vault.example")
    clean_config.setenv("SQL_CONNECTION_STRING", "@Microsoft.KeyVault(SecretUri=https://vault.example/secrets/sql)")
    clean_config.setenv("ADO_PAT_SECRET_TEMPLATE", "ado-pat-{organization}")
    assert core_config.get_settings().sql_connection_string == "value-of-sql-connection-string"
    assert core_config.get_ado_pat("My Org!") == "value-of-ado-pat-my-org"
    assert requested == ["sql-connection-string", "ado-pat-my-org"]


def test_validators_accept_real_names_and_reject_hostile_ones():
    assert validate_organization(" my-org1 ") == "my-org1"
    assert validate_project("Payments Platform (v2)") == "Payments Platform (v2)"
    assert validate_pat("a" * 52) == "a" * 52
    for bad in ("../x", "a/b", "a b", "-x", "x" * 65, ""):
        with pytest.raises(ValueError):
            validate_organization(bad)
    for bad in ("a/b", "a..b", "a?b", "a#b", "x" * 257, "", "line\nbreak", "ends."):
        with pytest.raises(ValueError):
            validate_project(bad)
    for bad in ("", "with space", "tab\t", "x" * 513):
        with pytest.raises(ValueError):
            validate_pat(bad)
