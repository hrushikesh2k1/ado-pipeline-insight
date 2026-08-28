CREATE OR ALTER VIEW dbo.vw_pipeline_duration_trend AS
SELECT CAST(r.start_time AS date) AS run_date, r.pipeline_id, p.pipeline_name, s.stage_name,
       AVG(s.duration_seconds) AS avg_duration_seconds,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY s.duration_seconds) OVER (PARTITION BY CAST(r.start_time AS date), r.pipeline_id, s.stage_name) AS p90_duration_seconds
FROM dbo.pipeline_runs r JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id JOIN dbo.pipeline_stages s ON s.run_id = r.run_id
GROUP BY CAST(r.start_time AS date), r.pipeline_id, p.pipeline_name, s.stage_name, s.duration_seconds;
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