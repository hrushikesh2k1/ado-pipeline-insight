CREATE OR ALTER VIEW dbo.vw_pipeline_duration_trend AS
SELECT CAST(r.start_time AS date) AS run_date, r.pipeline_id, p.pipeline_name, s.stage_name,
       AVG(s.duration_seconds) AS avg_duration_seconds,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY s.duration_seconds) OVER (PARTITION BY CAST(r.start_time AS date), r.pipeline_id, s.stage_name) AS p90_duration_seconds
FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id JOIN dbo.pipeline_stages s ON s.run_id = r.run_id
GROUP BY CAST(r.start_time AS date), r.pipeline_id, p.pipeline_name, s.stage_name;
GO
CREATE OR ALTER VIEW dbo.vw_task_duration_trend AS
SELECT CAST(r.start_time AS date) AS run_date, r.pipeline_id, p.pipeline_name, t.stage_name, t.job_name, t.task_name,
       AVG(t.duration_seconds) AS avg_duration_seconds, AVG(100.0 * t.duration_seconds / NULLIF(s.duration_seconds, 0)) AS pct_of_parent_duration
FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id JOIN dbo.pipeline_tasks t ON t.run_id = r.run_id
LEFT JOIN dbo.pipeline_stages s ON s.run_id = r.run_id AND s.stage_name = t.stage_name
GROUP BY CAST(r.start_time AS date), r.pipeline_id, p.pipeline_name, t.stage_name, t.job_name, t.task_name;
GO
CREATE OR ALTER VIEW dbo.vw_flaky_jobs AS
SELECT r.pipeline_id, p.pipeline_name, j.stage_name, j.job_name,
       100.0 * AVG(CASE WHEN j.retry_count > 0 THEN 1.0 ELSE 0.0 END) AS retry_rate_pct
FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id JOIN dbo.pipeline_jobs j ON j.run_id = r.run_id
GROUP BY r.pipeline_id, p.pipeline_name, j.stage_name, j.job_name;
GO
CREATE OR ALTER VIEW dbo.vw_flaky_tasks AS
SELECT r.pipeline_id, p.pipeline_name, t.stage_name, t.job_name, t.task_name,
       100.0 * AVG(CASE WHEN t.retry_count > 0 THEN 1.0 ELSE 0.0 END) AS retry_rate_pct
FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id JOIN dbo.pipeline_tasks t ON t.run_id = r.run_id
GROUP BY r.pipeline_id, p.pipeline_name, t.stage_name, t.job_name, t.task_name;
GO
CREATE OR ALTER VIEW dbo.vw_latest_ai_recommendations AS
SELECT id, pipeline_id, category, severity, stage_name, task_name, recommendation, evidence, generated_at
FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY pipeline_id, stage_name, ISNULL(task_name, ''), category ORDER BY generated_at DESC) AS row_number FROM dbo.ai_recommendations) latest
WHERE row_number = 1;
GO
CREATE OR ALTER VIEW dbo.vw_dora_metrics AS
SELECT 
    CAST(r.start_time AS date) AS metric_date,
    r.pipeline_id,
    p.pipeline_name,
    p.organization_name,
    p.project_name,
    COUNT(*) AS total_runs_count,
    SUM(CASE WHEN r.result IN ('succeeded', 'partiallySucceeded') THEN 1 ELSE 0 END) AS successful_runs_count,
    SUM(CASE WHEN r.result = 'failed' THEN 1 ELSE 0 END) AS failed_runs_count,
    CAST(100.0 * SUM(CASE WHEN r.result = 'failed' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS DECIMAL(5, 2)) AS change_failure_rate_pct,
    AVG(DATEDIFF(second, r.queue_time, r.finish_time)) AS avg_lead_time_seconds,
    AVG(DATEDIFF(second, r.start_time, r.finish_time)) AS avg_execution_duration_seconds
FROM dbo.pipeline_runs r
JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id
WHERE r.start_time IS NOT NULL
GROUP BY CAST(r.start_time AS date), r.pipeline_id, p.pipeline_name, p.organization_name, p.project_name;
GO
CREATE OR ALTER VIEW dbo.vw_agent_pool_saturation AS
SELECT 
    CAST(j.start_time AS date) AS metric_date,
    COALESCE(j.pool_name, 'Default') AS pool_name,
    COUNT(DISTINCT j.run_id) AS total_runs,
    COUNT(*) AS total_jobs,
    AVG(j.duration_seconds) AS avg_job_duration_seconds,
    AVG(DATEDIFF(second, r.queue_time, j.start_time)) AS avg_queue_wait_seconds,
    COUNT(DISTINCT j.agent_name) AS active_agents_count
FROM dbo.pipeline_jobs j
JOIN dbo.pipeline_runs r ON r.run_id = j.run_id
WHERE j.start_time IS NOT NULL
GROUP BY CAST(j.start_time AS date), COALESCE(j.pool_name, 'Default');