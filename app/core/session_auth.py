"""Username/password sign-in with credentials held in Azure Key Vault and signed, HttpOnly session cookies.

Key Vault secrets (names configurable in Settings):
  app-auth-username        the login name
  app-auth-password        the password: plain text, or "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>" (see hash_password)
  app-auth-session-secret  optional random string used to sign session cookies (a per-process secret is used if absent)

Secrets are re-read every CREDENTIAL_TTL_SECONDS, so rotating the password in Key Vault takes effect without a restart
and signs everyone out (the session signature is bound to the current password secret).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "ado_session"
CREDENTIAL_TTL_SECONDS = 60
PBKDF2_PREFIX = "pbkdf2_sha256"
# /api/ paths reachable without a session. auth/me answers 200 {"authenticated": false} so the SPA can pick its screen.
OPEN_API_PATHS = frozenset({"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/me"})

_PROCESS_SECRET = secrets.token_hex(32)


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str  # plain text or pbkdf2 verifier
    session_secret: str


def hash_password(password: str, iterations: int = 600_000) -> str:
    """Build a verifier you can store in Key Vault instead of the plain password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_PREFIX}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(candidate: str, stored: str) -> bool:
    if stored.startswith(PBKDF2_PREFIX + "$"):
        try:
            _, iterations, salt_hex, hash_hex = stored.split("$")
            digest = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
            return hmac.compare_digest(digest, bytes.fromhex(hash_hex))
        except (ValueError, TypeError):
            logger.error("Stored password verifier is malformed; refusing all logins.")
            return False
    # Hash both sides so the comparison time does not depend on the length of either value.
    return hmac.compare_digest(hashlib.sha256(candidate.encode("utf-8")).digest(), hashlib.sha256(stored.encode("utf-8")).digest())


class CredentialStore:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings
        self._lock = threading.Lock()
        self._cached: Credentials | None = None
        self._loaded_at = 0.0

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    def get(self) -> Credentials | None:
        with self._lock:
            if self._cached is not None and time.monotonic() - self._loaded_at < CREDENTIAL_TTL_SECONDS:
                return self._cached
            try:
                loaded = self._load()
            except Exception as exc:  # Key Vault unreachable: keep serving the last good value, else fail closed.
                logger.error("Could not load sign-in credentials: %s", type(exc).__name__)
                loaded = self._cached
            if loaded is not None:
                self._cached = loaded
                self._loaded_at = time.monotonic()
            return loaded

    def _load(self) -> Credentials | None:
        s = self.settings
        if s.key_vault_url:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            client = SecretClient(vault_url=s.key_vault_url, credential=DefaultAzureCredential())
            username = client.get_secret(s.auth_username_secret_name).value or ""
            password = client.get_secret(s.auth_password_secret_name).value or ""
            try:
                session_secret = client.get_secret(s.auth_session_secret_name).value or ""
            except Exception:
                session_secret = ""
        else:
            username, password, session_secret = s.auth_username, s.auth_password, s.auth_session_secret
        if not username or not password:
            return None
        return Credentials(username, password, session_secret or _PROCESS_SECRET)

    def clear(self) -> None:
        with self._lock:
            self._cached = None
            self._loaded_at = 0.0


credential_store = CredentialStore()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signing_key(creds: Credentials) -> bytes:
    # Bound to the username and password secret: rotating either invalidates every outstanding session.
    material = f"session|{creds.username}|{creds.password}".encode("utf-8")
    return hmac.new(creds.session_secret.encode("utf-8"), material, hashlib.sha256).digest()


def create_session_token(creds: Credentials, lifetime_seconds: int) -> str:
    payload = _b64(json.dumps({"u": creds.username, "exp": int(time.time()) + lifetime_seconds}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(_signing_key(creds), payload.encode("ascii"), hashlib.sha256).digest())
    return f"v1.{payload}.{signature}"


def verify_session_token(token: str | None, creds: Credentials | None) -> str | None:
    """Return the signed-in username, or None when the token is missing, forged, expired or from before a rotation."""
    if not token or creds is None:
        return None
    try:
        version, payload, signature = token.split(".")
        if version != "v1":
            return None
        expected = _b64(hmac.new(_signing_key(creds), payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_unb64(payload))
        if int(data["exp"]) < time.time() or data["u"] != creds.username:
            return None
        return str(data["u"])
    except (ValueError, KeyError, TypeError):
        return None


def session_user(request: Request, store: CredentialStore | None = None) -> str | None:
    return verify_session_token(request.cookies.get(COOKIE_NAME), (store or credential_store).get())


def check_login(username: str, password: str, store: CredentialStore | None = None) -> Credentials | None:
    """Verify a username/password pair. Both checks always run so timing does not reveal which one was wrong."""
    creds = (store or credential_store).get()
    if creds is None:
        return None
    user_ok = hmac.compare_digest(hashlib.sha256(username.encode("utf-8")).digest(), hashlib.sha256(creds.username.encode("utf-8")).digest())
    pass_ok = verify_password(password, creds.password)
    return creds if user_ok and pass_ok else None


class LoginThrottle:
    """Per-client and global failed-attempt limiter (in memory; the app runs as a single instance)."""

    def __init__(self, per_client: int = 5, global_limit: int = 50, window_seconds: int = 900):
        self.per_client, self.global_limit, self.window = per_client, global_limit, window_seconds
        self._failures: dict[str, list[float]] = {}
        self._global: list[float] = []
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        self._global = [t for t in self._global if t > cutoff]
        for key in list(self._failures):
            self._failures[key] = [t for t in self._failures[key] if t > cutoff]
            if not self._failures[key]:
                del self._failures[key]

    def retry_after(self, client: str) -> int:
        """Seconds the caller must wait, or 0 when allowed."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            for stamps, limit in ((self._failures.get(client, []), self.per_client), (self._global, self.global_limit)):
                if len(stamps) >= limit:
                    return max(1, int(stamps[0] + self.window - now))
        return 0

    def record_failure(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._failures) < 10_000:
                self._failures.setdefault(client, []).append(now)
            self._global.append(now)

    def record_success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._global.clear()


login_throttle = LoginThrottle()


def client_id(request: Request) -> str:
    """App Service appends the real client address to X-Forwarded-For; the last entry is the one its front end added."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        last = forwarded.split(",")[-1].strip()
        if last.count(":") == 1:  # IPv4 with a port, e.g. 203.0.113.9:51234
            last = last.split(":")[0]
        return last
    return request.client.host if request.client else "unknown"


def cookie_is_secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


class SessionAuthGate:
    """Return 401 for every /api/ route except the sign-in endpoints and the health probe unless a valid session cookie is sent."""

    def __init__(self, app: ASGIApp, store: CredentialStore | None = None):
        self.app = app
        self.store = store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if path.startswith("/api/") and path not in OPEN_API_PATHS and scope["method"] != "OPTIONS":
                request = Request(scope)
                if await run_in_threadpool(session_user, request, self.store) is None:
                    response: Response = JSONResponse({"detail": "Authentication required."}, status_code=401)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
