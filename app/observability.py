"""MLflow tracing + experiment helpers.

MLflow is an optional dependency: it is imported lazily inside the functions
below (never at module import time), so the app runs normally whether or not
mlflow is installed, and whether or not tracing is enabled.
"""

from contextlib import contextmanager
import logging

from app.config import get_settings


logger = logging.getLogger(__name__)


def init_mlflow() -> None:
    """Initialize MLFlow if enabled in settings."""
    settings = get_settings()
    if not settings.mlflow_enabled:
        return

    try:
        import mlflow
        import mlflow.langchain  # noqa: F401 — needed for autolog()

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment)
        mlflow.langchain.autolog()
    except Exception:
        logger.exception("MLflow initialization failed; continuing without tracing")


@contextmanager
def run(name: str):
    """Wrap a block in an MLflow run when tracing is enabled."""
    settings = get_settings()
    if not settings.mlflow_enabled:
        yield
        return
    init_mlflow()
    import mlflow
    with mlflow.start_run(run_name=name) as active:
        yield active


def log_reindex(*, provider, model_id, dim, chunks, chars, duration_s) -> None:
    """Log embedding-index build metrics (no content, just counts/latency).

    Lets you compare embedding models on your own corpus. No-op when MLflow is
    disabled or not installed.
    """
    settings = get_settings()
    if not settings.mlflow_enabled:
        return
    try:
        import mlflow

        mlflow.log_params({
            "embeddings_provider": provider,
            "embeddings_model": model_id,
            "embedding_dim": dim,
        })
        mlflow.log_metrics({
            "indexed_chunks": chunks,
            "chars_embedded": chars,
            "duration_s": round(duration_s, 2),
            "chunks_per_s": round(chunks / duration_s, 2) if duration_s else 0.0,
        })
    except Exception:
        logger.exception("MLflow log_reindex failed; continuing")

