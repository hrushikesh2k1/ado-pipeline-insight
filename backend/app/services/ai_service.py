from core.db import AlertRepository, build_analysis_summary
from core.openai_client import PipelineRecommendationClient
from backend.app.core.config import get_settings


def _telemetry_fallback(summary: dict) -> list[dict]:
    stages = summary.get("stages") or []
    if not stages:
        return []

    stage = max(stages, key=lambda item: item.get("avg_duration_s", 0) or 0)
    tasks = stage.get("tasks") or []
    task = max(tasks, key=lambda item: item.get("avg_duration_s", 0) or 0) if tasks else None
    target_name = task.get("name") if task else stage.get("name", "unknown stage")
    stage_name = stage.get("name", "unknown stage")
    failure_rate = float((task or stage).get("failure_rate_pct", 0) or 0)
    retry_rate = float((task or stage).get("retry_rate_pct", 0) or 0)
    duration = float((task or stage).get("avg_duration_s", 0) or 0)

    if failure_rate > 0 or retry_rate > 0:
        category = "flaky_step"
        severity = "high" if failure_rate >= 10 or retry_rate >= 10 else "medium"
        recommendation = f"Investigate {target_name} for intermittent failures or retries."
        evidence = f"{target_name} has a {failure_rate:g}% failure rate and {retry_rate:g}% retry rate."
    else:
        category = "other"
        severity = "medium"
        recommendation = f"Review {target_name} as the largest measured duration contributor."
        evidence = f"{target_name} averages {duration:g} seconds in the selected telemetry window."

    return [{
        "category": category,
        "severity": severity,
        "stage_name": stage_name,
        "task_name": task.get("name") if task else None,
        "recommendation": recommendation,
        "evidence": evidence,
    }]


class AIService:
    def analyze(self, pipeline_id: int, days: int):
        settings = get_settings()
        if not settings.sql_connection_string:
            raise RuntimeError("SQL_CONNECTION_STRING is not configured.")

        repo = AlertRepository(settings.sql_connection_string)
        run_count = repo.count_runs(pipeline_id, days=days)
        if run_count < settings.min_history_runs:
            return {
                "pipeline_id": pipeline_id,
                "findings": [],
                "message": f"Not enough completed run history. Found {run_count} completed runs, but {settings.min_history_runs} are required for AI analysis.",
            }

        if not settings.azure_openai_endpoint or not settings.azure_openai_deployment:
            raise RuntimeError("Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT in .env.")

        summary = build_analysis_summary(repo.get_pipeline_metrics(pipeline_id, days=days), window_days=days)
        client = PipelineRecommendationClient(
            settings.azure_openai_endpoint,
            settings.azure_openai_deployment,
            settings.azure_openai_api_version,
            settings.azure_openai_api_key or None,
        )
        findings = [finding.__dict__ for finding in client.recommend(summary).findings]
        if not findings:
            findings = _telemetry_fallback(summary)
        repo.upsert_recommendations(pipeline_id, findings)
        message = "AI analysis completed." if findings else "No recommendations could be generated from the available telemetry."
        return {"pipeline_id": pipeline_id, "findings": findings, "message": message}
