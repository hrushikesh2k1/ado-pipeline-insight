"""Strict validation for values that end up in Azure DevOps URLs or HTTP headers."""
from __future__ import annotations

import re

ORGANIZATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
PAT_RE = re.compile(r"^[\x21-\x7e]{1,512}$")
_PROJECT_FORBIDDEN = re.compile(r'[\\/:*?"<>|#%&+$@;=,\x00-\x1f\x7f]')


def validate_organization(value: str) -> str:
    value = (value or "").strip()
    if not ORGANIZATION_RE.fullmatch(value):
        raise ValueError("organization must be 1-64 letters, digits or hyphens and start with a letter or digit.")
    return value


def validate_project(value: str) -> str:
    value = (value or "").strip()
    if (
        not 1 <= len(value) <= 256
        or _PROJECT_FORBIDDEN.search(value)
        or ".." in value
        or value.endswith(".")
    ):
        raise ValueError("project contains characters that are not allowed in an Azure DevOps project name.")
    return value


def validate_pat(value: str) -> str:
    if not PAT_RE.fullmatch(value or ""):
        raise ValueError("pat must be 1-512 printable ASCII characters without spaces.")
    return value
