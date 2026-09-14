/* V6 self-service connection metadata. Secrets are never stored here. */
IF OBJECT_ID('dbo.ado_connections','U') IS NULL
BEGIN
    CREATE TABLE dbo.ado_connections (
        connection_id UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        organization_name NVARCHAR(256) NOT NULL,
        project_name NVARCHAR(256) NULL,
        pipeline_id INT NULL,
        pipeline_name NVARCHAR(256) NULL,
        created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        last_ingested_at DATETIME2 NULL,
        is_enabled BIT NOT NULL DEFAULT 1
    );
END
GO
CREATE INDEX IX_ado_connections_scope ON dbo.ado_connections(organization_name, project_name, pipeline_id);
GO
