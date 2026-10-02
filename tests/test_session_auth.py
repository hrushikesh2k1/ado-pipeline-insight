"""Username/password sign-in: Key Vault-backed credentials, signed cookies, route gate and brute-force throttle."""
import time

import pytest
from fastapi.testclient import TestClient

import app.core.config as cfg
from app.core import session_auth
from app.core.session_auth import CredentialStore, Credentials

CREDS = Credentials("Admin", "Admin@123", "unit-test-session-secret")


class FixedStore(CredentialStore):
    def __init__(self, creds):
        super().__init__(settings=cfg.Settings(require_login=True))
        self.creds = creds

    def get(self):
        return self.creds


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REQUIRE_LOGIN", "true")
    cfg.get_settings.cache_clear()
    store = FixedStore(CREDS)
    monkeypatch.setattr(session_auth, "credential_store", store)
    session_auth.login_throttle.reset()
    from app.main import create_app

    c = TestClient(create_app(), raise_server_exceptions=False, base_url="https://testserver")
    c.store = store
    yield c
    cfg.get_settings.cache_clear()
    session_auth.login_throttle.reset()


def login(c, username="Admin", password="Admin@123"):
    return c.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_api_requires_session(client):
    assert client.get("/api/v1/options").status_code == 401
    assert client.post("/api/v1/pipelines/1/analyze", json={"months": 3}).status_code == 401


def test_health_login_and_me_are_open(client):
    assert client.get("/api/v1/health").status_code != 401
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["authenticated"] is False and me.json()["loginRequired"] is True


def test_login_success_sets_hardened_cookie_and_unlocks_api(client):
    r = login(client)
    assert r.status_code == 200 and r.json()["authenticated"] is True
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert client.get("/api/v1/options").status_code != 401
    assert client.get("/api/v1/auth/me").json()["name"] == "Admin"


@pytest.mark.parametrize("user,pw", [("Admin", "wrong"), ("admin", "Admin@123"), ("Root", "Admin@123"), ("Admin", "admin@123")])
def test_login_rejects_bad_credentials_without_hinting_which_field(client, user, pw):
    r = login(client, user, pw)
    assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password."
    assert "set-cookie" not in r.headers
    assert client.get("/api/v1/options").status_code == 401


def test_logout_clears_session(client):
    login(client)
    assert client.post("/api/v1/auth/logout").status_code == 200
    client.cookies.clear()
    assert client.get("/api/v1/options").status_code == 401


def test_forged_tampered_and_expired_tokens_are_rejected():
    good = session_auth.create_session_token(CREDS, 60)
    assert session_auth.verify_session_token(good, CREDS) == "Admin"
    version, payload, sig = good.split(".")
    assert session_auth.verify_session_token(f"{version}.{payload}.{sig[:-2]}xx", CREDS) is None
    assert session_auth.verify_session_token(f"{version}.{payload}x.{sig}", CREDS) is None
    assert session_auth.verify_session_token("garbage", CREDS) is None
    assert session_auth.verify_session_token(None, CREDS) is None
    assert session_auth.verify_session_token(session_auth.create_session_token(CREDS, -1), CREDS) is None
    other_key = Credentials("Admin", "Admin@123", "a-different-secret")
    assert session_auth.verify_session_token(good, other_key) is None


def test_changing_the_password_in_key_vault_signs_everyone_out(client):
    login(client)
    assert client.get("/api/v1/options").status_code != 401
    client.store.creds = Credentials("Admin", "NewPassword#1", CREDS.session_secret)
    assert client.get("/api/v1/options").status_code == 401
    assert login(client, password="Admin@123").status_code == 401
    assert login(client, password="NewPassword#1").status_code == 200


def test_fails_closed_when_no_credentials_are_configured(client):
    client.store.creds = None
    assert login(client).status_code == 401
    assert client.get("/api/v1/options").status_code == 401


def test_pbkdf2_verifier_supported():
    verifier = session_auth.hash_password("Admin@123", iterations=1000)
    assert verifier.startswith("pbkdf2_sha256$1000$")
    assert session_auth.verify_password("Admin@123", verifier)
    assert not session_auth.verify_password("nope", verifier)
    assert not session_auth.verify_password("Admin@123", "pbkdf2_sha256$broken")


def test_brute_force_is_throttled_then_recovers(client, monkeypatch):
    for _ in range(5):
        assert login(client, password="bad").status_code == 401
    locked = login(client)  # even the right password is refused while locked out
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0
    session_auth.login_throttle.reset()
    assert login(client).status_code == 200


def test_throttle_window_expires():
    t = session_auth.LoginThrottle(per_client=2, global_limit=10, window_seconds=1)
    t.record_failure("1.2.3.4")
    t.record_failure("1.2.3.4")
    assert t.retry_after("1.2.3.4") > 0
    assert t.retry_after("5.6.7.8") == 0
    time.sleep(1.1)
    assert t.retry_after("1.2.3.4") == 0


def test_credential_store_reads_key_vault_and_caches(monkeypatch):
    calls = []

    class Secret:
        def __init__(self, value):
            self.value = value

    class FakeSecretClient:
        def __init__(self, vault_url, credential):
            assert vault_url == "https://vault.test/"

        def get_secret(self, name):
            calls.append(name)
            return Secret({"app-auth-username": "Admin", "app-auth-password": "Admin@123", "app-auth-session-secret": "sess"}[name])

    import azure.identity
    import azure.keyvault.secrets

    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", FakeSecretClient)
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: object())
    store = CredentialStore(settings=cfg.Settings(key_vault_url="https://vault.test/"))
    first = store.get()
    assert (first.username, first.password, first.session_secret) == ("Admin", "Admin@123", "sess")
    n = len(calls)
    assert store.get() is first and len(calls) == n  # served from cache


def test_credential_store_without_key_vault_uses_local_fallback_and_missing_means_closed():
    assert CredentialStore(settings=cfg.Settings(key_vault_url="", auth_username="u", auth_password="p")).get().username == "u"
    assert CredentialStore(settings=cfg.Settings(key_vault_url="")).get() is None
