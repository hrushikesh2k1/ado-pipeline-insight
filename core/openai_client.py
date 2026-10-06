from __future__ import annotations

import json
import time
from typing import Any

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI
from core.models import (
    Finding,
    RecommendationResponse,
)


SYSTEM_PROMPT = """You are a Principal DevOps Architect and Reliability Engineering expert analyzing CI/CD pipeline telemetry.
Your mission is to provide world-class, concrete, actionable diagnoses and remediations based on measured performance metrics and actual error log excerpts. Never invent ungrounded facts.

Return strict JSON: {"findings":[{"category":"flaky_step|bottleneck|regression|caching_opportunity|parallelization_opportunity|queue_capacity|other","severity":"high|medium|low","stage_name":"<exact stage name>","task_name":"<exact task name or null>","recommendation":"<structured recommendation text>","evidence":"<metric-backed proof and log snippet>"}]}

Guidelines for World-Class Findings:
1. Coverage & Prioritization: The tasks in the input are sorted by failure rate, worst first. Return one finding for EVERY task with `failure_rate_pct` >= 15 or `retry_rate_pct` >= 20 (all severity high; up to 8, worst first), then up to 3 more non-overlapping findings for the largest bottlenecks, regressions or optimization opportunities, across:
   - Critical Failures / Flakiness (category: flaky_step, severity: high) when failure_rate_pct > 0 or error_excerpt is provided.
   - Duration Bottlenecks & Regressions (category: bottleneck or regression) for stages/tasks consuming the largest portion of pipeline execution time.
   - Optimization & Caching (category: caching_opportunity or parallelization_opportunity) for tasks with long execution times that can be cached (e.g. package restores, Docker builds, artifact downloads).
2. Deep Technical Diagnosis:
   - When an `error_excerpt` is provided in the input, identify the exact root cause (e.g., Kubernetes API dial timeout, Helm release lock, TLS handshake failure, missing dependency, OOM kill, exit code).
   - If no error log is present, diagnose based on duration and failure patterns.
3. Structure of `recommendation`:
   Format every recommendation with three distinct markdown sections:
   **Diagnosis**: Precise root cause explanation (referencing the error excerpt if present).
   **Remediation**: Concrete, actionable engineering fix. It MUST contain exactly one code block with the YAML fix, ready to copy and paste. When `pipeline_yaml` shows the step (see rule 6), the block is a unified diff in a ```diff ... ``` block against the file that defines the step. Otherwise it is a short ```yaml ... ``` snippet whose first line is the comment `# example, not from your file`.
   **Impact**: What was measured and what fixing the cause removes, using only numbers from the input (for example "This step failed in 31.8% of runs in the analysed window"). Never promise a result such as "Eliminates ~30% failure rate" or "Saves 4 minutes": nothing in the data supports a prediction.
   Every finding MUST have all three sections: the root cause, the remediation and the YAML fix inside it.
4. Structure of `evidence`:
   Concise summary of measured metrics (duration, failure rate, retry rate, % of stage). If `error_excerpt` is provided, quote the relevant log snippet cleanly (e.g., 'Error Log: "dial tcp 13.77.233.102:443: i/o timeout"').
5. Severity Guidelines:
   - high: Failure rate >= 15%, or stage duration > 15m, or timeout errors blocking deployments.
   - medium: Failure rate between 5% and 15%, or task taking > 30% of stage time, or duration regression > 25%.
   - low: Minor duration optimizations, non-blocking retries, or small caching candidates.
6. The customer's real pipeline files (`pipeline_yaml`):
   - When the input contains `pipeline_yaml` ({file, branch, content, truncated, templates, templates_not_expanded, template_errors}), `content` is the complete pipeline YAML that produced these runs and `templates` holds the complete template files that were read ({file, content}); read all of them before answering. A step can live in any of them. If `truncated` is true, part of a file was cut for size: do not describe what you could not see. Base every remediation on the files: name the exact file, stage, job and step it applies to, and write the fix as a unified diff (```diff, with `--- a/<file>` and `+++ b/<file>` headers and context and removed lines copied exactly from that file) against the file that defines the step. A diff whose lines do not exist in the file is discarded.
   - Never recommend something the files already do (for example caching when the job already has a `Cache@2` step, or retries when the step already has `retryCountOnTaskFailure`). If the file already applies a fix and the problem persists, say the fix is not working and diagnose why from the error log instead.
   - Templates listed in `templates_not_expanded` could not be read (`template_errors` says why): do not guess their contents or invent the step's task type or inputs, and do not write a diff against files you cannot see. Name the template, describe the change in words, and give a short example snippet marked `# example, not from your file` that is derived from the error text (for example defining a variable that the error shows is empty), not from a guess about the step.
   - If `pipeline_yaml` is absent, the files could not be read: keep the snippet minimal, mark it `# example, not from your file`, and do not claim anything about the customer's YAML.
   - When several steps or stages fail with the same error, write one finding for the worst occurrence and name the others in its Diagnosis.
7. Retries (`retryCountOnTaskFailure`):
   - Recommend a retry only when `error_excerpt` shows a transient cause (timeout, connection reset or refused, DNS failure, 429/502/503/504 throttling, a lock held by another operation) or the task's `retry_rate_pct` is above 0.
   - A generic exit code or a deterministic error (not found, permission denied, invalid input, failing tests) will fail again on every retry. For those, do NOT recommend retries and do NOT describe the failures as transient; quote the first error line from `error_excerpt` and tell the customer to fix that cause. If there is no usable error text, say the cause is unknown and to open the step log.
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
