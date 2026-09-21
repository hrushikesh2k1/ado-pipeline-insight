/*
  RESET APPLICATION DATA ONLY
  --------------------------------
  This does NOT drop or alter the schema.
  Run this once before the first clean end-to-end test.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRANSACTION;

DELETE FROM dbo.ai_recommendations;
DELETE FROM dbo.pipeline_tasks;
DELETE FROM dbo.pipeline_jobs;
DELETE FROM dbo.pipeline_stages;
DELETE FROM dbo.pipeline_runs;
DELETE FROM dbo.pipelines;

IF OBJECT_ID('dbo.ado_connections', 'U') IS NOT NULL
    DELETE FROM dbo.ado_connections;

COMMIT TRANSACTION;

SELECT
    (SELECT COUNT(*) FROM dbo.pipelines) AS pipelines,
    (SELECT COUNT(*) FROM dbo.pipeline_runs) AS pipeline_runs,
    (SELECT COUNT(*) FROM dbo.pipeline_stages) AS stages,
    (SELECT COUNT(*) FROM dbo.pipeline_jobs) AS jobs,
    (SELECT COUNT(*) FROM dbo.pipeline_tasks) AS tasks,
    (SELECT COUNT(*) FROM dbo.ai_recommendations) AS recommendations;
