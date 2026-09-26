from core.db import AlertRepository, build_analysis_summary
from core.openai_client import PipelineRecommendationClient
from app.core.config import get_settings
from app.core.errors import ServiceConfigError


def _telemetry_fallback(summary: dict) -> list[dict]:
    stages = summary.get("stages") or []
    if not stages:
        return []

    findings = []

    # 1. Critical Failures & Flakiness
    for stage in stages:
        stage_name = stage.get("name", "Unknown Stage")
        tasks = stage.get("tasks") or []
        for task in tasks:
            fail_pct = float(task.get("failure_rate_pct", 0) or 0)
            retry_pct = float(task.get("retry_rate_pct", 0) or 0)
            err = task.get("error_excerpt")
            if fail_pct > 0 or retry_pct > 0 or err:
                task_name = task.get("name", "Unknown Task")
                sev = "high" if fail_pct >= 15 or retry_pct >= 20 else "medium"

                diagnosis = f"Task '{task_name}' failed in {fail_pct:g}% of runs"
                if err:
                    diagnosis += f". Error: {err}"
                else:
                    diagnosis += f" and experienced {retry_pct:g}% retry rate."

                remediation = f"Add automatic retry policies or pass diagnostic timeout flags to '{task_name}' in pipeline YAML."
                impact = f"Eliminates ~{fail_pct:g}% pipeline failure rate in the '{stage_name}' stage."

                rec_text = f"**Diagnosis**: {diagnosis}\n**Remediation**: {remediation}\n**Impact**: {impact}"
                evidence = f"Failure rate: {fail_pct:g}%, Retry rate: {retry_pct:g}%, Avg duration: {task.get('avg_duration_s', 0):g}s."
                if err:
                    evidence += f" Error Log: \"{err}\""

                findings.append({
                    "category": "flaky_step",
                    "severity": sev,
                    "stage_name": stage_name,
                    "task_name": task_name,
                    "recommendation": rec_text,
                    "evidence": evidence,
                })
                if len(findings) >= 2:
                    break
        if len(findings) >= 2:
            break

    # 2. Duration Bottlenecks & Caching Candidates
    stage_by_duration = sorted(stages, key=lambda s: s.get("avg_duration_s", 0) or 0, reverse=True)
    if stage_by_duration:
        top_stage = stage_by_duration[0]
        top_stage_name = top_stage.get("name", "Unknown Stage")
        stage_avg = float(top_stage.get("avg_duration_s", 0) or 0)
        tasks = top_stage.get("tasks") or []
        top_task = max(tasks, key=lambda t: t.get("avg_duration_s", 0) or 0) if tasks else None

        target = top_task.get("name") if top_task else top_stage_name
        task_avg = float(top_task.get("avg_duration_s", 0) or 0) if top_task else stage_avg
        pct = float(top_task.get("pct_of_parent_duration", 0) or 0) if top_task else 100.0

        if not any(f["stage_name"] == top_stage_name and f["task_name"] == (top_task.get("name") if top_task else None) for f in findings):
            cat = "caching_opportunity" if any(kw in target.lower() for kw in ("restore", "install", "build", "cache", "download", "pull")) else "bottleneck"
            mins = round(task_avg / 60, 1)
            rec_text = (
                f"**Diagnosis**: '{target}' accounts for {pct:g}% of '{top_stage_name}' execution time ({task_avg:g}s average).\n"
                f"**Remediation**: Configure build caching (e.g. Cache@2 task) or execute independent steps concurrently.\n"
                f"**Impact**: Potential runtime reduction of ~{mins} minutes per pipeline execution."
            )
            evidence = f"Duration: {task_avg:g}s ({pct:g}% of parent stage '{top_stage_name}')."
            findings.append({
                "category": cat,
                "severity": "medium",
                "stage_name": top_stage_name,
                "task_name": top_task.get("name") if top_task else None,
                "recommendation": rec_text,
                "evidence": evidence,
            })

    return findings


class AIService:
    def analyze(self, pipeline_id: int, days: int):
        settings = get_settings()
        if not settings.sql_connection_string:
            raise ServiceConfigError("SQL_CONNECTION_STRING is not configured.")

        repo = AlertRepository(settings.sql_connection_string)
        run_count = repo.count_runs(pipeline_id, days=days)
        if run_count < settings.min_history_runs:
            return {
                "pipeline_id": pipeline_id,
                "findings": [],
                "message": f"Not enough completed run history. Found {run_count} completed runs, but {settings.min_history_runs} are required for AI analysis.",
            }

        if not settings.azure_openai_endpoint or not settings.azure_openai_deployment:
            raise ServiceConfigError("Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT in .env.")

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
