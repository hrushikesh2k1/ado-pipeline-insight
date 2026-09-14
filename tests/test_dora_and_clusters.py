from datetime import datetime, timezone
from core.models import DoraMetric, FailureCluster, AgentPoolStat, YamlDiffProposal


def test_dora_metric_model_instantiation():
    dora = DoraMetric(
        metric_date="2026-09-04",
        pipeline_id=101,
        pipeline_name="backend-api",
        organization_name="Contoso",
        project_name="Core",
        total_runs_count=20,
        successful_runs_count=18,
        failed_runs_count=2,
        change_failure_rate_pct=10.0,
        avg_lead_time_seconds=320.5,
        avg_execution_duration_seconds=280.0,
    )
    assert dora.pipeline_name == "backend-api"
    assert dora.change_failure_rate_pct == 10.0
    assert dora.successful_runs_count + dora.failed_runs_count == 20


def test_failure_cluster_model_instantiation():
    now = datetime.now(timezone.utc)
    cluster = FailureCluster(
        cluster_id="cluster-ssl-01",
        signature_hash="hash-1234",
        error_pattern="SSLHandshakeTimeout: Remote host closed connection",
        first_seen_at=now,
        last_seen_at=now,
        occurrences_count=15,
        severity="high",
        root_cause_summary="Proxy certificate expired on self-hosted runners",
        suggested_yaml_diff="- task: DotNetCoreCLI@2\n+ env:\n+   DOTNET_SYSTEM_NET_HTTP_USESOCKETSHTTPHANDLER: 0",
    )
    assert cluster.severity == "high"
    assert cluster.occurrences_count == 15
    assert "DOTNET_SYSTEM_NET_HTTP" in cluster.suggested_yaml_diff


def test_agent_pool_stat_model_instantiation():
    stat = AgentPoolStat(
        metric_date="2026-09-04",
        pool_name="EastUS-ScaleSet-Linux",
        total_runs=45,
        total_jobs=90,
        avg_job_duration_seconds=185.0,
        avg_queue_wait_seconds=12.4,
        active_agents_count=8,
    )
    assert stat.pool_name == "EastUS-ScaleSet-Linux"
    assert stat.active_agents_count == 8


def test_yaml_diff_proposal_model_instantiation():
    proposal = YamlDiffProposal(
        pipeline_id=101,
        pipeline_name="backend-ci",
        target_file="azure-pipelines.yml",
        diff_patch="@@ -1,3 +1,5 @@\n+ - task: Cache@2",
        explanation="Add cache task for npm node_modules",
        estimated_time_saved_seconds=210.0,
    )
    assert proposal.pipeline_id == 101
    assert proposal.estimated_time_saved_seconds == 210.0
