# ADO Pipeline Insight Architecture

## Runtime

React + TypeScript is the browser application. FastAPI is the API boundary. React never connects directly to Azure SQL.

Azure SQL stores normalized pipeline, run, stage, job, task and recommendation data. Azure Functions handle ingestion and background analysis. Azure DevOps remains the source of pipeline telemetry. Azure OpenAI receives structured analytics and returns validated findings.

## Data flow

Azure DevOps -> Service Hook -> Azure Function -> Azure DevOps REST API -> Azure SQL

React -> FastAPI -> Repository -> Azure SQL

FastAPI analyze endpoint -> analytics summary -> Azure OpenAI -> validated findings -> Azure SQL

## Deployment principle

The application is configuration driven. Organization, project and pipeline values are discovered from stored telemetry. Credentials stay server side. Local development uses `.env`. Azure deployment should use Key Vault and Managed Identity.
