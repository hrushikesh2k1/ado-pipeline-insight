from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from backend.app.api.routes import router
from backend.app.core.config import get_settings

app = FastAPI(title="ADO Pipeline Insight API", version="1.0.0", docs_url="/docs", redoc_url="/redoc")
settings = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

@app.get("/")
def root():
    index = frontend_dist / "index.html"
    if index.exists():
        from fastapi.responses import FileResponse
        return FileResponse(index)
    return {"name": "ADO Pipeline Insight API", "docs": "/docs"}
