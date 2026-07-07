"""FastAPI application factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_documents import router as documents_router
from app.api.routes_treaties import router as treaties_router
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReIn — Reinsurance Treaty Parser",
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

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
