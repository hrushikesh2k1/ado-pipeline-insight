# Quality gate

One command runs every security and quality check on this project and writes a single HTML report that says
**PASS**, **PASS WITH WARNINGS**, or **NOT READY** (with what to fix first).

## Run it

```powershell
.\quality_gate\run.ps1              # Windows: creates .venv-quality on first run, runs everything, opens the report
.\quality_gate\run.ps1 --no-azure   # code-only run; by default the live Azure apps are inspected too when `az login` is active
.\quality_gate\run.ps1 --ci         # strict mode for pipelines: skipped checks fail, exit code 1 on FAIL
```

```bash
./quality_gate/run.sh [--no-azure] [--ci]      # Linux / macOS / CI agents
```

Useful options: `--only sast,deps` (run some checks), `--skip types`, `--no-live` (skip the checks that call the deployed site), `--open`.

Output (all in `quality_gate/reports/`, git-ignored):

| File | Purpose |
|---|---|
| `report.html` | The report (self-contained, works offline, light/dark) |
| `report-<timestamp>.html` | History of previous runs |
| `report.json` | Machine-readable results for dashboards or CI |
| `raw/` | Raw tool output (bandit, coverage, junit) |

Exit code is `0` unless a **blocking** check failed, so it can gate a pipeline.

## What it checks

| Check id | What it does | Blocks the gate when |
|---|---|---|
| `sast` | **Bandit** static analysis: SQL built from strings, hard-coded passwords, unsafe eval/pickle/subprocess, weak crypto, binding 0.0.0.0, swallowed exceptions | any finding of severity medium or higher |
| `deps` | **pip-audit** on every requirements file (+ **npm audit** on `frontend/` if npm is installed) against public CVE databases | any known Python vulnerability; npm high/critical |
| `secrets` | Regex scan of every git-tracked and untracked-not-ignored file for passwords, connection strings, keys, tokens, PATs | any match |
| `api_security` | **Attack simulation** against the real FastAPI app and Azure Function handlers (no network, no database): SQL-injection payloads, URL/path injection via organization/project, header injection, oversized bodies, error-message leaks, PAT leakage in logs, missing security headers, cache headers, exposed `/docs`, CORS abuse, anonymous access, server-PAT abuse | any scenario succeeds |
| `config` | Dockerfile (non-root, pinned image), CI workflows (token permissions, pinned actions, a gate before deploy), pinned dependencies, committed `venv/`, `.env`, publish profiles, zips, logs | any medium+ issue |
| `lint` | **Ruff**: bug-finding rules block (F, E9, B, S, PLE); style rules are advisory | any blocking rule violation |
| `smells` | **radon** complexity / maintainability, long functions and files, **vulture** dead code, duplicated blocks | a function above the complexity limit; the rest are warnings |
| `types` | **mypy** on `app/` and `core/` | never (advisory) |
| `tests` | Runs `tests/` under **pytest-cov** with branch coverage | a failing test, or coverage below `fail_under` |
| `functional` | **Live data accuracy** (read-only, ~5 min because the API is slow): recomputes every summary card from the raw runs; checks Recent Runs order, durations and paging; proves the per-run and daily build-duration trends reconcile with the runs; checks run detail against its stages/jobs/tasks and that the deployed site is hardened. With database access it also reconciles against independent SQL and checks data integrity (negative durations, orphans, duplicates) | any figure that is wrong or inconsistent |
| `ui_accuracy` | **Playwright** opens the deployed dashboard in headless Chromium and checks every card, the trend tab counts, the Recent Runs rows and the run drawer equal what the API returned to the page | any mismatch |
| `azure` (automatic when logged in with `az login`; read-only) | Live App Service / Function App posture: HTTPS-only, TLS, FTPS, remote debugging, authentication in front of the app, managed identity, IP restrictions, CORS, secrets not stored as Key Vault references | any medium+ misconfiguration |

The `azure` check matters: whether the deployed site requires a login is an Azure setting, not something the code can prove.
When you are not logged in to Azure the report says **deployment not inspected** and never shows a clean PASS.

## Tune it

Everything that decides pass/fail is in `quality_gate.toml` (severity thresholds, coverage minimum, complexity limits,
Azure app names). Accepted risks go in `[dependencies].ignore` with a reason and an expiry date, so they cannot be
forgotten.

To suppress a Bandit false positive, put `# nosec B608 - <why it is safe>` on that line. The reason is mandatory by convention.

Add a new attack scenario by writing a test in `security_tests/` and tagging it:

```python
@pytest.mark.sec(severity="high", area="Injection", title="What the attacker tries", fix="How to fix it")
def test_something(client): ...
```

## Requirements

Python 3.11 (same as Azure). `run.ps1` / `run.sh` create `.venv-quality` and install the app's own requirements plus
`quality_gate/requirements.txt` automatically. pip-audit and npm audit need internet access.

## Relationship to `tests/security/`

`tests/security/test_security_scan.py` (Bandit + pip-audit only) is superseded by `sast` and `deps` here. It is left
untouched; delete it once you are happy with this gate.

## Data-accuracy tests in detail

Three layers, each catching a different kind of wrong number:

1. **`tests/test_trends_and_runs_logic.py`** (offline, milliseconds): the arithmetic on rows and the exact SQL parameters for summary,
   recent runs, trends and run detail. Runs with the normal unit tests.
2. **`quality_gate/functional_tests/`** (live, read-only): the deployed API against itself. `test_data_consistency.py` recomputes each
   figure from the raw run list; `test_deployment_smoke.py` checks the deployed site is hardened and its files are served;
   `test_db_reconciliation.py` compares against independent SQL and checks table integrity.
3. **`frontend/playwright/tests/accuracy.spec.ts`**: what is drawn on screen versus what the API returned.

**Database reconciliation needs database access.** It reads the connection string from `QG_SQL_CONNECTION_STRING`, or from Key Vault with your
`az login`, and needs your IP allowed on the Azure SQL firewall. Without that the scenarios are reported as **not run** (never as passed) and the
check ends as a warning. Only `SELECT` statements are ever executed.

If the site is behind App Service Authentication, set `QG_BEARER_TOKEN`; otherwise the live checks report that they need sign-in.
Override the target with `QG_BASE_URL`.
