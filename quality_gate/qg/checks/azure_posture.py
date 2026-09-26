from __future__ import annotations

import re
import shutil

from qg.model import CheckResult, Finding, FAIL, PASS, SKIP, WARN
from qg.util import parse_json, run

ID, NAME, CATEGORY = "azure", "Live Azure deployment posture (read-only)", "Security"
WHAT = ("Inspects the deployed App Service / Function App configuration through the Azure CLI: HTTPS-only, TLS version, FTP, "
        "authentication in front of the app, managed identity, IP restrictions, CORS, and whether secrets are Key Vault references. "
        "Only reads settings; secret values are never fetched or printed.")

SECRET_NAME = re.compile(r"(?i)(password|secret|_key$|_pat$|connection_?string|token|api_?key)")
SAFE_NAMES = {"SCM_DO_BUILD_DURING_DEPLOYMENT", "ADO_PAT_SECRET_NAME", "SQL_CONNECTION_SECRET_NAME", "ADO_PAT_SECRET_TEMPLATE",
              "APPLICATIONINSIGHTS_CONNECTION_STRING"}  # telemetry ingestion identifier, not a credential


def _az(*args: str) -> dict | list | None:
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        return None
    r = run([az, *args, "-o", "json", "--only-show-errors"], timeout=120)
    return parse_json(r.stdout, None) if r.returncode == 0 else None


def _check_app(res: CheckResult, kind: str, name: str, rg: str) -> bool:
    cmd = "webapp" if kind == "web" else "functionapp"
    site = _az(cmd, "show", "-g", rg, "-n", name)
    if site is None:
        return False
    cfg = _az(cmd, "config", "show", "-g", rg, "-n", name) or {}
    where = f"{kind} app '{name}'"

    def add(sev: str, title: str, fix: str, rule: str) -> None:
        res.findings.append(Finding(sev, title, where, "", rule, fix))

    if not site.get("httpsOnly"):
        add("high", "HTTPS-only is OFF (plain-HTTP requests are accepted; API keys, PATs and tokens can travel unencrypted)",
            f"az {cmd} update -g {rg} -n {name} --https-only true", "AZ-HTTPS")
    if str(cfg.get("minTlsVersion", "")) not in ("1.2", "1.3"):
        add("high", f"Minimum TLS version is {cfg.get('minTlsVersion')}", f"az {cmd} config set -g {rg} -n {name} --min-tls-version 1.2", "AZ-TLS")
    if str(cfg.get("ftpsState", "")).lower() == "allallowed":
        add("medium", "FTP (unencrypted) is enabled", f"az {cmd} config set -g {rg} -n {name} --ftps-state FtpsOnly", "AZ-FTP")
    if cfg.get("remoteDebuggingEnabled"):
        add("high", "Remote debugging is enabled", f"az {cmd} config set -g {rg} -n {name} --remote-debugging-enabled false", "AZ-DEBUG")
    if not site.get("identity"):
        add("medium", "No managed identity; secrets must be stored as passwords", f"az {cmd} identity assign -g {rg} -n {name}", "AZ-MI")
    if kind == "web":
        auth = _az("webapp", "auth", "show", "-g", rg, "-n", name) or {}
        if not auth.get("enabled"):
            add("high", "No authentication in front of the web app: every API route, including POST /ado/ingest and /analyze, is open to the internet",
                "Enable App Service Authentication (Microsoft Entra ID) with 'Require authentication', then set REQUIRE_EASY_AUTH=true.", "AZ-NOAUTH")
        if not cfg.get("http20Enabled"):
            res.findings.append(Finding("info", "HTTP/2 is disabled", where, "", "AZ-HTTP2", f"az webapp config set -g {rg} -n {name} --http20-enabled true"))
    restrictions = cfg.get("ipSecurityRestrictions") or []
    if all(r.get("action") == "Allow" and not r.get("ip_address") or r.get("ip_address") == "Any" for r in restrictions):
        res.findings.append(Finding("low", "No network access restrictions (open to all IPs)", where, "", "AZ-IP",
                                    "Add access restrictions or private endpoints if the app is internal-only."))
    settings = _az(cmd, "config", "appsettings", "list", "-g", rg, "-n", name) or []
    for s in settings:
        n, v = s.get("name", ""), str(s.get("value") or "")
        if SECRET_NAME.search(n) and n not in SAFE_NAMES and v and not v.startswith("@Microsoft.KeyVault"):
            add("high", f"App setting '{n}' holds a secret directly (not a Key Vault reference)",
                "Store it in Key Vault and reference it: @Microsoft.KeyVault(SecretUri=...)", "AZ-SECRET")
    for s in settings:
        n, v = s.get("name", ""), str(s.get("value") or "")
        if re.search(r"(?i)(AccountKey|SharedAccessKey|Password|Pwd)=[^;\s]{6,}", v) and not v.startswith("@Microsoft.KeyVault") and not SECRET_NAME.search(n):
            res.findings.append(Finding("low", f"App setting '{n}' embeds a credential in its value", where, "", "AZ-SECRET-VALUE",
                                        "Prefer an identity-based connection or a Key Vault reference."))
    cors = _az(cmd, "cors", "show", "-g", rg, "-n", name) or {}
    if "*" in (cors.get("allowedOrigins") or []):
        add("medium", "CORS allows every origin (*)", f"az {cmd} cors remove -g {rg} -n {name} --allowed-origins '*'", "AZ-CORS")
    return True


def run_check(cfg: dict, enabled: bool) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    if not enabled:
        res.status, res.summary = SKIP, "skipped by --no-azure; the live deployment was NOT inspected"
        return res
    if not (shutil.which("az") or shutil.which("az.cmd")):
        res.status, res.summary = SKIP, "Azure CLI not installed: the live deployment was NOT inspected"
        return res
    if _az("account", "show") is None:
        res.status, res.summary = SKIP, "not logged in: the live deployment was NOT inspected (run `az login` and re-run)"
        return res
    checked = 0
    for app in cfg["azure"].get("webapps", []):
        checked += _check_app(res, "web", app["name"], app["resource_group"])
    for app in cfg["azure"].get("functionapps", []):
        checked += _check_app(res, "function", app["name"], app["resource_group"])
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    res.findings.sort(key=lambda f: order[f.severity])
    c = res.counts
    res.metrics = {"apps inspected": checked, "high": c["high"], "medium": c["medium"], "low": c["low"]}
    if not checked:
        res.status, res.summary = WARN, "could not read any configured app (check names/resource groups/permissions)"
    elif c["high"] or c["critical"]:
        res.status, res.summary = FAIL, f"{c['high'] + c['critical']} high-risk misconfiguration(s) in the live deployment"
    elif c["medium"]:
        res.status, res.summary = FAIL, f"{c['medium']} medium misconfiguration(s) in the live deployment"
    elif res.findings:
        res.status, res.summary = WARN, f"{len(res.findings)} minor deployment note(s)"
    else:
        res.status, res.summary = PASS, f"{checked} app(s) follow the hardening baseline"
    return res
