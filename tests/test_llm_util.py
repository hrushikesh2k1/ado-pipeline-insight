"""The chat helpers: a model that refuses a temperature is asked again without one; anything else is not hidden."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm_util import DeploymentClient, chat_json, chat_json_with_tools


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


TEMPERATURE_ONLY_DEFAULT = Refused("Unsupported value: 'temperature' does not support 0.0 with this model. Only the default (1) value is supported.", 400)
TOOLS_NEED_NO_REASONING = Refused("Function tools with reasoning_effort are not supported for the-model in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'.", 400)
TOOLS = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}}}]


class Recording:
    """An SDK client that refuses what `refuse(request)` says it refuses (with the 400 it returns) and records every request it receives."""

    def __init__(self, refuse):
        self.refuse, self.requests, self.deployment = refuse, [], "the-model"
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))

    def create(self, **request):
        self.requests.append(request)
        error = self.refuse(request)
        if error is not None:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}', tool_calls=None))])


def picky(request):
    """A model that takes only its default temperature, and function tools only with reasoning turned off."""
    if "temperature" in request:
        return TEMPERATURE_ONLY_DEFAULT
    if request.get("tools") and request.get("reasoning_effort") != "none":
        return TOOLS_NEED_NO_REASONING
    return None


class TestAModelThatRefusesSettings:
    def test_a_temperature_it_refuses_is_dropped_and_remembered(self):
        inner = Recording(lambda request: TEMPERATURE_ONLY_DEFAULT if "temperature" in request else None)
        client = DeploymentClient(inner)
        assert chat_json(client, "system", "one") == {"ok": True}
        assert chat_json(client, "system", "two") == {"ok": True}
        assert ["temperature" in r for r in inner.requests] == [True, False, False]  # one failed call, then never again
        assert client.deployment == "the-model" and inner.requests[1]["model"] == "the-model"

    def test_tools_are_sent_with_reasoning_off_once_the_model_has_said_it_needs_that(self):
        inner = Recording(picky)
        client = DeploymentClient(inner)
        assert chat_json_with_tools(client, "system", "user", TOOLS, lambda name, args: "") == {"ok": True}
        assert chat_json_with_tools(client, "system", "user", TOOLS, lambda name, args: "") == {"ok": True}
        sent = [(("temperature" in r), r.get("reasoning_effort"), bool(r.get("tools"))) for r in inner.requests]
        assert sent == [(True, None, True), (False, None, True), (False, "none", True), (False, "none", True)]
        assert inner.requests[-1]["tools"] == TOOLS

    def test_a_request_without_tools_keeps_its_reasoning(self):
        inner = Recording(picky)
        client = DeploymentClient(inner)
        chat_json_with_tools(client, "system", "user", TOOLS, lambda name, args: "")
        chat_json(client, "system", "a plain request")
        assert "reasoning_effort" not in inner.requests[-1] and "tools" not in inner.requests[-1]

    def test_a_model_that_takes_everything_is_asked_once_with_everything(self):
        inner = Recording(lambda request: None)
        client = DeploymentClient(inner)
        chat_json_with_tools(client, "system", "user", TOOLS, lambda name, args: "", temperature=0.2)
        assert len(inner.requests) == 1 and inner.requests[0]["temperature"] == 0.2 and "reasoning_effort" not in inner.requests[0]

    @pytest.mark.parametrize("error", [Refused("content filter triggered", 400), Refused("Unsupported value: 'response_format' is not allowed", 400), Refused("busy", 429), Refused("down", 503), ValueError("temperature")])
    def test_any_other_failure_is_not_hidden_and_not_repeated(self, error):
        inner = Recording(lambda request: error)
        with pytest.raises(type(error)):
            chat_json(DeploymentClient(inner), "system", "user")
        assert len(inner.requests) == 1

    def test_a_model_that_keeps_refusing_is_not_asked_without_end(self):
        inner = Recording(lambda request: TEMPERATURE_ONLY_DEFAULT)
        with pytest.raises(Refused):
            chat_json(DeploymentClient(inner), "system", "user")
        assert len(inner.requests) <= 4

    def test_each_deployment_learns_for_itself(self):
        picky_model, easy_model = DeploymentClient(Recording(picky)), DeploymentClient(Recording(lambda request: None))
        chat_json(picky_model, "system", "one")
        chat_json(easy_model, "system", "two", temperature=0.3)
        assert picky_model.no_temperature and not easy_model.no_temperature and easy_model.inner.requests[0]["temperature"] == 0.3


class TestRequestsInFlightTogether:
    """Files are reviewed several at a time: all of them can be refused for the same setting before any answer comes back."""

    def test_a_request_refused_after_another_one_learned_the_same_thing_is_asked_again(self):
        client = DeploymentClient(Recording(lambda request: TEMPERATURE_ONLY_DEFAULT if "temperature" in request else None))
        client.no_temperature = True  # learned from a sibling request while this one was in flight
        sent_with_it = {"messages": [], "temperature": 0.1}
        client.inner.requests.clear()
        assert client.client.chat.completions.create(**{**sent_with_it, "model": "the-model"}) is not None  # the flag removes it up front
        client.no_temperature = False
        original = client.inner.create

        def refused_after_the_flag_was_set(**request):
            client.no_temperature = True  # the sibling request finishes learning while this one is being refused
            return original(**request)

        client.inner.client.chat.completions.create = refused_after_the_flag_was_set
        assert client.client.chat.completions.create(**{**sent_with_it, "model": "the-model"}) is not None
        assert ["temperature" in r for r in client.inner.requests] == [False, True, False]

    def test_the_same_for_tools(self):
        client = DeploymentClient(Recording(picky))
        original = client.inner.create

        def refused_after_the_flag_was_set(**request):
            client.tools_without_reasoning = True
            return original(**request)

        client.inner.client.chat.completions.create = refused_after_the_flag_was_set
        assert chat_json_with_tools(client, "system", "user", TOOLS, lambda name, args: "", temperature=0) == {"ok": True}
        assert [r.get("reasoning_effort") for r in client.inner.requests if r.get("tools")][-1] == "none"
