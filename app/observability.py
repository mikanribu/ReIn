"""MLflow tracing + experiment helpers."""

from contextlib import contextmanager
import logging
import mlflow.langchain

from app.config import get_settings


logger = logging.getLogger(__name__)


def init_mlflow() -> None:
    """Initialize MLFlow if enabled in settings."""
    settings = get_settings()
    if not settings.mlflow_enabled:
        return

    try:
        import mlflow

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
    with mlflow.start_run(run_name=name) as run:
        print(f"MLflow run started: {run.info.run_id}")
        yield run

