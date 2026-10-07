"""Small helpers shared by the features that ask the model for JSON."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger(__name__)

_UNAVAILABLE = {401: "the key was refused", 403: "access was refused", 404: "the deployment was not found", 408: "it timed out", 429: "it is busy (rate limit)"}


def model_unavailable(exc: Exception) -> str | None:
    """Why a deployment cannot answer right now (not found, no access, busy, down, unreachable), or None for any other error: a bad request is our own
    mistake and must not be hidden by asking another model."""
    status = getattr(exc, "status_code", None)
    if status in _UNAVAILABLE:
        return _UNAVAILABLE[status]
    if isinstance(status, int) and status >= 500:
        return f"it answered HTTP {status}"
    name = type(exc).__name__
    return "it could not be reached" if "Timeout" in name or "Connection" in name else None


class DeploymentClient:
    """One deployment as a model client that learns what the model does not accept and stops sending it. Some newer models answer 400 to a temperature other
    than their own default, and to function tools unless reasoning is turned off (Microsoft's documented workaround is reasoning_effort "none" for the requests
    that send tools). The request is sent again without the setting, and every later request is made that way from the start, so there is one failed call at most."""

    def __init__(self, inner: Any):
        self.inner, self.deployment = inner, inner.deployment
        self.no_temperature = False
        self.tools_without_reasoning = False
        outer = self

        class Completions:
            @staticmethod
            def create(**request: Any) -> Any:
                request = dict(request)
                for _ in range(3):
                    if outer.no_temperature:
                        request.pop("temperature", None)
                    if request.get("tools") and outer.tools_without_reasoning:
                        request.setdefault("reasoning_effort", "none")
                    try:
                        return outer.inner.client.chat.completions.create(**request)
                    except Exception as exc:
                        said = str(exc).lower()
                        if getattr(exc, "status_code", None) != 400:
                            raise
                        # a request that was already in flight when another one learned the same thing is asked again too: it is the request that was refused
                        if "temperature" in said and "temperature" in request:
                            outer.no_temperature = True
                        elif "function tools" in said and "reasoning_effort" in said and request.get("tools") and request.get("reasoning_effort") != "none":
                            outer.tools_without_reasoning = True
                        else:
                            raise
                        logger.info("The deployment %s does not take that setting: asking again without it", outer.deployment)
                return outer.inner.client.chat.completions.create(**request)

        self.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


class WithBackup:
    """A model client that asks `primary` and, once its deployment cannot answer, carries on with `backup` for the rest of the review.
    The switch is for good (a review is never half one model and half the other by chance after a single slow answer) and `fell_back_because` says why."""

    def __init__(self, primary: Any, backup: Any):
        self.primary, self.backup = primary, backup
        self.fell_back_because: str | None = None
        self._lock = threading.Lock()
        outer = self

        class Completions:
            @staticmethod
            def create(**request: Any) -> Any:
                if outer.fell_back_because is None:
                    try:
                        return outer.primary.client.chat.completions.create(**{**request, "model": outer.primary.deployment})
                    except Exception as exc:
                        why = model_unavailable(exc)
                        if why is None:
                            raise
                        with outer._lock:
                            if outer.fell_back_because is None:
                                outer.fell_back_because = why
                                logger.warning("The deployment %s cannot answer (%s): the review goes on with %s", outer.primary.deployment, why, outer.backup.deployment)
                return outer.backup.client.chat.completions.create(**{**request, "model": outer.backup.deployment})

        self.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    @property
    def deployment(self) -> str:
        """The deployment that answers now."""
        return self.backup.deployment if self.fell_back_because else self.primary.deployment


def parse_json_object(text: str | None) -> dict[str, Any]:
    """The JSON object in a model answer, whether it is bare, fenced or surrounded by chatter."""
    body = (text or "").strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body)
    try:
        value = json.loads(body)
    except ValueError:
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("The AI did not return JSON.") from None
        value = json.loads(body[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("The AI did not return a JSON object.")
    return value


def _create(client: Any, **request: Any) -> Any:
    """One chat completion. Some newer models only run at their own default temperature and answer 400 when one is sent: ask again without it."""
    try:
        return client.client.chat.completions.create(model=client.deployment, **request)
    except Exception as exc:
        rejected = getattr(exc, "status_code", None) == 400 and "temperature" in str(exc).lower()
        if not rejected or "temperature" not in request:
            raise
        logger.info("The model does not take a temperature, asking again without it")
        return client.client.chat.completions.create(model=client.deployment, **{k: v for k, v in request.items() if k != "temperature"})


def chat_json(client: Any, system: str, user: str, temperature: float = 0.0) -> dict[str, Any]:
    """One chat call that must answer with a JSON object."""
    response = _create(
        client,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    return parse_json_object(response.choices[0].message.content)


def chat_json_with_tools(client: Any, system: str, user: str, tools: list[dict[str, Any]], run_tool: Callable[[str, dict[str, Any]], str],
                         max_turns: int = 6, temperature: float = 0.0) -> dict[str, Any]:
    """A chat that may call tools before it answers with a JSON object. The last turn takes no more tool calls, so there is always an answer."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for turn in range(max_turns):
        final = turn == max_turns - 1
        extra: dict[str, Any] = {"tool_choice": "none", "response_format": {"type": "json_object"}} if final else {}
        response = _create(client, messages=messages, temperature=temperature, tools=tools, **extra)
        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            return parse_json_object(message.content)
        messages.append({"role": "assistant", "content": message.content or "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}} for c in calls]})
        for call in calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except ValueError:
                arguments = {}
            messages.append({"role": "tool", "tool_call_id": call.id, "content": run_tool(call.function.name, arguments if isinstance(arguments, dict) else {})})
    raise ValueError("The AI gave no answer.")


def with_retry(call: Callable[[], Any], attempts: int = 2, delay: float = 1.5) -> Any:
    """Run a call, once more after a short pause if it fails."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if attempt == attempts:
                raise
            logger.info("AI call failed (%s), retrying", type(exc).__name__)
            time.sleep(delay)
