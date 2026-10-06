"""The IRP format the organisation asked for: the three sections of its IRP example, with a 3-column Remediation Steps table.

The prompt asks the model for exactly this skeleton. `normalize_irp_markdown` then enforces it on whatever came back, so a model that
adds a section, an "Expected outcome" column or a stray pipe inside a KQL query cannot change the shape of the document.
"""
from __future__ import annotations

import re
from typing import Any

SECTION_ALERT = "Alert Details"
SECTION_PREREQUISITES = "Prerequisites"
SECTION_REMEDIATION = "Remediation Steps"
SECTIONS = (SECTION_ALERT, SECTION_PREREQUISITES, SECTION_REMEDIATION)

REMEDIATION_COLUMNS = ("STEPS", "ACTIONS", "ADDITIONAL INFO")
REMEDIATION_HEADER = "| " + " | ".join(f"**{name}**" for name in REMEDIATION_COLUMNS) + " |"
REMEDIATION_DIVIDER = "| " + " | ".join("---" for _ in REMEDIATION_COLUMNS) + " |"

DEFAULT_SEVERITY = "Sev0 (Critical)"  # Azure Monitor: Sev0 Critical, Sev1 Error, Sev2 Warning, Sev3 Informational, Sev4 Verbose
DEFAULT_TRIGGER_CONDITION = "Metric threshold breached for > 5 minutes"  # what the single-pass writer is told when nothing was given; not a fact about the alert
DEFAULT_TARGET_RESOURCE = "<ResourceName>"  # what the built-in plans write when no resource is given; never sent to the model


def severity_name(severity: str | None) -> str:
    """'Sev0 (Critical)' -> 'Critical', the way the IRP example writes it; a value without brackets ('Sev-1') is returned as it is."""
    text = (severity or "").strip()
    inside = re.search(r"\(([^)]+)\)", text)
    return inside.group(1).strip() if inside else text


# These are our own limits, not the model's: the example is the skeleton the model copies, so it is sent whole.
MAX_EXAMPLE_CHARS = 60_000
MAX_TEMPLATE_CHARS = 30_000
MAX_ARM_CHARS = 4_000

IRP_SYSTEM_PROMPT = f"""You are a Principal Cloud Site Reliability Engineer writing an Incident Response Plan (IRP) for an Azure alert, in GitHub-flavored Markdown.

Return EXACTLY this skeleton and nothing else. It is the organisation's IRP example, reduced to three sections:

# <Alert Name>

# {SECTION_ALERT}

| **Alert** | <alert name> |
| --- | --- |
| **Description** | *This alert is designed to trigger when/if <condition>, deployed in <environment>. It is a critical issue when this occurs and the system cannot be accessible.* |
| **Severity** | <the severity name only: Critical, Error, Warning, Informational or Verbose> |
| **Source** | <Log or Metric> |
| **Root Cause** | - **Case 1 : ** <failure mode> - **Case 2 : ** <failure mode> - **Case 3 : ** <failure mode> |
| **Product** | <product or component> |

# {SECTION_PREREQUISITES}

<a bullet list of what is needed before starting: access or roles, and the input values the steps use, such as resource names>

# {SECTION_REMEDIATION}

{REMEDIATION_HEADER}
{REMEDIATION_DIVIDER}
| <step> | <what to do and where> | <expected outcome or notes> |

RULES:
1. Exactly three sections, in this order, with exactly these headings: "{SECTION_ALERT}", "{SECTION_PREREQUISITES}", "{SECTION_REMEDIATION}".
   Write no other section: no Testing Scenarios, Overview, Alert Properties, Remediation Overview, Investigation Steps, RCA & Mitigation,
   Example Story Submissions, References, Alert Enhancement, Lessons learned, Post-Incident Analysis and no authoring checklist. If the IRP template
   lists a Post-Incident Analysis or any other section, do not write it. Nothing may follow the {SECTION_REMEDIATION} table: no notes, no second table.
2. The {SECTION_REMEDIATION} table has EXACTLY 3 columns, with exactly this header: {REMEDIATION_HEADER}
   Never add a 4th column. Put the expected outcome or system behaviour after an action in ADDITIONAL INFO.
3. Aim for about 10 rows (there is no hard limit). Follow the row pattern of the IRP example when one is given: a row to check the status, a row to check
   the resource health, one row per root cause written as "Case N : <failure mode>", a row for log analysis if it helps, a "Health Check" row and a final
   row to confirm that the alert has stopped firing in CNC. Cover every case listed in Root Cause.
4. A table cell cannot hold line breaks: write several steps in one cell as "1. ... <br>2. ...". Put every command in backticks and say where to run it
   (Azure Portal, Azure Cloud Shell, CLI, Log Analytics). Write values the reader must supply in angle brackets, for example <ResourceGroupName>.
   Escape every pipe character inside a query or command as \\| so it cannot split the table.
5. Any step that changes something (scale, delete, reset, restart, configuration change) starts with "**Inform to the management for approval**." before the command.
6. Commands must follow the official Azure documentation: Azure CLI (az ...), Azure PowerShell and KQL for Log Analytics. Use the ARM template context
   and the alert output columns when they are given.
7. When an IRP example is given, copy its skeleton exactly: the same Alert Details row labels in the same order, the same style, the same row pattern. Take the
   content from the alert metadata, not from the example.
8. Return only the Markdown. No commentary and no code fence around it."""


