"""FastAPI application factory."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_analytics import router as analytics_router
from app.api.routes_chat import router as chat_router
from app.api.routes_documents import router as documents_router
from app.api.routes_kb import router as kb_router
from app.api.routes_treaties import router as treaties_router
from app.database import init_db

from app.observability import init_mlflow

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_mlflow()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="TreatyIQ — Reinsurance Treaty Parser",
        description=(
            "Parses reinsurance treaties with LangChain + Claude, maps every "
            "extracted data point with its source quote and confidence for human "
            "review, stores approved values for downstream calculation, and keeps "
            "a hash-chained audit trail of every change. Amendments (from an "
            "adjustment document or manual) always create a new reviewable version."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(documents_router)
    app.include_router(treaties_router)
    app.include_router(chat_router)
    app.include_router(analytics_router)
    app.include_router(kb_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def ui() -> FileResponse:
        """The review web UI (single-page app)."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
