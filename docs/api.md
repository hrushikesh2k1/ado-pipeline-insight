# API contract

GET /api/v1/health
GET /api/v1/options
GET /api/v1/summary?pipeline_id=&days=
GET /api/v1/trends?pipeline_id=&days=
GET /api/v1/runs?pipeline_id=&page=&page_size=&status=
GET /api/v1/runs/{run_id}/timeline
GET /api/v1/runs/{run_id}/logs
GET /api/v1/pipelines/{pipeline_id}/recommendations
POST /api/v1/pipelines/{pipeline_id}/analyze
GET /api/v1/pools?days=

OpenAPI is available at `/docs` when FastAPI is running.
