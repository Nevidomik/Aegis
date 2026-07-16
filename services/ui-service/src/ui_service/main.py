"""FastAPI application for the Aegis UI service."""

from fastapi import APIRouter, FastAPI

router = APIRouter()


@router.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Confirm that the UI service process is running."""
    return {"status": "ok"}


app = FastAPI(title="Aegis UI Service")
app.include_router(router)
