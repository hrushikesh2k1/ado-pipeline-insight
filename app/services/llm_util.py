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
