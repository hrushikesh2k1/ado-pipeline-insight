import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.security import EasyAuthGate, RequestSizeLimit, SecurityHeaders

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.enable_api_docs
    app = FastAPI(
        title="ADO Pipeline Insight API",
        version="1.0.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    # Middleware added last is outermost: headers wrap everything, then the size limit, then CORS, then the auth gate.
    if settings.require_easy_auth:
        app.add_middleware(EasyAuthGate)
    if "*" in settings.cors_origins:
        logging.warning("Ignoring '*' in CORS_ORIGINS; list explicit origins instead.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    app.add_middleware(RequestSizeLimit, max_bytes=settings.max_request_bytes)
    app.add_middleware(SecurityHeaders, csp=not docs)
    app.include_router(router)

    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/")
    def root():
        index = frontend_dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"name": "ADO Pipeline Insight API"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"), port=port)
