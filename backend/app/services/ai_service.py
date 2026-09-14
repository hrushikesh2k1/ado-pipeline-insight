from core.db import AlertRepository, build_analysis_summary
from core.openai_client import PipelineRecommendationClient
from backend.app.core.config import get_settings

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
        repo.upsert_recommendations(pipeline_id, findings)
        return {"pipeline_id": pipeline_id, "findings": findings, "message": "AI analysis completed."}
