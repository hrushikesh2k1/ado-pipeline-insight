import logging
from collections.abc import Callable

from core.ado_client import AzureDevOpsClient
from core.db import AlertRepository, build_analysis_summary
from core.openai_client import PipelineRecommendationClient
from app.core.config import get_settings
from app.core.db import fetch_one
from app.core.errors import ServiceConfigError
from app.services.failure_kind import best_error_line
from app.services.finding_quality import (
    HIGH_FAILURE_PCT,
    HIGH_RETRY_PCT,
    adopt_causes,
    impact_kind,
    measured_impact,
    norm as _norm,
    normalize_findings,
    order_and_cap,
    severity_for,
    task_stats,
)
from app.services.pipeline_yaml import (
    CATEGORY_EXAMPLES,
    YamlContext,
    apply_yaml_context,
    cache_remediation,
    enforce_retry_policy,
    fetch_pipeline_yaml,
    retry_remediation,
    validate_model_snippets,
    yaml_fence,
    yaml_for_prompt,
)
from app.services.root_causes import identify_cause

logger = logging.getLogger(__name__)
MAX_FINDINGS = 15


def _flaky_finding(stage_name: str, task: dict, ctx: YamlContext | None) -> dict | None:
    """A rule-based finding for a failing step: measured numbers, the cause the error names (or an honest 'not visible'),
    the remediation, and a YAML block to paste. Used when the language model leaves a high-severity step out or is unavailable."""
    fail_pct = float(task.get("failure_rate_pct", 0) or 0)
    retry_pct = float(task.get("retry_rate_pct", 0) or 0)
    err = task.get("error_excerpt")
    if not (fail_pct > 0 or retry_pct > 0 or err):
        return None
    task_name = task.get("name", "Unknown Task")
    cause = identify_cause(err)
    line = best_error_line(err)
    if cause:
        diagnosis = f"Task '{task_name}' failed in {fail_pct:g}% of runs. {cause.diagnosis}"
    elif err:
        diagnosis = f"Task '{task_name}' failed in {fail_pct:g}% of runs. The captured error excerpt shows `{line}`."
    else:
        diagnosis = f"Task '{task_name}' failed in {fail_pct:g}% of runs and experienced {retry_pct:g}% retry rate."
    evidence =f"Failure rate: {fail_pct:g}%, Retry rate: {retry_pct:g}%, Avg duration: {task.get('avg_duration_s', 0):g}s."
    if err:
        evidence += f" Error Log: \"{err}\""
    return {
        "category": "flaky_step",
        "severity": severity_for(fail_pct, retry_pct),
        "stage_name": stage_name,
        "task_name": task_name,
        "recommendation": (f"**Diagnosis**: {diagnosis}\n**Remediation**: {retry_remediation(task_name, ctx, err, retry_pct > 0)}\n"
                           f"**Impact**: {measured_impact(fail_pct, retry_pct, impact_kind(err, retry_pct))}"),
        "evidence": evidence,
    }


def _slow_step_finding(top_stage: dict, ctx: YamlContext | None) -> dict | None:
    top_stage_name = top_stage.get("name", "Unknown Stage")
    stage_avg = float(top_stage.get("avg_duration_s", 0) or 0)
    tasks = top_stage.get("tasks") or []
    top_task = max(tasks, key=lambda t: t.get("avg_duration_s", 0) or 0) if tasks else None
    target = top_task.get("name") if top_task else top_stage_name
    task_avg = float(top_task.get("avg_duration_s", 0) or 0) if top_task else stage_avg
    pct = float(top_task.get("pct_of_parent_duration", 0) or 0) if top_task else 100.0
    is_cacheable = any(kw in target.lower() for kw in ("restore", "install", "build", "cache", "download", "pull"))
    mins = round(task_avg / 60, 1)
    diagnosis = f"'{target}' accounts for {pct:g}% of '{top_stage_name}' execution time ({task_avg:g}s average)."
    category = "bottleneck"
    if is_cacheable:
        remediation = cache_remediation(target, None, ctx)
        if remediation is None:
            return None  # the job already caches: there is nothing to recommend
        category = "caching_opportunity"
        impact = f"Dependency downloads are the usual cost here; a warm cache can save part of the ~{mins} minutes this step takes per run."
    else:
        remediation = (f"Look at what '{target}' waits on (network, queue or a slow command); the measurements show where the time goes "
                       "but not why. If its work is independent of the other steps, running it in a parallel job shortens the stage.\n\n"
                       + yaml_fence(CATEGORY_EXAMPLES["bottleneck"]))
        impact = f"This step is the largest share of the stage (~{mins} minutes per run)."
    return {
        "category": category,
        "severity": "medium",
        "stage_name": top_stage_name,
        "task_name": top_task.get("name") if top_task else None,
        "recommendation": f"**Diagnosis**: {diagnosis}\n**Remediation**: {remediation}\n**Impact**: {impact}",
        "evidence": f"Duration: {task_avg:g}s ({pct:g}% of parent stage '{top_stage_name}').",
    }


