from __future__ import annotations

import json
import time
from typing import Any

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI
from core.models import (
    Finding,
    RecommendationResponse,
    PullRequestReviewComment,
    PullRequestReviewResponse,
)


SYSTEM_PROMPT = """You are a Principal DevOps Architect and Reliability Engineering expert analyzing CI/CD pipeline telemetry.
Your mission is to provide world-class, concrete, actionable diagnoses and remediations based on measured performance metrics and actual error log excerpts. Never invent ungrounded facts.

Return strict JSON: {"findings":[{"category":"flaky_step|bottleneck|regression|caching_opportunity|parallelization_opportunity|queue_capacity|other","severity":"high|medium|low","stage_name":"<exact stage name>","task_name":"<exact task name or null>","recommendation":"<structured recommendation text>","evidence":"<metric-backed proof and log snippet>"}]}

Guidelines for World-Class Findings:
1. Coverage & Prioritization: Return between 1 and 4 high-impact, non-overlapping findings across:
   - Critical Failures / Flakiness (category: flaky_step, severity: high) when failure_rate_pct > 0 or error_excerpt is provided.
   - Duration Bottlenecks & Regressions (category: bottleneck or regression) for stages/tasks consuming the largest portion of pipeline execution time.
   - Optimization & Caching (category: caching_opportunity or parallelization_opportunity) for tasks with long execution times that can be cached (e.g. package restores, Docker builds, artifact downloads).
2. Deep Technical Diagnosis:
   - When an `error_excerpt` is provided in the input, identify the exact root cause (e.g., Kubernetes API dial timeout, Helm release lock, TLS handshake failure, missing dependency, OOM kill, exit code).
   - If no error log is present, diagnose based on duration and failure patterns.
3. Structure of `recommendation`:
   Format every recommendation with three distinct markdown sections:
   **Diagnosis**: Precise root cause explanation (referencing the error excerpt if present).
   **Remediation**: Concrete, actionable engineering fix. ALWAYS include a clean, copy-pasteable Azure DevOps pipeline YAML snippet enclosed in a ```yaml ... ``` code block (e.g., using `Cache@2`, task retry policy `retryCountOnTaskFailure: 2`, `--timeout` flags, or matrix execution).
   **Impact**: Quantified expected benefit (e.g., "Eliminates ~25% failure rate in Build / Test stage", "Saves ~4.5 minutes per pipeline run").
4. Structure of `evidence`:
   Concise summary of measured metrics (duration, failure rate, retry rate, % of stage). If `error_excerpt` is provided, quote the relevant log snippet cleanly (e.g., 'Error Log: "dial tcp 13.77.233.102:443: i/o timeout"').
5. Severity Guidelines:
   - high: Failure rate >= 15%, or stage duration > 15m, or timeout errors blocking deployments.
   - medium: Failure rate between 5% and 15%, or task taking > 30% of stage time, or duration regression > 25%.
   - low: Minor duration optimizations, non-blocking retries, or small caching candidates.
"""


class PipelineRecommendationClient:
    """Azure OpenAI client using the Azure OpenAI v1 API surface."""

    def __init__(self, endpoint: str, deployment: str, api_version: str, api_key: str | None = None):
        del api_version  # Azure OpenAI v1 does not require api-version in the URL.
        self.deployment = deployment
        base_url = endpoint.rstrip("/") + "/"

        if not base_url.endswith("/openai/v1/"):
            if "/openai/v1" not in base_url:
                base_url = base_url.rstrip("/") + "/openai/v1/"

        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                "https://cognitiveservices.azure.com/.default",
            )
            self.client = OpenAI(api_key=token_provider, base_url=base_url)

    def recommend(self, summary: dict[str, Any]) -> RecommendationResponse:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.deployment,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(summary)},
                    ],
                    temperature=0,
                )
                return parse_recommendations(response.choices[0].message.content or "")
            except Exception as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                if status_code == 429 and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                if isinstance(error, (ValueError, json.JSONDecodeError)) and attempt < 2:
                    time.sleep(0.5)
                    continue
                break
        raise ValueError("Azure OpenAI failed after retries") from last_error

    def review_pull_request(self, pr_context: dict[str, Any]) -> PullRequestReviewResponse:
        pr_id = int(pr_context.get("pull_request_id", 0))
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.deployment,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": PR_REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(pr_context)},
                    ],
                    temperature=0.1,
                )
                return parse_pr_review(response.choices[0].message.content or "", pr_id)
            except Exception as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                if status_code == 429 and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                if isinstance(error, (ValueError, json.JSONDecodeError)) and attempt < 2:
                    time.sleep(0.5)
                    continue
                break
        raise ValueError("Azure OpenAI PR review failed after retries") from last_error


