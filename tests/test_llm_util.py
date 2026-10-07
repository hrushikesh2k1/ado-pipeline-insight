"""The chat helpers: a model that refuses a temperature is asked again without one; anything else is not hidden."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm_util import chat_json, chat_json_with_tools


class Refused(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class FakeChat:
    """Stands in for client.client.chat.completions; fails with `error` on the first call when one is given."""

    def __init__(self, error: Exception | None = None, content: str = '{"ok": true}'):
        self.error, self.content, self.requests = error, content, []
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))
        self.deployment = "strong"

    def create(self, **request):
        self.requests.append(request)
        if self.error is not None and len(self.requests) == 1:
            raise self.error
        message = SimpleNamespace(content=self.content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


TEMPERATURE_REFUSED = Refused("Unsupported value: 'temperature' does not support 0.0 with this model. Only the default (1) value is supported.", 400)


class TestTemperature:
    def test_a_model_that_refuses_a_temperature_is_asked_again_without_one(self):
        chat = FakeChat(TEMPERATURE_REFUSED)
        assert chat_json(chat, "system", "user") == {"ok": True}
        assert "temperature" in chat.requests[0] and "temperature" not in chat.requests[1]
        assert chat.requests[1]["model"] == "strong" and chat.requests[1]["response_format"] == {"type": "json_object"}

    def test_the_same_for_a_chat_that_may_call_tools(self):
        chat = FakeChat(TEMPERATURE_REFUSED)
        assert chat_json_with_tools(chat, "system", "user", [{"type": "function"}], lambda name, args: "") == {"ok": True}
        assert "temperature" not in chat.requests[1] and chat.requests[1]["tools"] == [{"type": "function"}]

    def test_a_model_that_takes_one_is_asked_once(self):
        chat = FakeChat()
        chat_json(chat, "system", "user", temperature=0.1)
        assert len(chat.requests) == 1 and chat.requests[0]["temperature"] == 0.1

    @pytest.mark.parametrize("error", [Refused("content filter triggered", 400), Refused("temperature is fine but the service is busy", 429), ValueError("temperature")])
    def test_any_other_failure_is_not_hidden(self, error):
        chat = FakeChat(error)
        with pytest.raises(type(error)):
            chat_json(chat, "system", "user")
        assert len(chat.requests) == 1
