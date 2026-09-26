from __future__ import annotations

import json
import time
from typing import Any

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI

from core.models import Finding, RecommendationResponse


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
   **Remediation**: Concrete, actionable engineering fix (provide specific YAML keys, CLI flags like `--validate=false` or `--timeout`, retry policies, or cache task configurations).
   **Impact**: Quantified expected benefit (e.g., "Eliminates ~25% failure rate in Monitoring stage", "Saves ~4.5 minutes per pipeline run").
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
