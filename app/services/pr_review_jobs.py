"""Pull request reviews that run in the background.

A review that looks things up and checks every finding can take minutes, and Azure App Service ends a web request after 230 seconds. So
the page starts the review, gets a job id at once, and asks for progress until the job is done. Jobs live in this process's memory only:
nothing about a review (its code snippets, its findings) is written to disk, and the token is never stored, it is only held by the running
job. If the app restarts, a job is gone and the page says so: the review is run again.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

TTL_SECONDS = 3600  # a finished job is kept for an hour
MAX_RUNNING = 4  # reviews running at once in this process: each one makes many model calls


class TooManyReviews(Exception):
    pass


class ReviewJobs:
    def __init__(self, max_running: int = MAX_RUNNING, ttl: float = TTL_SECONDS):
        self.max_running, self.ttl = max_running, ttl
        self._jobs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    @staticmethod
    def fingerprint(*parts: Any) -> str:
        """A key for "the same review by the same person": a hash, so a token is never kept."""
        return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()

    def _purge(self) -> None:
        now = time.monotonic()
        for job_id in [i for i, j in self._jobs.items() if j["status"] != "running" and now - j["finished"] > self.ttl]:
            self._jobs.pop(job_id, None)
            self._threads.pop(job_id, None)

    def start(self, key: str, work: Callable[[Callable[[int, int, str], None]], dict[str, Any]], explain: Callable[[Exception], tuple[int, str]]) -> str:
        """Start `work(progress)` in the background and return its job id. The same key while a job is still running gives that job's id (a second click
        does not start a second review). `explain(exception)` turns a failure into (status code, message) for the page."""
        with self._lock:
            self._purge()
            for job_id, job in self._jobs.items():
                if job["status"] == "running" and job["key"] == key:
                    return job_id
            if sum(1 for j in self._jobs.values() if j["status"] == "running") >= self.max_running:
                raise TooManyReviews("Several reviews are running already. Try again in a minute.")
            job_id = secrets.token_urlsafe(16)
            self._jobs[job_id] = {"key": key, "status": "running", "message": "Starting", "done": 0, "total": 0, "started": time.monotonic(), "finished": 0.0, "result": None, "error": None}
            thread = threading.Thread(target=self._run, args=(job_id, work, explain), name=f"pr-review-{job_id[:6]}", daemon=True)
            self._threads[job_id] = thread
        thread.start()
        return job_id

    def _progress(self, job_id: str) -> Callable[[int, int, str], None]:
        def tell(done: int, total: int, message: str) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.update(done=done, total=total, message=message)
        return tell

    def _run(self, job_id: str, work: Callable[[Callable[[int, int, str], None]], dict[str, Any]], explain: Callable[[Exception], tuple[int, str]]) -> None:
        try:
            result = work(self._progress(job_id))
            update = {"status": "done", "result": result, "message": "Done"}
        except Exception as exc:  # noqa: BLE001
            status, detail = explain(exc)
            logger.info("PR review job %s failed (%s)", job_id[:6], type(exc).__name__)
            update = {"status": "failed", "error": {"status_code": status, "detail": detail}, "message": detail}
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(update, finished=time.monotonic())

    def get(self, job_id: str) -> dict[str, Any] | None:
        """A copy of the job's state (status running | done | failed, progress, and the result or the error), or None when there is no such job."""
        with self._lock:
            self._purge()
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {"job_id": job_id, "status": job["status"], "message": job["message"], "done": job["done"], "total": job["total"],
                    "elapsed_seconds": int((job["finished"] or time.monotonic()) - job["started"]), "result": job["result"], "error": job["error"]}

    def join(self, job_id: str, timeout: float = 10) -> None:
        """Wait for a job to end (for tests)."""
        thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)


jobs = ReviewJobs()