def _telemetry_fallback(summary: dict, ctx: YamlContext | None = None) -> list[dict]:
    """Rule-based findings when the language model is unavailable. Advice names only what the data and the pipeline
    files actually show; when they could not be read, the advice says so and any snippet is labelled an example."""
    stages = summary.get("stages") or []
    findings: list[dict] = []
    for stage in stages:
        for task in stage.get("tasks") or []:
            finding = _flaky_finding(stage.get("name", "Unknown Stage"), task, ctx)
            if finding:
                findings.append(finding)
            if len(findings) >= 2:
                break
        if len(findings) >= 2:
            break

    if stages:
        top_stage = max(stages, key=lambda s: s.get("avg_duration_s", 0) or 0)
        slow = _slow_step_finding(top_stage, ctx)
        already = any(f["stage_name"] == slow["stage_name"] and f["task_name"] == slow["task_name"] for f in findings) if slow else True
        if slow and not already:
            findings.append(slow)
    return findings


def _task_rates(task: dict) -> tuple[float, float]:
    return float(task.get("failure_rate_pct", 0) or 0), float(task.get("retry_rate_pct", 0) or 0)


def prioritize_summary(summary: dict) -> dict:
    """Sort the measurements the model sees by failure rate, worst first, so the steps that matter most come first."""
    def stage_key(stage: dict) -> tuple[float, float]:
        return -float(stage.get("failure_rate_pct", 0) or 0), -float(stage.get("avg_duration_s", 0) or 0)

    def task_key(task: dict) -> tuple[float, float, float]:
        fail, retry = _task_rates(task)
        return -fail, -retry, -float(task.get("avg_duration_s", 0) or 0)

    stages = [{**stage, "tasks": sorted(stage.get("tasks") or [], key=task_key)} for stage in summary.get("stages") or []]
    return {**summary, "stages": sorted(stages, key=stage_key)}


def ensure_coverage(findings: list[dict], summary: dict, ctx: YamlContext | None) -> tuple[list[dict], int]:
    """Every step above the 'high' thresholds gets a finding, whatever the model chose to leave out.

    Returns (the findings plus the rule-based ones added for the steps the model skipped, how many were added)."""
    stats = task_stats(summary)
    name_counts: dict[str, int] = {}
    for _stage, task_name in stats:
        name_counts[task_name] = name_counts.get(task_name, 0) + 1
    flaky = [f for f in findings if f.get("category") == "flaky_step"]
    covered_pairs = {(_norm(f.get("stage_name")), _norm(f.get("task_name"))) for f in flaky}
    covered_names = {_norm(f.get("task_name")) for f in flaky}

    added: list[dict] = []
    for (stage_key, task_key), stat in sorted(stats.items(), key=lambda kv: -kv[1]["fail"]):
        if (stat["fail"] < HIGH_FAILURE_PCT and stat["retry"] < HIGH_RETRY_PCT) or (stage_key, task_key) in covered_pairs:
            continue
        if name_counts[task_key] == 1 and task_key in covered_names:  # the model named the step but spelled the stage differently
            continue
        finding = _flaky_finding(stat["stage"], stat["raw"], ctx)
        if finding:
            added.append(finding)
    return [*findings, *added], len(added)


