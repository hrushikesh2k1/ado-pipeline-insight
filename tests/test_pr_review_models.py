"""Which model reviews a pull request: the standard one or the strong one, and the standard one finishing the review when the strong one cannot answer."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import create_app
from app.services import pr_review
from app.services.llm_util import WithBackup, chat_json, model_unavailable
from app.services.pr_review import AiUnavailable, PullRequestReviewService, effective_choice, get_model_client, model_info, review_models
from pr_support import FakeAdo, FakePrModel, finding


class Refused(Exception):
    def __init__(self, message: str = "refused", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# named like the SDK's errors, which carry no status code
APIConnectionError = type("APIConnectionError", (Exception,), {})
APITimeoutError = type("APITimeoutError", (Exception,), {})


class Deployment:
    """One deployment as a model client: answers `{"ok": true}`, or raises `error`; records the deployment name each request asked for."""

    def __init__(self, name: str, error: Exception | None = None):
        self.deployment, self.error, self.asked = name, error, []
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))

    def create(self, **request):
        self.asked.append(request["model"])
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content='{"ok": true}', tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def settings(**over):
    base = dict(azure_openai_endpoint="https://x.openai.azure.com", azure_openai_deployment="standard-mini", azure_openai_review_deployment="strong-sol",
                azure_openai_api_version="2024-02-01", azure_openai_api_key="k")
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def configured(monkeypatch):
    def use(**over):
        monkeypatch.setattr(pr_review, "get_settings", lambda: settings(**over))
        made = []
        monkeypatch.setattr(pr_review, "PipelineRecommendationClient", lambda endpoint, name, version, key: made.append(name) or Deployment(name))
        return made
    return use


class TestWhichModelsAreSetUp:
    def test_both_set_up_and_the_strong_one_is_the_default(self, configured):
        configured()
        assert review_models() == {"standard": "standard-mini", "strong": "strong-sol", "default": "strong"}

    @pytest.mark.parametrize("over,expected", [
        ({"azure_openai_review_deployment": ""}, {"standard": "standard-mini", "strong": None, "default": "standard"}),
        ({"azure_openai_review_deployment": "  "}, {"standard": "standard-mini", "strong": None, "default": "standard"}),
        ({"azure_openai_endpoint": ""}, {"standard": None, "strong": None, "default": "standard"}),
        ({"azure_openai_deployment": ""}, {"standard": None, "strong": "strong-sol", "default": "strong"}),
    ])
    def test_what_is_missing_is_none(self, configured, over, expected):
        configured(**over)
        assert review_models() == expected

    @pytest.mark.parametrize("asked,expected", [(None, "strong"), ("strong", "strong"), ("standard", "standard"), ("nonsense", "strong")])
    def test_the_choice_with_both(self, configured, asked, expected):
        configured()
        assert effective_choice(asked) == expected

    @pytest.mark.parametrize("asked", [None, "strong", "standard"])
    def test_without_a_strong_deployment_every_choice_is_the_standard_one(self, configured, asked):
        configured(azure_openai_review_deployment="")
        assert effective_choice(asked) == "standard"

    def test_with_only_a_strong_deployment_every_choice_is_the_strong_one(self, configured):
        configured(azure_openai_deployment="")
        assert effective_choice("standard") == "strong"


class TestTheClientForAReview:
    def test_the_strong_choice_is_the_strong_deployment_with_the_standard_one_behind_it(self, configured):
        configured()
        model = get_model_client("strong")
        assert isinstance(model, WithBackup) and (model.primary.deployment, model.backup.deployment) == ("strong-sol", "standard-mini")

    def test_no_choice_means_the_default(self, configured):
        configured()
        assert isinstance(get_model_client(), WithBackup)
        configured(azure_openai_review_deployment="")
        assert get_model_client().deployment == "standard-mini"

    def test_the_standard_choice_is_the_standard_deployment_alone(self, configured):
        made = configured()
        model = get_model_client("standard")
        assert not isinstance(model, WithBackup) and model.deployment == "standard-mini" and made == ["standard-mini"]

    def test_a_strong_deployment_with_nothing_behind_it_is_used_alone(self, configured):
        configured(azure_openai_deployment="")
        assert get_model_client("strong").deployment == "strong-sol"
        configured(azure_openai_deployment="strong-sol")  # the same deployment twice is not a backup
        assert not isinstance(get_model_client("strong"), WithBackup)

    def test_nothing_set_up_means_no_review(self, configured):
        configured(azure_openai_endpoint="")
        with pytest.raises(AiUnavailable, match="Nothing was reviewed"):
            get_model_client("strong")


class TestWhenTheStrongModelCannotAnswer:
    @pytest.mark.parametrize("error,why", [
        (Refused(status_code=404), "the deployment was not found"), (Refused(status_code=429), "it is busy (rate limit)"), (Refused(status_code=401), "the key was refused"),
        (Refused(status_code=403), "access was refused"), (Refused(status_code=408), "it timed out"), (Refused(status_code=503), "it answered HTTP 503"),
        (APIConnectionError("down"), "it could not be reached"), (APITimeoutError("slow"), "it could not be reached"),
    ])
    def test_the_standard_deployment_answers_and_the_reason_is_kept(self, error, why):
        strong, standard = Deployment("strong-sol", error), Deployment("standard-mini")
        model = WithBackup(strong, standard)
        assert chat_json(model, "system", "user") == {"ok": True}
        assert strong.asked == ["strong-sol"] and standard.asked == ["standard-mini"] and model.fell_back_because == why and model.deployment == "standard-mini"

    def test_the_switch_is_for_good(self):
        strong, standard = Deployment("strong-sol", Refused(status_code=429)), Deployment("standard-mini")
        model = WithBackup(strong, standard)
        chat_json(model, "system", "one")
        chat_json(model, "system", "two")
        assert strong.asked == ["strong-sol"] and standard.asked == ["standard-mini", "standard-mini"]

    def test_the_strong_deployment_answers_when_it_can(self):
        strong, standard = Deployment("strong-sol"), Deployment("standard-mini")
        model = WithBackup(strong, standard)
        chat_json(model, "system", "user")
        assert strong.asked == ["strong-sol"] and standard.asked == [] and model.fell_back_because is None and model.deployment == "strong-sol"

    @pytest.mark.parametrize("error", [Refused("content filter", status_code=400), Refused("bad", status_code=422), ValueError("nope"), Refused()])
    def test_our_own_mistakes_are_not_hidden_by_asking_another_model(self, error):
        strong, standard = Deployment("strong-sol", error), Deployment("standard-mini")
        model = WithBackup(strong, standard)
        with pytest.raises(type(error)):
            chat_json(model, "system", "user")
        assert standard.asked == [] and model.fell_back_because is None

    def test_a_standard_deployment_that_fails_too_fails_the_call(self):
        model = WithBackup(Deployment("strong-sol", Refused(status_code=404)), Deployment("standard-mini", Refused(status_code=500)))
        with pytest.raises(Refused):
            chat_json(model, "system", "user")

    @pytest.mark.parametrize("error,why", [(Refused(status_code=429), "it is busy (rate limit)"), (Refused(status_code=400), None), (ValueError("x"), None)])
    def test_what_counts_as_unavailable(self, error, why):
        assert model_unavailable(error) == why


class TestWhatTheReviewSays:
    def test_a_review_names_the_deployment(self):
        result = PullRequestReviewService(FakeAdo(), FakePrModel()).review("proj", "repo", 7)
        assert result["model"] == {"deployment": "fake", "fallback_deployment": None, "fallback_reason": None}
        assert not any("strong model" in note for note in result["notes"])

    def test_a_review_that_the_standard_model_finished_says_so(self):
        strong = Deployment("strong-sol", Refused(status_code=429))
        model = WithBackup(strong, FakePrModel({"scripts/report.py": [finding(17, "Division by zero")]}))
        result = PullRequestReviewService(FakeAdo(), model).review("proj", "repo", 7)
        assert result["model"] == {"deployment": "strong-sol", "fallback_deployment": "fake", "fallback_reason": "it is busy (rate limit)"}
        assert result["notes"][0] == ("The strong model (strong-sol) could not answer (it is busy (rate limit)), so the standard model (fake) did the rest of this review. "
                                      "Review again later to use the strong model.")
        assert [c["title"] for c in result["comments"]] == ["Division by zero"]

    def test_a_review_the_strong_model_made_alone_has_no_such_note(self):
        model = WithBackup(FakePrModel(), Deployment("standard-mini"))
        result = PullRequestReviewService(FakeAdo(), model).review("proj", "repo", 7)
        assert result["model"] == {"deployment": "fake", "fallback_deployment": None, "fallback_reason": None}
        assert not any("strong model" in note for note in result["notes"])

    def test_a_model_without_a_name_gives_no_info(self):
        assert model_info(SimpleNamespace()) is None


class TestOverHttp:
    @pytest.fixture
    def api(self, monkeypatch, configured):
        configured()
        asked = []
        state = {"model": FakePrModel(), "asked": asked}
        monkeypatch.setattr(routes, "AzureDevOpsClient", lambda organization, pat: FakeAdo())
        monkeypatch.setattr(pr_review, "get_model_client", lambda *choice: asked.append(choice) or state["model"])
        monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)
        return TestClient(create_app(), raise_server_exceptions=False), state

    PAYLOAD = {"organization": "myorg", "project": "myproj", "repository_id": "repo-1", "pull_request_id": 101, "pat": "fake-pat"}
    URL = "/api/v1/ado/pullrequests/review"

    def test_the_page_can_ask_which_models_there_are(self, api):
        client, _ = api
        assert client.get(f"{self.URL}/models").json() == {"standard": "standard-mini", "strong": "strong-sol", "default": "strong"}

    def test_the_choice_reaches_the_review(self, api):
        client, state = api
        for choice in ("standard", "strong"):
            assert client.post(self.URL, json={**self.PAYLOAD, "model": choice}).status_code == 200
        client.post(self.URL, json=self.PAYLOAD)
        assert state["asked"] == [("standard",), ("strong",), (None,)]

    def test_a_model_that_is_not_one_of_the_two_is_refused(self, api):
        client, state = api
        assert client.post(self.URL, json={**self.PAYLOAD, "model": "gpt-anything"}).status_code == 422
        assert state["asked"] == []

    def test_the_result_says_which_model_made_it(self, api):
        client, _ = api
        assert client.post(self.URL, json=self.PAYLOAD).json()["model"] == {"deployment": "fake", "fallback_deployment": None, "fallback_reason": None}

    def test_the_background_review_takes_the_choice_and_another_model_is_another_review(self, api):
        client, state = api
        first = client.post(f"{self.URL}/start", json={**self.PAYLOAD, "model": "standard"}).json()["job_id"]
        second = client.post(f"{self.URL}/start", json={**self.PAYLOAD, "model": "strong"}).json()["job_id"]
        assert first != second and [c for c in state["asked"] if c] == [("standard",), ("strong",)]
