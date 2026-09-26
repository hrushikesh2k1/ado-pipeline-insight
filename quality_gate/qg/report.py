from __future__ import annotations

import html
from datetime import datetime

from qg.model import CheckResult, FAIL, PASS, SEVERITIES, SKIP, WARN, ERROR

STATUS_LABEL = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN", SKIP: "SKIPPED", ERROR: "ERROR"}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1f24;--muted:#5b6672;--line:#e3e7ec;--pass:#18794e;--pass-bg:#e6f6ee;--fail:#b42318;--fail-bg:#fdecea;
--warn:#a15c00;--warn-bg:#fff4dc;--skip:#5b6672;--skip-bg:#eceff3;--accent:#1f4fd8;--code:#f0f2f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1318;--card:#171c23;--text:#e8ecf1;--muted:#98a4b3;--line:#28303a;--pass:#4cd08a;--pass-bg:#12301f;--fail:#ff7b72;--fail-bg:#3a1714;
--warn:#f0b34a;--warn-bg:#3a2b0e;--skip:#98a4b3;--skip-bg:#222932;--accent:#7aa2ff;--code:#1f2630}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0}h2{font-size:17px;margin:32px 0 12px}h3{font-size:14px;margin:18px 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.verdict{border-radius:12px;padding:22px 24px;margin:18px 0;display:flex;gap:18px;align-items:center;border:1px solid var(--line)}
.verdict.PASS{background:var(--pass-bg);border-color:var(--pass)}.verdict.FAIL{background:var(--fail-bg);border-color:var(--fail)}.verdict.WARN{background:var(--warn-bg);border-color:var(--warn)}
.verdict .big{font-size:34px;font-weight:800;letter-spacing:.02em}.verdict.PASS .big{color:var(--pass)}.verdict.FAIL .big{color:var(--fail)}.verdict.WARN .big{color:var(--warn)}
.meta{color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;border-left:5px solid var(--skip);text-decoration:none;color:inherit;display:block}
.tile.PASS{border-left-color:var(--pass)}.tile.FAIL{border-left-color:var(--fail)}.tile.WARN{border-left-color:var(--warn)}.tile.ERROR{border-left-color:var(--fail)}
.tile .n{font-weight:600}.tile .s{color:var(--muted);font-size:12.5px;margin-top:4px}
.pill{display:inline-block;padding:1px 9px;border-radius:99px;font-size:11.5px;font-weight:700;letter-spacing:.03em}
.pill.PASS{background:var(--pass-bg);color:var(--pass)}.pill.FAIL,.pill.ERROR{background:var(--fail-bg);color:var(--fail)}.pill.WARN{background:var(--warn-bg);color:var(--warn)}.pill.SKIP{background:var(--skip-bg);color:var(--skip)}
.pill.critical,.pill.high{background:var(--fail-bg);color:var(--fail)}.pill.medium{background:var(--warn-bg);color:var(--warn)}.pill.low,.pill.info{background:var(--skip-bg);color:var(--skip)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:14px 0}
.card header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
.card h2{margin:0 0 4px;font-size:16px}.what{color:var(--muted);margin:2px 0 10px;max-width:900px}
.kv{display:flex;flex-wrap:wrap;gap:8px 22px;margin:8px 0}.kv div{font-size:12.5px;color:var(--muted)}.kv b{color:var(--text);font-size:15px;display:block}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0 4px}th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
code,.loc{font-family:ui-monospace,Consolas,monospace;font-size:12px;background:var(--code);padding:1px 5px;border-radius:4px;word-break:break-all}
.fix{color:var(--muted);font-size:12.5px;margin-top:3px}.fix b{color:var(--text)}
details{margin-top:8px}summary{cursor:pointer;color:var(--accent);font-weight:600}
.bar{background:var(--line);border-radius:4px;height:8px;min-width:70px;position:relative}.bar i{display:block;height:8px;border-radius:4px;background:var(--pass)}.bar.mid i{background:var(--warn)}.bar.low i{background:var(--fail)}
.top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline}
.sev{display:flex;gap:6px;flex-wrap:wrap}
footer{color:var(--muted);font-size:12px;margin-top:40px}
@media print{body{background:#fff}.card,.tile{break-inside:avoid}}
"""


def _e(x) -> str:
    return html.escape(str(x))


def _table(rows: list[dict]) -> str:
    if not rows:
        return ""
    cols = list(rows[0].keys())
    head = "".join(f"<th>{_e(c)}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for c in cols:
            v = r[c]
            if c in ("result", "severity", "rank") and str(v):
                cls = {"pass": "PASS", "FAIL": "FAIL"}.get(str(v), str(v))
                cells.append(f'<td><span class="pill {cls}">{_e(v)}</span></td>')
            elif c == "coverage %":
                cls = "" if v >= 80 else ("mid" if v >= 60 else "low")
                cells.append(f'<td><div class="bar {cls}"><i style="width:{min(100, max(2, v))}%"></i></div>{v}%</td>')
            elif c in ("file", "function", "uncovered lines"):
                cells.append(f"<td><span class='loc'>{_e(v)}</span></td>" if v != "" else "<td></td>")
            else:
                cells.append(f"<td>{_e(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _findings(res: CheckResult, limit: int = 400) -> str:
    if not res.findings:
        return ""
    rows = []
    for f in res.findings[:limit]:
        fix = f'<div class="fix"><b>How to fix:</b> {_e(f.fix)}</div>' if f.fix else ""
        detail = f'<div class="fix">{_e(f.detail)}</div>' if f.detail else ""
        rule = f"<code>{_e(f.rule)}</code>" if f.rule else ""
        rows.append(f'<tr><td><span class="pill {f.severity}">{f.severity.upper()}</span></td>'
                    f'<td>{_e(f.title)}{detail}{fix}</td><td><span class="loc">{_e(f.location)}</span></td><td>{rule}</td></tr>')
    more = f"<p class='fix'>Showing {limit} of {len(res.findings)} findings; see report.json for all.</p>" if len(res.findings) > limit else ""
    return ('<table><thead><tr><th>Severity</th><th>Finding</th><th>Where</th><th>Rule</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>" + more)


def _card(res: CheckResult) -> str:
    kv = "".join(f"<div>{_e(k)}<b>{_e(v)}</b></div>" for k, v in res.metrics.items())
    counts = res.counts
    sev = "".join(f'<span class="pill {s}">{counts[s]} {s}</span>' for s in SEVERITIES if counts[s])
    tables = ""
    for title, rows in res.tables.items():
        if not rows:
            continue
        big = len(rows) > 14
        inner = f"<h3>{_e(title)}</h3>{_table(rows)}"
        tables += f"<details><summary>{_e(title)} ({len(rows)})</summary>{_table(rows)}</details>" if big else inner
    finds = _findings(res)
    if finds:
        opener = " open" if res.status in (FAIL, ERROR) and len(res.findings) <= 40 else ""
        finds = f"<details{opener}><summary>Findings ({len(res.findings)})</summary>{finds}</details>"
    blocking = "" if res.blocking else ' <span class="pill SKIP">advisory only</span>'
    return f"""<section class="card" id="{res.id}"><header><div><h2>{_e(res.name)}{blocking}</h2>
<div class="loc" style="background:none;padding:0;color:var(--muted)">{_e(res.category)} &middot; {res.duration:.1f}s</div></div>
<div><span class="pill {res.status}">{STATUS_LABEL[res.status]}</span></div></header>
<p class="what">{_e(res.what)}</p><p><b>{_e(res.summary)}</b></p><div class="sev">{sev}</div><div class="kv">{kv}</div>{tables}{finds}</section>"""


def overall(results: list[CheckResult], strict: bool) -> str:
    blocking_fail = any(r.status in (FAIL, ERROR) and r.blocking for r in results)
    strict_skip = strict and any(r.status == SKIP and r.id != "azure" for r in results)
    if blocking_fail or strict_skip:
        return FAIL
    if any(r.status in (WARN, FAIL, ERROR) or r.status == SKIP for r in results):
        return WARN
    return PASS


def render(results: list[CheckResult], env: dict, strict: bool) -> str:
    verdict = overall(results, strict)
    headline = {PASS: "SECURE &amp; HEALTHY", WARN: "PASSED WITH WARNINGS", FAIL: "NOT READY: BLOCKING ISSUES"}[verdict]
    sub = {
        PASS: "Every blocking check passed.",
        WARN: "No blocking failures, but some checks reported warnings or were skipped. Review them below.",
        FAIL: "At least one blocking check failed. Do not deploy until the items marked FAIL are fixed.",
    }[verdict]
    azure_skipped = any(r.id == "azure" and r.status == SKIP for r in results)
    if azure_skipped:
        sub += " NOTE: the live Azure deployment was NOT inspected, so this verdict covers the code only."
        if verdict == PASS:
            headline = "CODE CHECKS PASSED (deployment not inspected)"
    totals = {s: sum(r.counts[s] for r in results) for s in SEVERITIES}
    failing = [r for r in results if r.status in (FAIL, ERROR)]
    tiles = "".join(
        f'<a class="tile {r.status}" href="#{r.id}"><div class="top"><span class="n">{_e(r.name.split(" (")[0])}</span>'
        f'<span class="pill {r.status}">{STATUS_LABEL[r.status]}</span></div><div class="s">{_e(r.summary)}</div></a>'
        for r in results)
    action = ""
    if failing:
        items = "".join(f"<li><a href='#{r.id}'>{_e(r.name)}</a>: {_e(r.summary)}</li>" for r in failing)
        action = f'<div class="card"><h2>What to fix first</h2><ol>{items}</ol></div>'
    meta = "".join(f"<span>{_e(k)}: <b>{_e(v)}</b></span>" for k, v in env.items())
    sev_pills = "".join(f'<span class="pill {s}">{totals[s]} {s}</span>' for s in SEVERITIES if totals[s]) or '<span class="pill PASS">0 findings</span>'
    cards = "".join(_card(r) for r in results)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quality Gate Report</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Quality Gate Report</h1>
<div class="verdict {verdict}"><div class="big">{headline}</div><div><div>{_e(sub)}</div><div class="sev" style="margin-top:8px">{sev_pills}</div></div></div>
<div class="meta">{meta}</div>
{action}
<h2>Checks at a glance</h2><div class="grid">{tiles}</div>
<h2>Details</h2>{cards}
<footer>Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by quality_gate/run_all.py. Machine-readable copy: report.json. Thresholds: quality_gate/quality_gate.toml.</footer>
</div></body></html>"""
