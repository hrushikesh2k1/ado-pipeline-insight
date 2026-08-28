from __future__ import annotations

import json
from typing import Any

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from core.models import Finding, RecommendationResponse


SYSTEM_PROMPT = """You are a senior DevOps performance engineer. Reason only over supplied metrics; never invent causes or facts.
Return strict JSON: {"findings":[{"category":"queue_capacity|flaky_step|regression|parallelization_opportunity|caching_opportunity|other","severity":"low|medium|high","stage_name":"required","task_name":"nullable","recommendation":"one sentence","evidence":"metric-backed concise evidence"}]}.
Name the most specific task responsible, when supplied.
Example input: {"stages":[{"name":"Build","delta_vs_prior_week_pct":34,"tasks":[{"name":"npm install","pct_of_parent_duration":57,"delta_vs_prior_week_pct":60,"failure_rate_pct":0}]}]}
Example output: {"findings":[{"category":"caching_opportunity","severity":"high","stage_name":"Build","task_name":"npm install","recommendation":"Check the dependency cache for npm install.","evidence":"It is 57% of Build and grew 60% week over week."}]}.
Example input: {"stages":[{"name":"Test","avg_queue_time_s":180,"tasks":[{"name":"Run unit tests","failure_rate_pct":18,"retry_rate_pct":22}]}]}
Example output: {"findings":[{"category":"flaky_step","severity":"high","stage_name":"Test","task_name":"Run unit tests","recommendation":"Investigate intermittent unit-test failures.","evidence":"Failure rate is 18% and retry rate is 22%."}]}.
"""


class PipelineRecommendationClient:
    def __init__(self, endpoint: str, deployment: str, api_version: str, api_key: str | None = None):
        self.deployment = deployment
        if api_key:
            self.client = AzureOpenAI(azure_endpoint=endpoint, api_version=api_version, api_key=api_key)
        else:
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            self.client = AzureOpenAI(azure_endpoint=endpoint, api_version=api_version, azure_ad_token_provider=token_provider)

    def recommend(self, summary: dict[str, Any]) -> RecommendationResponse:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.deployment,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(summary)}],
                    temperature=0,
                )
                return parse_recommendations(response.choices[0].message.content or "")
            except (ValueError, json.JSONDecodeError) as error:
                last_error = error
        raise ValueError("Azure OpenAI returned invalid recommendation JSON") from last_error


def parse_recommendations(content: str) -> RecommendationResponse:
    payload = json.loads(content)
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Response must contain a findings list")
    allowed_categories = {"queue_capacity", "flaky_step", "regression", "parallelization_opportunity", "caching_opportunity", "other"}
    allowed_severities = {"low", "medium", "high"}
    parsed = []
    for item in findings:
        required = {"category", "severity", "stage_name", "recommendation", "evidence"}
        if not required.issubset(item) or item["category"] not in allowed_categories or item["severity"] not in allowed_severities:
            raise ValueError("Response finding does not match the required schema")
        parsed.append(Finding(**{key: item.get(key) for key in Finding.__dataclass_fields__}))
    return RecommendationResponse(findings=parsed)