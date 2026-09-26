# Security scan test suite

Checks this project's own source code and dependencies for security issues.

## What it checks

1. **Static code analysis (Bandit)** — scans `core/`, `app/`, `functions/`,
   `function_app.py`, `get_recommendations/`, `ingest_run/` for insecure
   patterns: hardcoded secrets/credentials, SQL built via string
   concatenation, unsafe `eval`/`exec`/`pickle`, weak crypto, etc.
   Fails on any finding with severity >= medium and confidence >= medium.

2. **Dependency vulnerability scan (pip-audit)** — checks every pinned
   package in `requirements.txt`, `requirements-backend.txt`, and
   `functions/requirements.txt` against known CVE/advisory databases.
   Fails on any known vulnerability.

It does **not** currently scan the `frontend/` JS code, repo secrets
outside dependency files, or the Azure Pipelines YAML files — that was an
explicit scope decision, not an oversight. Ask for those to be added if
you want broader coverage.

## Setup

```bash
pip install -r tests/security/requirements-security.txt
```

## Run

```bash
pytest tests/security/test_security_scan.py -v
```

Reports are written to `tests/security/reports/` on every run:
- `bandit_<timestamp>.json` / `bandit_latest.json`
- `pip_audit_<timestamp>.json` / `pip_audit_latest.json`

If a tool isn't installed, its test is skipped (not failed) with a message
telling you how to install it. If pip-audit can't reach the network (e.g.
in an offline CI runner), that test is skipped rather than failed, and the
reason is recorded in the report.

## Adjusting strictness

Thresholds are set as module-level constants at the top of
`test_security_scan.py`:

- `BANDIT_SEVERITY_THRESHOLD` / `BANDIT_CONFIDENCE_THRESHOLD` (`low` /
  `medium` / `high`)
- pip-audit currently fails on *any* finding — there's no severity knob to
  tune, since pip-audit's advisory sources don't consistently expose a
  CVSS score.