# ---------------------------------------------------------------------------------------------------------------------
# What the model is given
# ---------------------------------------------------------------------------------------------------------------------

def _plain(text: str) -> str:
    return re.sub(r"[*_`:\\]", "", text).strip().lower()


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, text) of every Markdown heading that is not inside a code fence."""
    found: list[tuple[int, int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        match = None if in_fence else _HEADING.match(line)
        if match:
            found.append((index, len(match.group(1)), match.group(2)))
    return found


def section_key(heading: str) -> str | None:
    """Which of the three sections a heading is, or None. 'Alert Overview' counts as Alert Details; 'Remediation Overview' is not a section."""
    text = _plain(heading)
    if text.startswith(("alert details", "alert overview")):
        return SECTION_ALERT
    if text.startswith("prerequisite"):
        return SECTION_PREREQUISITES
    if re.match(r"remediation steps?\b", text):
        return SECTION_REMEDIATION
    return None


# Sections of the organisation's example and template that this IRP must NOT contain, however the model writes them
# (a heading of any level, a bold line, or a "Label:" line).
EXTRA_SECTIONS = frozenset({
    "testing scenarios", "overview", "alert properties", "remediation overview", "investigation steps", "rca & mitigation", "rca and mitigation",
    "example story submissions", "references", "alert enhancement", "lessons learned", "post-incident analysis", "post incident analysis",
    "authoring checklist", "irp authoring checklist",
})
_LABEL = re.compile(r"^\s*(?:#{1,6}\s+)?(?:\*\*|__)?\s*([A-Za-z][A-Za-z0-9 &/()\-]{1,70}?)\s*:?\s*(?:\*\*|__)?\s*:?\s*$")


def is_extra_section_label(line: str) -> bool:
    """True for a line that only names one of the unwanted sections: '#### **Post-Incident Analysis (Optional):**', '**Lessons learned**', 'References:'."""
    match = _LABEL.match(line)
    if not match:
        return False
    name = re.sub(r"\(.*?\)", "", _plain(match.group(1))).strip()
    return section_key(name) is None and name in EXTRA_SECTIONS


def _cut_at_extra_label(body: list[str]) -> list[str]:
    """The body up to the first line that starts an unwanted section (lines inside code fences are never taken for labels)."""
    in_fence = False
    for index, line in enumerate(body):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and is_extra_section_label(line):
            return body[:index]
    return body


def _headings_as_bold(body: list[str]) -> list[str]:
    """A sub-heading inside Prerequisites would read as one more section: keep its text as a bold line (lines inside code fences are left alone)."""
    out: list[str] = []
    in_fence = False
    for line in body:
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        out.append(f"**{match.group(2).strip('* ')}**" if match else line)
    return out


def _first_table(body: list[str]) -> list[str] | None:
    start = next((i for i, line in enumerate(body) if line.lstrip().startswith("|")), None)
    if start is None:
        return None
    end = start
    while end < len(body) and body[end].lstrip().startswith("|"):
        end += 1
    return body[start:end]


def extract_skeleton(example: str | None, limit: int = MAX_EXAMPLE_CHARS) -> tuple[str, bool]:
    """The part of the uploaded example that defines the output: its start through the end of its Remediation Steps section.
    The sections after that are not wanted and would only tempt the model to copy them. Returns (text, was it cut at `limit`)."""
    text = (example or "").strip()
    lines = text.splitlines()
    heads = _headings(lines)
    start = next((i for i, _level, title in heads if section_key(title) == SECTION_REMEDIATION), None)
    if start is not None:
        end = next((i for i, _level, _title in heads if i > start), len(lines))
        text = "\n".join(lines[:end]).strip()
    return text[:limit], len(text) > limit


def _section_body(example: str | None, wanted: str) -> list[str]:
    lines = (example or "").splitlines()
    heads = _headings(lines)
    start = next((i for i, _level, title in heads if section_key(title) == wanted), None)
    if start is None:
        return []
    end = next((i for i, _level, _title in heads if i > start), len(lines))
    return lines[start + 1:end]


def alert_detail_labels(example: str | None) -> list[str]:
    """The row labels of the Alert Details table of an IRP example, in order ('Alert', 'Description', ...); empty when there is none."""
    table = _first_table(_section_body(example, SECTION_ALERT))
    labels = []
    for line in table or []:
        cells = split_table_row(line)
        label = re.sub(r"[*_`]", "", cells[0]).strip() if cells else ""
        if label and not _DIVIDER_CELL.match(label):
            labels.append(label)
    return labels


def remediation_excerpt(example: str | None, limit: int) -> str:
    """The Remediation Steps section of an IRP example: the style the rows of a new IRP should have."""
    return "\n".join(_section_body(example, SECTION_REMEDIATION)).strip()[:limit]


def build_user_prompt(data: dict[str, Any], example_skeleton: str, template: str) -> str:
    """The alert's facts, the example to mirror, and the template as writing guidelines. Tags (not code fences) delimit the uploads,
    because an uploaded document may itself contain code fences."""
    parts = [
        "### ALERT METADATA:",
        f"- Alert Name: {data['alert_name']}",
        f"- Severity: {data['severity']}",
    ]
    if data.get("cvrd"):  # no longer asked for on the page, but still accepted from API callers
        parts.append(f"- CVRD / Alert ID: {data['cvrd']}")
    if data.get("target_resource") and data["target_resource"] != DEFAULT_TARGET_RESOURCE:
        parts.append(f"- Target Resource / Service: {data['target_resource']}")
    parts += [
        f"- Trigger Condition: {data['trigger_condition']}",
        f"- Owning Team: {data['owning_team']}",
        f"- Environment: {data['environment']}",
    ]
    if data["alert_output_columns"]:
        parts.append(f"\n### ALERT OUTPUT COLUMNS:\n{data['alert_output_columns']}")
    if data["alert_details"]:
        parts.append(f"\n### ALERT DETAILS / REPORT INFO:\n{data['alert_details']}")
    if data["arm_template_context"]:
        parts.append(f"\n### ARM TEMPLATE / INFRASTRUCTURE CONTEXT:\n<arm_template>\n{data['arm_template_context'][:MAX_ARM_CHARS]}\n</arm_template>")
    if example_skeleton:
        parts.append("\n### IRP EXAMPLE (the skeleton to mirror exactly: same sections, same row labels, same style, same row pattern; "
                     "write the content for THIS alert):\n<irp_example>\n" + example_skeleton + "\n</irp_example>")
    if template:
        parts.append("\n### WRITING GUIDELINES FROM THE ORGANISATION'S IRP TEMPLATE (about content quality only. Where anything here disagrees with the RULES "
                     "or the IRP example about sections, columns or column names, follow the RULES and the example):\n<irp_template>\n"
                     + template[:MAX_TEMPLATE_CHARS] + "\n</irp_template>")
    if data["additional_notes"]:
        parts.append(f"\n### ADDITIONAL NOTES:\n{data['additional_notes']}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------------------------------------------------
# What comes back: enforce the skeleton
# ---------------------------------------------------------------------------------------------------------------------

_DIVIDER_CELL = re.compile(r"^:?-{2,}:?$")
_RAW_PIPE = re.compile(r"(?<!\\)\|")


def split_table_row(row: str) -> list[str]:
    """The cells of one Markdown table row. Pipes inside backticks, inside <pre>/<code> and escaped as \\| do not split a cell."""
    text = row.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    lowered = text.lower()
    cells: list[str] = []
    current: list[str] = []
    in_code = in_pre = False
    index = 0
    while index < len(text):
        char = text[index]
        if lowered.startswith(("<pre", "<code"), index):
            in_pre = True
        elif lowered.startswith(("</pre>", "</code>"), index):
            in_pre = False
        if char == "\\" and text[index + 1:index + 2] == "|":
            current.append("\\|")
            index += 2
            continue
        if char == "`":
            in_code = not in_code
            current.append(char)
        elif char == "|" and not in_code and not in_pre:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _is_divider(cells: list[str]) -> bool:
    return bool(cells) and all(_DIVIDER_CELL.match(cell.strip()) for cell in cells)


def _looks_like_column_names(cells: list[str]) -> bool:
    """A row that is only the column names ('STEPS | ACTION | ADDITIONAL COMMENTS'), not a step that happens to mention an action."""
    return len(cells) >= 2 and _plain(cells[0]) in ("step", "steps") and _plain(cells[1]) in ("action", "actions", "command", "commands")


def _roles(header: list[str]) -> list[str]:
    roles = []
    for cell in header:
        name = _plain(cell)
        if "action" in name or "command" in name or "remediation" in name:
            roles.append("actions")
        elif "step" in name:
            roles.append("steps")
        else:
            roles.append("info")
    if "steps" not in roles or "actions" not in roles:  # names we do not recognise: go by position
        roles = ["steps", "actions"] + ["info"] * max(0, len(header) - 2)
    return roles


def _normalize_table(block: list[str]) -> list[str]:
    """One table, whatever its shape, as the 3-column Remediation table: names from the header decide which model column is which
    (steps, actions, everything else -> additional info), extra cells caused by unescaped pipes are folded back into the actions cell."""
    rows = [split_table_row(line) for line in block]
    divider = next((i for i, cells in enumerate(rows) if _is_divider(cells)), None)
    header: list[str] | None = None
    body_start = 0
    if divider is not None:
        header = rows[divider - 1] if divider > 0 else None
        body_start = divider + 1
    if header is not None and not any(header):  # a blank header row (an export artefact): the real names may be the first body row
        first = next((cells for cells in rows[body_start:] if not _is_divider(cells)), None)
        header = first if first and _looks_like_column_names(first) else None
    body = [cells for cells in rows[body_start:] if any(cells) and not _is_divider(cells) and cells != header and not _looks_like_column_names(cells)]
    names = header or ["steps", "actions", "info"]
    roles = _roles(names) if header else ["steps", "actions", "info"]
    names = names + [""] * (len(roles) - len(names))  # a one-column header still gets the two roles every table needs
    width = len(roles)
    action_at = roles.index("actions")
    info_titles = [re.sub(r"[*_]", "", name).strip().title() for name, role in zip(names, roles, strict=True) if role == "info"]

    out = [REMEDIATION_HEADER, REMEDIATION_DIVIDER]
    for cells in body:
        if len(cells) > width:  # a pipe inside a query split the actions cell
            extra = len(cells) - width
            cells = cells[:action_at] + [" \\| ".join(cells[action_at:action_at + extra + 1])] + cells[action_at + extra + 1:]
        cells = cells + [""] * (width - len(cells))
        steps = "<br>".join(c for c, r in zip(cells, roles, strict=True) if r == "steps" and c)
        actions = "<br>".join(c for c, r in zip(cells, roles, strict=True) if r == "actions" and c)
        info_cells = [c for c, r in zip(cells, roles, strict=True) if r == "info"]
        if len(info_cells) > 1:  # e.g. "Expected outcome" and "Additional comments": keep both, labelled
            info = "<br>".join(f"**{title}:** {c}" for title, c in zip(info_titles, info_cells, strict=True) if c)
        else:
            info = "<br>".join(c for c in info_cells if c)
        # GitHub-flavoured Markdown and the Azure DevOps wiki split a table cell at every unescaped pipe, even inside `code` or <pre>,
        # so a KQL query like `AzureDiagnostics | where ...` would turn one cell into several columns there.
        steps, actions, info = (_RAW_PIPE.sub(r"\\|", cell) for cell in (steps, actions, info))
        out.append(f"| {steps} | {actions} | {info} |")
    return out


def _unwrap_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) >= 2 and _FENCE.match(lines[0]) and lines[-1].strip() in ("```", "~~~"):
        return "\n".join(lines[1:-1])
    return text


def normalize_irp_markdown(markdown: str | None, alert_name: str) -> tuple[str, list[str]]:
    """Cut whatever the model returned down to the three sections and a 3-column Remediation table.
    Returns (markdown, problems), where problems says what could not be repaired (for example a missing table)."""
    text = _unwrap_fence((markdown or "").strip())
    if not text:
        return "", ["The generator returned no text."]
    lines = text.splitlines()
    heads = _headings(lines)
    sections: dict[str, list[str]] = {}
    for position, (index, level, title) in enumerate(heads):
        key = section_key(title)
        if not key or key in sections:
            continue
        end = len(lines)
        for later_index, later_level, later_title in heads[position + 1:]:
            if section_key(later_title) or later_level <= level + 1:  # a deeper sub-heading (two levels down) stays inside the section
                end = later_index
                break
        sections[key] = lines[index + 1:end]

    problems = [f"The generator did not return the '{key}' section." for key in (SECTION_ALERT, SECTION_REMEDIATION) if key not in sections]
    out = [f"# {alert_name.strip() or 'Incident Response Plan'}", ""]
    for key in SECTIONS:
        body = _cut_at_extra_label(list(sections.get(key, [])))
        table = _first_table(body) if key in (SECTION_ALERT, SECTION_REMEDIATION) else None
        if table is not None:  # these two sections are one table each: nothing before or after it (a note, a second table) is kept
            body = _normalize_table(table) if key == SECTION_REMEDIATION else table
        elif key == SECTION_REMEDIATION and key in sections:
            problems.append("The Remediation Steps section has no table.")
        elif key == SECTION_PREREQUISITES:
            body = _headings_as_bold(body)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        out.extend([f"# {key}", "", *body, ""])
    return "\n".join(out).strip() + "\n", problems
