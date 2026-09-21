# Local development

The recommended development setup runs FastAPI on port 8000 and React on port 5173.

Terminal 1:

```powershell
.\scripts\start-backend.ps1
```

Terminal 2:

```powershell
.\scripts\start-frontend.ps1
```

Open `http://127.0.0.1:5173`.

Vite proxies `/api` to `http://127.0.0.1:8000`.

FastAPI docs are at `http://127.0.0.1:8000/docs`.

For a single-process check after a React build:

```powershell
.\scripts\build.ps1
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000
```

The single process serves React from `frontend/dist`.