class AIService:
    @staticmethod
    def _load_yaml(pipeline_id: int, resolve_pat: Callable[[str], str | None] | None) -> YamlContext:
        """Read the pipeline's real YAML so advice can name the exact step; never fails the analysis."""
        if resolve_pat is None:
            return YamlContext(False, "no Azure DevOps access was provided")
        try:
            row = fetch_one("SELECT organization_name, project_name FROM dbo.pipelines WHERE pipeline_id = ?", (pipeline_id,))
        except Exception:
            return YamlContext(False, "the pipeline's organization and project could not be looked up")
        if not row or not row.get("organization_name") or not row.get("project_name"):
            return YamlContext(False, "the pipeline's organization and project are not known")
        token = resolve_pat(row["organization_name"])
        if not token:
            return YamlContext(False, "no Azure DevOps token is available for this organization")
        return fetch_pipeline_yaml(AzureDevOpsClient(row["organization_name"], token), row["project_name"], pipeline_id)

    @staticmethod
    def _ask_model(client: PipelineRecommendationClient, summary: dict) -> tuple[list[dict], bool]:
        """The model's findings. If the request carrying the full YAML is rejected (for example too large for the deployment's context
        window), it is repeated once without the YAML. Returns (findings, whether the YAML had to be left out)."""
        try:
            return [f.__dict__ for f in client.recommend(summary).findings], False
        except Exception:
            if "pipeline_yaml" not in summary:
                raise
            logger.warning("Model request with the pipeline YAML failed; retrying without it")
            return [f.__dict__ for f in client.recommend({k: v for k, v in summary.items() if k != "pipeline_yaml"}).findings], True

    def analyze(self, pipeline_id: int, days: int, resolve_pat: Callable[[str], str | None] | None = None):
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

        summary = prioritize_summary(build_analysis_summary(repo.get_pipeline_metrics(pipeline_id, days=days), window_days=days))
        ctx = self._load_yaml(pipeline_id, resolve_pat)
        prompt_yaml = yaml_for_prompt(ctx)
        if prompt_yaml:
            summary["pipeline_yaml"] = prompt_yaml
        client = PipelineRecommendationClient(
            settings.azure_openai_endpoint,
            settings.azure_openai_deployment,
            settings.azure_openai_api_version,
            settings.azure_openai_api_key or None,
        )
        model_findings, yaml_dropped = self._ask_model(client, summary)
        findings = adopt_causes(model_findings, summary)  # a cause the error text shows replaces the model's own diagnosis and remediation
        findings, skipped = apply_yaml_context(findings, ctx)  # drops the model's snippets for steps it cannot have seen
        findings = enforce_retry_policy(findings, summary, ctx)  # then our corrections, which carry their own labelled blocks
        findings = validate_model_snippets(findings, ctx)
        if not model_findings:
            findings = _telemetry_fallback(summary, ctx)
        findings, added = ensure_coverage(findings, summary, ctx)
        findings, merged = normalize_findings(findings, summary, ctx)
        findings, omitted = order_and_cap(findings, summary, MAX_FINDINGS)
        repo.upsert_recommendations(pipeline_id, findings)

        message = "AI analysis completed." if findings else "No recommendations could be generated from the available telemetry."
        if ctx.ok:
            message += f" Based on {ctx.path} ({ctx.branch})"
            message += f" and {len(ctx.facts.files) - 1} template file(s)." if ctx.facts and len(ctx.facts.files) > 1 else "."
            if ctx.unresolved:
                message += " Templates that could not be read: " + "; ".join(ctx.unresolved_with_reasons[:5]) + "."
            if yaml_dropped:
                message += " The AI request carrying the full YAML was rejected, so it was repeated without the YAML."
        else:
            message += f" Pipeline YAML not used: {ctx.reason}."
        if skipped:
            message += " Skipped, already in place: " + "; ".join(skipped) + "."
        if added:
            message += f" {added} failing step(s) above the high-severity thresholds were left out by the AI and added by the rule-based check."
        if merged:
            message += f" {merged} duplicate finding(s) for the same step or the same error were merged into the one that lists them."
        if omitted:
            message += f" {omitted} lower-priority finding(s) are not shown (limit {MAX_FINDINGS})."
        return {"pipeline_id": pipeline_id, "findings": findings, "message": message}
