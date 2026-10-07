"""Reviews that run in the background: the job store, and the routes that start a review and report its progress."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import create_app
from app.services import pr_review, pr_review_jobs
from app.services.pr_review_jobs import ReviewJobs, TooManyReviews
from pr_support import FakeAdo, FakePrModel, finding

PAYLOAD = {"organization": "myorg", "project": "myproj", "repository_id": "repo-1", "pull_request_id": 101, "pat": "fake-pat-value"}
START = "/api/v1/ado/pullrequests/review/start"
STATUS = "/api/v1/ado/pullrequests/review/status/"


def explain(exc):
    return 502, "The pull request review failed. Nothing was reviewed."


def wait_for(jobs, job_id, status="running", timeout=5):
    """Wait until the job is no longer in the given state."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = jobs.get(job_id)
        if job["status"] != status:
            return job
        time.sleep(0.01)
    raise AssertionError("the job did not finish")


class TestTheJobStore:
    def test_a_job_runs_in_the_background_and_its_result_is_kept(self):
        jobs = ReviewJobs()
        release = threading.Event()

        def work(progress):
            progress(1, 4, "Reviewed 1 of 4 files")
            release.wait(5)
            return {"verdict": "APPROVED"}

        job_id = jobs.start("key", work, explain)
        running = jobs.get(job_id)
        assert running["status"] == "running" and running["result"] is None and running["error"] is None
        time.sleep(0.05)
        assert (jobs.get(job_id)["done"], jobs.get(job_id)["total"], jobs.get(job_id)["message"]) == (1, 4, "Reviewed 1 of 4 files")
        release.set()
        done = wait_for(jobs, job_id)
        assert done["status"] == "done" and done["result"] == {"verdict": "APPROVED"} and done["message"] == "Done"

    def test_the_same_review_started_twice_while_running_is_one_job(self):
        jobs = ReviewJobs()
        release = threading.Event()
        first = jobs.start("same", lambda progress: release.wait(5) or {}, explain)
        assert jobs.start("same", lambda progress: {}, explain) == first
        other = jobs.start("other", lambda progress: release.wait(5) or {}, explain)
        assert other != first
        release.set()
        wait_for(jobs, first)
        assert jobs.start("same", lambda progress: {}, explain) != first  # a finished job is not reused: the page asked for a new review

    def test_a_failure_is_explained_and_its_details_are_not_leaked(self):
        jobs = ReviewJobs()

        def work(progress):
            raise RuntimeError("secret internals: token abc123")

        failed = wait_for(jobs, jobs.start("k", work, explain))
        assert failed["status"] == "failed" and failed["error"] == {"status_code": 502, "detail": "The pull request review failed. Nothing was reviewed."}
        assert "abc123" not in str(failed) and failed["result"] is None

    def test_the_explainer_chooses_the_status_and_message(self):
        jobs = ReviewJobs()
        failed = wait_for(jobs, jobs.start("k", lambda progress: (_ for _ in ()).throw(ValueError("x")), lambda exc: (422, "No file changes.")))
        assert failed["error"] == {"status_code": 422, "detail": "No file changes."} and failed["message"] == "No file changes."

    def test_only_a_few_reviews_run_at_once(self):
        jobs = ReviewJobs(max_running=2)
        release = threading.Event()
        ids = [jobs.start(f"k{n}", lambda progress: release.wait(5) or {}, explain) for n in range(2)]
        with pytest.raises(TooManyReviews, match="Try again in a minute"):
            jobs.start("k2", lambda progress: {}, explain)
        release.set()
        for job_id in ids:
            wait_for(jobs, job_id)
        jobs.start("k2", lambda progress: {}, explain)  # room again

    def test_a_finished_job_is_forgotten_after_a_while(self):
        jobs = ReviewJobs(ttl=0.05)
        job_id = jobs.start("k", lambda progress: {}, explain)
        wait_for(jobs, job_id)
        assert jobs.get(job_id) is not None
        time.sleep(0.1)
        assert jobs.get(job_id) is None

    def test_a_job_that_is_still_running_is_never_forgotten(self):
        jobs = ReviewJobs(ttl=0.0)
        release = threading.Event()
        job_id = jobs.start("k", lambda progress: release.wait(5) or {}, explain)
        time.sleep(0.05)
        assert jobs.get(job_id)["status"] == "running"
        release.set()

    def test_an_unknown_job_is_none(self):
        assert ReviewJobs().get("nope") is None

    def test_a_job_id_cannot_be_guessed_and_the_key_hides_the_token(self):
        jobs = ReviewJobs()
        ids = {jobs.start(f"k{n}", lambda progress: {}, explain) for n in range(5)}
        assert len(ids) == 5 and all(len(i) >= 20 for i in ids)
        key = ReviewJobs.fingerprint("org", "proj", "repo", 7, "my-secret-token")
        assert "my-secret-token" not in key and len(key) == 64
        assert key != ReviewJobs.fingerprint("org", "proj", "repo", 7, "another-token")  # two people reviewing the same pull request do not share a job

    def test_the_review_is_kept_in_memory_only(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setenv("TEMP", str(tmp_path))
        jobs = ReviewJobs()
        wait_for(jobs, jobs.start("k", lambda progress: {"snippet": "SECRET CODE"}, explain))
        assert list(tmp_path.iterdir()) == []


@pytest.fixture
def api(monkeypatch):
    state = {"ado": FakeAdo(), "model": FakePrModel(), "ado_args": []}

    def make_ado(organization, pat):
        state["ado_args"].append((organization, pat))
        return state["ado"]

    monkeypatch.setattr(routes, "AzureDevOpsClient", make_ado)
    monkeypatch.setattr(pr_review, "get_model_client", lambda: state["model"])
    monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)
    monkeypatch.setattr(pr_review_jobs, "jobs", ReviewJobs())
    return TestClient(create_app(), raise_server_exceptions=False), state


