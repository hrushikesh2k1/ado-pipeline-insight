"""Retries only help intermittent failures: classify the error text captured from a failed step."""
import pytest

from app.services.failure_kind import classify_failure, first_error_line


@pytest.mark.parametrize("text", [
    "dial tcp 13.77.233.102:443: i/o timeout",
    "Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress",
    "curl: (56) Recv failure: Connection reset by peer",
    "HTTP 503 Service Unavailable",
    "Too Many Requests (429)",
    "Get \"https://registry\": context deadline exceeded",
    "Could not resolve host: dev.azure.com",
    "The agent did not connect within the timeout period",
])
def test_transient_causes(text):
    assert classify_failure(text) == "transient"


@pytest.mark.parametrize("text", [
    "Error: chart \"mdc\" not found in repository",
    "permission denied while trying to connect to the Docker daemon",
    "SyntaxError: invalid syntax",
    "2 tests failed",
    "401 Unauthorized",
])
def test_persistent_causes(text):
    assert classify_failure(text) == "persistent"


@pytest.mark.parametrize("text", [None, "", "   \n ", "Process completed with exit code 1.", "##[error]Bash exited with code '1'."])
def test_generic_or_missing_text_is_unknown_never_a_guess_for_retrying(text):
    assert classify_failure(text) == "unknown"


def test_transient_wins_when_both_signals_are_present():
    assert classify_failure("not found: connection reset by peer") == "transient"


def test_first_error_line_is_trimmed_and_skips_blanks():
    assert first_error_line("\n\n  boom happened  \nsecond") == "boom happened"
    assert first_error_line(None) == "" and len(first_error_line("x" * 500)) == 200
