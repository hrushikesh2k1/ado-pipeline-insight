"""JSON files in a pull request (settings, test collections, data): where a change sits in the file, and what can be read off it with certainty.

A JSON diff is a few lines of `"key": "value"` in the middle of thousands. On their own they say nothing about which request, setting or
object they belong to. So the reviewer is also given the path of each changed part, for example
`item[3] "Orders" > item[1] "Get one order" > request`, and exact checks are made in code (see pr_static): a file that stopped being
valid JSON, a key written twice in one object (a JSON reader keeps only the last), and a secret written in the file.
Comments and trailing commas are tolerated: tsconfig, VS Code settings and ARM templates use them.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.alert_facts import strip_json_comments

JSON_LANGUAGE = "JSON"  # a .json file that is not an ARM template
JSON_LINE_WIDTH = 4000  # a request body or a value can be one long line; the reviewer must see it
MAX_OUTLINE_LINES = 40
MAX_NAME_CHARS = 60
OUTLINE_GAP = 3  # changed lines this close to each other are one changed part

# a string, a comment, a structural character or a line break
_TOKENS = re.compile(r'"(?:[^"\\\n]|\\.)*"|//[^\n]*|/\*.*?\*/|[{}\[\]:,\n]', re.DOTALL)


class _Frame:
    __slots__ = ("kind", "label", "index", "pending", "name", "expect_key", "seen")

    def __init__(self, kind: str, label: str):
        self.kind, self.label, self.index, self.pending, self.name = kind, label, 0, None, None
        self.expect_key = kind == "obj"
        self.seen: dict[str, int] = {}


def _decoded(token: str) -> str:
    try:
        return str(json.loads(token))
    except ValueError:
        return token[1:-1]


class JsonMap:
    """Where things are in a JSON text: the object each line is in, and the keys written twice in one object. Tolerant of comments, trailing commas and
    broken files (it reads what it can; it never raises)."""

    def __init__(self, text: str):
        self.snapshots: dict[int, tuple[_Frame, ...]] = {1: ()}
        self.duplicates: list[tuple[str, int, int]] = []  # (key, line of the first, line of the second)
        stack: list[_Frame] = []
        line = 1
        for match in _TOKENS.finditer(text):
            token = match.group(0)
            if token == "\n":
                line += 1
                self.snapshots[line] = tuple(stack)
            elif token[0] == '"':
                frame = stack[-1] if stack else None
                if frame is None or frame.kind != "obj":
                    continue
                if frame.expect_key:
                    key = _decoded(token)
                    frame.expect_key, frame.pending = False, key
                    if key in frame.seen:
                        self.duplicates.append((key, frame.seen[key], line))
                    else:
                        frame.seen[key] = line
                elif frame.pending == "name":
                    frame.name = _decoded(token)
            elif token[0] == "/":
                for _ in range(token.count("\n")):
                    line += 1
                    self.snapshots[line] = tuple(stack)
            elif token in "{[":
                parent = stack[-1] if stack else None
                if parent is None:
                    label = ""
                elif parent.kind == "arr":
                    label = f"{parent.label}[{parent.index}]"
                else:
                    label = parent.pending or ""
                stack.append(_Frame("obj" if token == "{" else "arr", label))
            elif token == ",":
                if stack:
                    frame = stack[-1]
                    if frame.kind == "obj":
                        frame.expect_key, frame.pending = True, None
                    else:
                        frame.index += 1
            elif token in "}]":
                if stack:
                    stack.pop()

    def where(self, line: int) -> str:
        """The path of the object a line is in: `item[3] "Orders" > item[1] "Get one order" > request`."""
        frames = self.snapshots.get(line) or ()
        parts = []
        for frame in frames:
            if frame.kind == "obj" and frame.label:
                name = f' "{frame.name[:MAX_NAME_CHARS]}"' if frame.name else ""
                parts.append(frame.label + name)
        if frames and frames[-1].kind == "arr" and frames[-1].label:
            parts.append(frames[-1].label + "[]")
        return " > ".join(parts) or "the top level"


def outline(text: str, changed: set[int]) -> str:
    """One line for each changed part of the file: its lines and where in the JSON structure it is. Empty when nothing changed."""
    if not changed:
        return ""
    where = JsonMap(text)
    ordered = sorted(changed)
    parts: list[list[int]] = [[ordered[0], ordered[0]]]
    for number in ordered[1:]:
        if number - parts[-1][1] <= OUTLINE_GAP:
            parts[-1][1] = number
        else:
            parts.append([number, number])
    lines = [f"lines {a}-{b}: {where.where(a)}" if b > a else f"line {a}: {where.where(a)}" for a, b in parts[:MAX_OUTLINE_LINES]]
    if len(parts) > MAX_OUTLINE_LINES:
        lines.append(f"... and {len(parts) - MAX_OUTLINE_LINES} more changed parts")
    return "\n".join(lines)


# ---------------------------------------------------------------- validity

def parse(text: str | None) -> tuple[Any, json.JSONDecodeError | None]:
    """(the parsed value, None), or (None, the error). Comments and trailing commas do not count as errors."""
    body = (text or "").lstrip("﻿")
    body = re.sub(r",(\s*[}\]])", r"\1", strip_json_comments(body))
    try:
        return json.loads(body), None
    except json.JSONDecodeError as exc:
        return None, exc
    except (RecursionError, ValueError):
        return None, json.JSONDecodeError("the file is nested too deeply", body, 0)


# ---------------------------------------------------------------- secrets

_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")
_AUTH_HEADER = re.compile(r"\b(?:Bearer|Basic)\s+((?![{$<%#\[])[A-Za-z0-9._~+/=-]{16,})")
_CONNECTION_SECRET = re.compile(r"\b(?:AccountKey|SharedAccessKey|Password|Pwd)\s*=\s*([^;\"\s]{6,})", re.IGNORECASE)
_KEY_VALUE = re.compile(r'"([A-Za-z0-9_.\- ]{1,60})"\s*:\s*"((?:[^"\\]|\\.)*)"')
# the key says the value is a secret; the value is not a variable, an expression or an obvious placeholder
_SECRET_KEYS = {"password", "passwd", "pwd", "secret", "clientsecret", "apikey", "accesskey", "accesstoken", "authtoken", "bearertoken", "privatekey", "accountkey",
                "sharedaccesskey", "sastoken", "token"}
_PLACEHOLDER = re.compile(r"^\s*(?:\{\{.*\}\}|\$\{.*\}|\$\(.*\)|%[^%]+%|<[^>]*>|#\{.*\}|\[(?:parameters|variables|concat)\(.*|@Microsoft\.KeyVault.*|\*+|x{3,}|\.{3,}|"
                          r"(?:changeme|change[-_ ]me|your[-_ ].*|replace[-_ ].*|todo|redacted|dummy|example|none|null|secret|password|token))\s*$", re.IGNORECASE)


def mask(line: str, secret: str) -> str:
    """The line on one row with the secret cut to its first four characters: a review must not repeat a secret."""
    return " ".join(line.split()).replace(secret, secret[:4] + "…", 1) if secret else " ".join(line.split())


def secrets_in(line: str) -> list[tuple[str, str, str]]:
    """(what it is, the secret, how serious) for each secret written in a line of a JSON file. Variables, expressions and placeholders are not secrets."""
    found: list[tuple[str, str, str]] = []
    for match in _JWT.finditer(line):
        found.append(("a JSON Web Token (an access token)", match.group(0), "warning"))
    if _PRIVATE_KEY.search(line):
        found.append(("a private key", "-----BEGIN", "warning"))
    for match in _AUTH_HEADER.finditer(line):
        if not _JWT.search(match.group(1)):
            found.append(("an authorization header value", match.group(1), "warning"))
    for match in _CONNECTION_SECRET.finditer(line):
        if not _PLACEHOLDER.match(match.group(1)):
            found.append(("a password or account key in a connection string", match.group(1), "warning"))
    for key, value in _KEY_VALUE.findall(line):
        normalized = re.sub(r"[^a-z]", "", key.lower())
        if normalized in _SECRET_KEYS and len(value) >= 8 and not _PLACEHOLDER.match(value) and not any(value in s for _, s, _ in found):
            found.append((f'the value of "{key}"', value, "suggestion"))
    return found

