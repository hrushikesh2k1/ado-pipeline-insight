"""Small helpers shared by the features that ask the model for JSON."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


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


def chat_json(client: Any, system: str, user: str, temperature: float = 0.0) -> dict[str, Any]:
    """One chat call that must answer with a JSON object."""
    response = client.client.chat.completions.create(
        model=client.deployment,
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
        response = client.client.chat.completions.create(model=client.deployment, messages=messages, temperature=temperature, tools=tools, **extra)
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