def parse_recommendations(content: str) -> RecommendationResponse:
    payload = json.loads(content)
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Response must contain a findings list")
    allowed_categories = {
        "queue_capacity",
        "flaky_step",
        "regression",
        "bottleneck",
        "parallelization_opportunity",
        "caching_opportunity",
        "other",
    }
    allowed_severities = {"low", "medium", "high"}
    parsed = []
    for item in findings:
        required = {"category", "severity", "stage_name", "recommendation", "evidence"}
        if (
            not isinstance(item, dict)
            or not required.issubset(item)
            or item["category"] not in allowed_categories
            or item["severity"] not in allowed_severities
        ):
            raise ValueError("Response finding does not match the required schema")
        parsed.append(Finding(**{key: item.get(key) for key in Finding.__dataclass_fields__}))
    return RecommendationResponse(findings=parsed)


PR_REVIEW_SYSTEM_PROMPT = """You are a Principal Software Engineer, Staff Architect, and Application Security expert conducting a rigorous, evidence-grounded code review of an Azure DevOps Pull Request.

Your goal is to provide a constructive, precise, and professional review with concrete, actionable review comments.
CRITICAL CONSTRAINT: You are generating review comments solely for in-application display. NEVER assume these comments are published to Azure DevOps.

Adhere strictly to these Core Review Principles:

1. ACTIONABLE & GROUNDED CODE REVIEW COMMENTS:
   - When the developer clicks "Add review comments", they expect constructive, actionable findings in `comments`.
   - Each comment in `comments` MUST specify:
     * `file_path`: An actual file path from `changed_files`.
     * `line_number`: Specific integer line number if `content_snippet` is provided, or a relevant line / null.
     * `category`: "correctness" | "security" | "performance" | "maintainability" | "test_coverage".
     * `severity`: "critical" | "warning" | "suggestion" | "praise".
     * `title`: A concise, descriptive summary of the finding.
     * `comment`: Detailed explanation of WHAT can happen, WHY it matters, and the risk.
     * `suggestion_code`: A complete, copy-pasteable replacement snippet strictly matching the project's language (e.g., Python for Python files, TypeScript for TypeScript files).

2. CONSISTENCY WITH SCORECARD & VERDICT (CRITICAL RULE):
   - Every dimension in `scorecard` rated "NEEDS_IMPROVEMENT" or "CONCERNING", and every PR with verdict "APPROVED_WITH_SUGGESTIONS" or "CHANGES_REQUESTED", MUST HAVE CORRESPONDING ACTIONABLE COMMENTS in `comments`.
   - NEVER show "NEEDS_IMPROVEMENT" on the scorecard or "APPROVED_WITH_SUGGESTIONS" with 0 comments!
   - For example:
     * If Security is "NEEDS_IMPROVEMENT" for an HTML reporting change: Provide an actionable security comment (e.g., recommending HTML entity escaping via `html.escape` to prevent XSS/injection in generated HTML reports) with a copy-pasteable Python snippet.
     * If Test Coverage is "NEEDS_IMPROVEMENT": Provide an actionable testing comment targeting the changed report generator or test file, with a sample unit test implementation snippet.

3. USE THE PROJECT'S LANGUAGE AND CONTEXT:
   - All code snippets in `suggestion_code` MUST strictly match the programming language of the target file (as specified in `primary_languages` and file extensions).
   - If the PR modifies Python, suggestions MUST be idiomatic, valid Python. NEVER generate JavaScript, TypeScript, or other foreign languages for Python changes.

4. TREAT PR DESCRIPTIONS & CHECKLISTS AS CLUES, NOT PROOF:
   - PR descriptions and checklist boxes are human context clues—NOT definitive proof of code defects.
   - Mixed evidence: If test sections are blank or checkboxes are unchecked, but test files were modified or regression results links are present, do not assert tests are missing. Frame observations as constructive suggestions or verify in `clarifications`.

5. PREFER HIGH-SIGNAL, VALUABLE COMMENTS OVER BOILERPLATE:
   - Return 1 to 4 high-value, actionable, evidence-backed findings across security, correctness, and testing.
   - Avoid generic hand-waving (e.g., "ensure proper modularity"). Explain the concrete scenario (e.g., "when report contains special characters '<', '&', or user-supplied test names, HTML injection can corrupt the report layout or lead to stored XSS").

6. SEPARATE CODE FINDINGS FROM REVIEW PROCESS NOTES:
   - Code-level findings, security improvements, and test additions belong in `comments`.
   - Non-code process inquiries, wiki reminders, and PR checklist reminders belong in `clarifications`.

### Output Format (Strict JSON):
{
  "verdict": "APPROVED" | "APPROVED_WITH_SUGGESTIONS" | "CHANGES_REQUESTED",
  "summary": "<1-3 sentence concise executive summary grounded in the PR changes and intent>",
  "clarifications": [
    "<Optional non-blocking question or clarification regarding PR process, documentation, or checklist>"
  ],
  "scorecard": {
    "correctness": "EXCELLENT" | "GOOD" | "NEEDS_IMPROVEMENT" | "CONCERNING",
    "security": "EXCELLENT" | "GOOD" | "NEEDS_IMPROVEMENT" | "CONCERNING",
    "performance": "EXCELLENT" | "GOOD" | "NEEDS_IMPROVEMENT" | "CONCERNING",
    "maintainability": "EXCELLENT" | "GOOD" | "NEEDS_IMPROVEMENT" | "CONCERNING",
    "test_coverage": "EXCELLENT" | "GOOD" | "NEEDS_IMPROVEMENT" | "CONCERNING"
  },
  "comments": [
    {
      "id": "comment-1",
      "category": "correctness" | "security" | "performance" | "maintainability" | "test_coverage",
      "severity": "critical" | "warning" | "suggestion" | "praise",
      "file_path": "<exact file path from changed_files>",
      "line_number": <specific integer line number or null>,
      "title": "<concise title of the finding>",
      "comment": "<actionable, grounded explanation of what can go wrong and why>",
      "suggestion_code": "<copy-pasteable replacement code strictly in the target file's language, or null>"
    }
  ]
}
"""