def finish(client, job_id, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        response = client.get(STATUS + job_id)
        assert response.status_code == 200
        if response.json()["status"] != "running":
            return response.json()
        time.sleep(0.02)
    raise AssertionError("the review did not finish")


class TestTheRoutes:
    def test_starting_a_review_returns_a_job_at_once_and_the_review_follows(self, api):
        client, state = api
        state["model"] = FakePrModel({"scripts/report.py": [finding(17, "Division by zero")]})
        started = client.post(START, json=PAYLOAD)
        assert started.status_code == 202
        body = started.json()
        assert body["status"] in {"running", "done"} and len(body["job_id"]) >= 20
        done = finish(client, body["job_id"])
        assert done["status"] == "done" and done["error"] is None and done["message"] == "Done"
        review = done["result"]
        assert review["pull_request_id"] == 101 and review["posted_to_ado"] is False and review["verdict"] == "APPROVED_WITH_SUGGESTIONS"
        assert [(c["title"], c["verified"], c["source"]) for c in review["comments"]] == [("Division by zero", True, "ai")]

    def test_the_background_review_is_the_same_review_as_the_one_inside_a_request(self, api):
        client, state = api
        state["model"] = FakePrModel({"scripts/report.py": [finding(17, "Division by zero")]})
        direct = client.post("/api/v1/ado/pullrequests/review", json=PAYLOAD).json()
        background = finish(client, client.post(START, json=PAYLOAD).json()["job_id"])["result"]
        assert background == direct

    def test_the_background_review_gets_more_time_than_a_request(self, api, monkeypatch):
        client, state = api
        seen = []
        original = pr_review.PullRequestReviewService.review

        def spy(self, project, repository, pr_id, progress=None, budget=pr_review.REVIEW_BUDGET_SECONDS, knowledge=""):
            seen.append((budget, progress is not None))
            return original(self, project, repository, pr_id, progress, budget, knowledge)

        monkeypatch.setattr(pr_review.PullRequestReviewService, "review", spy)
        finish(client, client.post(START, json=PAYLOAD).json()["job_id"])
        client.post("/api/v1/ado/pullrequests/review", json=PAYLOAD)
        assert seen == [(pr_review.BACKGROUND_BUDGET_SECONDS, True), (pr_review.REVIEW_BUDGET_SECONDS, False)]

    def test_progress_is_visible_while_it_runs(self, api):
        client, state = api
        release = threading.Event()

        class Slow(FakePrModel):
            def _create(self, *args, **kwargs):
                release.wait(5)
                return super()._create(*args, **kwargs)

        state["model"] = Slow()
        job_id = client.post(START, json=PAYLOAD).json()["job_id"]
        time.sleep(0.2)
        running = client.get(STATUS + job_id).json()
        assert running["status"] == "running" and running["total"] == 3 and running["message"] == "Reviewing 3 files" and running["result"] is None
        release.set()
        assert finish(client, job_id)["status"] == "done"

    def test_the_token_is_used_for_azure_devops_and_never_comes_back(self, api):
        client, state = api
        started = client.post(START, json=PAYLOAD)
        done = finish(client, started.json()["job_id"])
        assert state["ado_args"] == [("myorg", "fake-pat-value")]
        assert "fake-pat-value" not in started.text and "fake-pat-value" not in str(done)

    def test_a_second_click_while_it_runs_follows_the_same_job(self, api):
        client, state = api
        release = threading.Event()

        class Slow(FakePrModel):
            def _create(self, *args, **kwargs):
                release.wait(5)
                return super()._create(*args, **kwargs)

        state["model"] = Slow()
        first = client.post(START, json=PAYLOAD).json()["job_id"]
        assert client.post(START, json=PAYLOAD).json()["job_id"] == first
        release.set()
        finish(client, first)

    def test_without_the_ai_it_is_refused_at_once(self, api, monkeypatch):
        client, _ = api

        def unavailable():
            raise pr_review.AiUnavailable("Azure OpenAI is not configured, so the AI review is unavailable. Nothing was reviewed.")

        monkeypatch.setattr(pr_review, "get_model_client", unavailable)
        response = client.post(START, json=PAYLOAD)
        assert response.status_code == 503 and "Nothing was reviewed" in response.json()["detail"]

    def test_a_review_that_fails_says_why_in_its_status(self, api):
        client, state = api
        state["ado"] = FakeAdo(changes=[])
        done = finish(client, client.post(START, json=PAYLOAD).json()["job_id"])
        assert done["status"] == "failed" and done["result"] is None
        assert done["error"]["status_code"] == 422 and "no file changes" in done["error"]["detail"]

    def test_azure_devops_errors_are_explained_as_they_are_for_a_direct_review(self, api):
        client, state = api
        state["ado"] = FakeAdo()
        state["ado"].get_pull_request = lambda *args: (_ for _ in ()).throw(requests.HTTPError(response=SimpleNamespace(status_code=401)))
        done = finish(client, client.post(START, json=PAYLOAD).json()["job_id"])
        assert done["error"]["status_code"] == 401 and "PAT" in done["error"]["detail"]

    def test_an_unexpected_error_does_not_leak_its_details(self, api):
        client, state = api
        state["ado"] = FakeAdo(fail={"get_pull_request"})
        done = finish(client, client.post(START, json=PAYLOAD).json()["job_id"])
        assert done["error"]["status_code"] == 502 and "get_pull_request failed" not in str(done) and "Nothing was reviewed" in done["error"]["detail"]

    def test_too_many_reviews_at_once_is_a_429(self, api, monkeypatch):
        client, _ = api
        monkeypatch.setattr(pr_review_jobs, "jobs", ReviewJobs(max_running=0))
        response = client.post(START, json=PAYLOAD)
        assert response.status_code == 429 and "Try again in a minute" in response.json()["detail"]

    def test_a_review_that_is_gone_says_to_start_it_again(self, api):
        client, _ = api
        response = client.get(STATUS + "abcdefghijklmnopqrstuv")
        assert response.status_code == 404 and "Start it again" in response.json()["detail"]

    @pytest.mark.parametrize("job_id", ["short", "has space in it!", "../../etc/passwd", "x" * 80])
    def test_a_job_id_that_cannot_be_one_is_refused(self, api, job_id):
        client, _ = api
        assert client.get(STATUS + job_id).status_code in {404, 422}

    def test_the_request_is_validated_like_the_direct_one(self, api):
        client, _ = api
        assert client.post(START, json={**PAYLOAD, "pull_request_id": 0}).status_code == 422
        assert client.post(START, json={**PAYLOAD, "organization": ""}).status_code == 422

    def test_without_a_pat_the_caller_is_asked_for_one(self, api, monkeypatch):
        client, _ = api

        def no_pat(org):
            raise RuntimeError("no key vault")

        monkeypatch.setattr(routes, "get_ado_pat", no_pat)
        monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(allowed_ado_org_list=[]))
        response = client.post(START, json={k: v for k, v in PAYLOAD.items() if k != "pat"})
        assert response.status_code == 401 and "personal access token" in response.json()["detail"].lower()
