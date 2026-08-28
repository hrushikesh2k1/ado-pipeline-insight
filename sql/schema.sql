CREATE TABLE dbo.pipelines (
    pipeline_id INT NOT NULL PRIMARY KEY,
    pipeline_name NVARCHAR(256) NOT NULL,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
CREATE OR ALTER PROCEDURE dbo.UpsertPipeline @pipeline_id INT, @pipeline_name NVARCHAR(256) AS
MERGE dbo.pipelines AS target USING (SELECT @pipeline_id AS pipeline_id, @pipeline_name AS pipeline_name) source ON target.pipeline_id = source.pipeline_id
WHEN MATCHED THEN UPDATE SET pipeline_name = source.pipeline_name
WHEN NOT MATCHED THEN INSERT (pipeline_id, pipeline_name) VALUES (source.pipeline_id, source.pipeline_name);
GO
CREATE TABLE dbo.pipeline_runs (
    run_id INT NOT NULL PRIMARY KEY, pipeline_id INT NOT NULL REFERENCES dbo.pipelines(pipeline_id),
    queue_time DATETIME2 NULL, start_time DATETIME2 NULL, finish_time DATETIME2 NULL, result NVARCHAR(32) NULL
);
CREATE TABLE dbo.pipeline_stages (
    id BIGINT IDENTITY PRIMARY KEY, run_id INT NOT NULL REFERENCES dbo.pipeline_runs(run_id), record_id NVARCHAR(64) NOT NULL,
    stage_name NVARCHAR(256) NOT NULL, agent_name NVARCHAR(256) NULL, start_time DATETIME2 NULL, finish_time DATETIME2 NULL,
    duration_seconds FLOAT NULL, result NVARCHAR(32) NULL, retry_count INT NOT NULL DEFAULT 0, failure_log_excerpt NVARCHAR(4000) NULL,
    CONSTRAINT UQ_pipeline_stages_run_record UNIQUE(run_id, record_id)
);
CREATE TABLE dbo.pipeline_jobs (
    id BIGINT IDENTITY PRIMARY KEY, run_id INT NOT NULL REFERENCES dbo.pipeline_runs(run_id), record_id NVARCHAR(64) NOT NULL,
    stage_name NVARCHAR(256) NULL, job_name NVARCHAR(256) NOT NULL, agent_name NVARCHAR(256) NULL, start_time DATETIME2 NULL, finish_time DATETIME2 NULL,
    duration_seconds FLOAT NULL, result NVARCHAR(32) NULL, retry_count INT NOT NULL DEFAULT 0, failure_log_excerpt NVARCHAR(4000) NULL,
    CONSTRAINT UQ_pipeline_jobs_run_record UNIQUE(run_id, record_id)
);
CREATE TABLE dbo.pipeline_tasks (
    id BIGINT IDENTITY PRIMARY KEY, run_id INT NOT NULL REFERENCES dbo.pipeline_runs(run_id), record_id NVARCHAR(64) NOT NULL,
    stage_name NVARCHAR(256) NULL, job_name NVARCHAR(256) NULL, task_name NVARCHAR(256) NOT NULL, agent_name NVARCHAR(256) NULL,
    start_time DATETIME2 NULL, finish_time DATETIME2 NULL, duration_seconds FLOAT NULL, result NVARCHAR(32) NULL,
    retry_count INT NOT NULL DEFAULT 0, failure_log_excerpt NVARCHAR(4000) NULL,
    CONSTRAINT UQ_pipeline_tasks_run_record UNIQUE(run_id, record_id)
);
CREATE TABLE dbo.ai_recommendations (
    id BIGINT IDENTITY PRIMARY KEY, pipeline_id INT NOT NULL REFERENCES dbo.pipelines(pipeline_id), category NVARCHAR(64) NOT NULL,
    severity NVARCHAR(16) NOT NULL, stage_name NVARCHAR(256) NOT NULL, task_name NVARCHAR(256) NULL,
    recommendation NVARCHAR(2000) NOT NULL, evidence NVARCHAR(2000) NOT NULL, generated_at DATETIME2 NOT NULL
);
CREATE INDEX IX_pipeline_runs_pipeline_start ON dbo.pipeline_runs(pipeline_id, start_time);
CREATE INDEX IX_pipeline_stages_run_start ON dbo.pipeline_stages(run_id, start_time);
CREATE INDEX IX_pipeline_jobs_run_start ON dbo.pipeline_jobs(run_id, start_time);
CREATE INDEX IX_pipeline_tasks_run_start ON dbo.pipeline_tasks(run_id, start_time);
CREATE INDEX IX_ai_recommendations_pipeline_generated ON dbo.ai_recommendations(pipeline_id, generated_at DESC);