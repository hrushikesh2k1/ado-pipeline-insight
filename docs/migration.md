# Migration from Flask dashboard

The existing `web_dashboard` is retained as a reference implementation. It is not part of the new runtime.

| Existing area | New home |
| --- | --- |
| Flask HTML templates | React + TypeScript |
| Inline selector JavaScript | React state + TanStack Query |
| Flask route handlers | FastAPI API routes |
| SQL access from Flask | FastAPI repository layer |
| ADO DevOps ingestion | Azure Functions |
| AI recommendation request | FastAPI orchestration plus Azure Function for background workloads |
| ECharts rendering | React chart component |
| Local settings | `.env` for development, Key Vault in Azure |

The old dashboard remains available under `web_dashboard/` until the new frontend passes end-to-end validation.
