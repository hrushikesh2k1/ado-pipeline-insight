"""Is a step failure likely transient (worth retrying) or a real fault (fix the cause)?

Retries only help when the failure is intermittent. A deterministic error repeats every time, and a retry then just makes
a failing run slower. The classification looks at the error text captured from the failed step's log; with no usable
text the answer is "unknown", never a guess in favour of retrying.
"""
from __future__ import annotations

import re

from app.services.root_causes import identify_cause

TRANSIENT = re.compile(
    r"time[d ]?-?out|timeout|timed out|i/o timeout|context deadline exceeded|connection (reset|refused|closed|aborted)|"
    r"econnreset|econnrefused|etimedout|eai_again|temporar(y|ily)|try again|service unavailable|bad gateway|gateway time-?out|"
    r"\b(429|502|503|504)\b|too many requests|throttl|rate limit|socket hang up|tls handshake|network is unreachable|"
    r"no route to host|unable to connect|could not resolve host|name resolution|another operation .{0,40} in progress|"
    r"unexpected eof|broken pipe|agent .{0,40}(lost|offline|did not connect)",
    re.IGNORECASE,
)
PERSISTENT = re.compile(
    r"not found|no such file|does not exist|cannot find|permission denied|access denied|unauthori[sz]ed|forbidden|"
    r"authentication failed|invalid|not valid|validation failed|expected a value of type|should satisfy the constraint|"
    r"authorizationfailed|does not have authorization|power state|operationnotallowed|resourcenotfound|syntax error|parse error|"
    r"failed to parse|undefined|missing required|unknown (flag|option|command)|compilation error|cannot be resolved|"
    r"assertion|tests? failed|unresolved",
    re.IGNORECASE,
)
# Lines that appear in almost every failure and say nothing about the cause.
BOILERPLATE = re.compile(
    r"^(check out the troubleshooting guide|script failed with exit code|process completed with exit code|bash exited with code|"
    r"powershell exited with code|cmd\.exe exited with code|details:?$|for more details)",
    re.IGNORECASE,
)


def classify_failure(excerpt: str | None) -> str:
    """'transient', 'persistent' or 'unknown' for the error text captured from a failed step."""
    text = (excerpt or "").strip()
    if not text:
        return "unknown"
    if identify_cause(text):  # a recognised, specific cause is a real fault
        return "persistent"
    if TRANSIENT.search(text):
        return "transient"
    if PERSISTENT.search(text):
        return "persistent"
    return "unknown"


def best_error_line(excerpt: str | None, limit: int = 200) -> str:
    """The most informative line of the excerpt: boilerplate such as 'Script failed with exit code: 1' is skipped unless it is all there is."""
    segments = [seg.strip() for seg in re.split(r"##\[error\]|\r?\n", excerpt or "") if seg.strip()]
    informative = [seg for seg in segments if not BOILERPLATE.match(seg)]
    return (informative or segments or [""])[0][:limit]


first_error_line = best_error_line  # the earlier name, kept for callers that still use it


def is_generic(excerpt: str | None) -> bool:
    """True when the excerpt says nothing about the cause (empty, or only exit-code boilerplate)."""
    segments = [seg.strip() for seg in re.split(r"##\[error\]|\r?\n", excerpt or "") if seg.strip()]
    return all(BOILERPLATE.match(seg) for seg in segments)