def parse_pr_review(content: str, pull_request_id: int) -> PullRequestReviewResponse:
    payload = json.loads(content)
    verdict = payload.get("verdict", "APPROVED_WITH_SUGGESTIONS")
    summary = payload.get("summary", "Pull request review completed.")
    scorecard = payload.get("scorecard", {})
    raw_comments = payload.get("comments") or []
    raw_clarifications = payload.get("clarifications") or []

    clarifications = [str(item) for item in raw_clarifications if isinstance(item, (str, int, float))]

    parsed_comments = []
    allowed_categories = {"correctness", "security", "performance", "maintainability", "test_coverage"}
    allowed_severities = {"critical", "warning", "suggestion", "praise"}

    for idx, c in enumerate(raw_comments):
        if not isinstance(c, dict):
            continue
        cat = c.get("category", "maintainability")
        if cat not in allowed_categories:
            cat = "maintainability"
        sev = c.get("severity", "suggestion")
        if sev not in allowed_severities:
            sev = "suggestion"
        cid = str(c.get("id") or f"review-comment-{idx + 1}")
        title = str(c.get("title") or "Code Review Feedback")
        comment = str(c.get("comment") or "")
        file_path = c.get("file_path")
        line_num = c.get("line_number")
        if line_num is not None:
            try:
                line_num = int(line_num)
            except (ValueError, TypeError):
                line_num = None
        suggestion = c.get("suggestion_code")

        parsed_comments.append(
            PullRequestReviewComment(
                id=cid,
                category=cat,
                severity=sev,
                title=title,
                comment=comment,
                file_path=str(file_path) if file_path else None,
                line_number=line_num,
                suggestion_code=str(suggestion) if suggestion else None,
            )
        )

    return PullRequestReviewResponse(
        pull_request_id=pull_request_id,
        verdict=verdict,
        summary=summary,
        scorecard=scorecard if isinstance(scorecard, dict) else {},
        comments=parsed_comments,
        clarifications=clarifications,
        posted_to_ado=False,
    )

