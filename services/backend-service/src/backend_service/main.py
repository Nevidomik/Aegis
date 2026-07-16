"""FastAPI application for the Aegis backend service."""

from fastapi import APIRouter, FastAPI

router = APIRouter()


@router.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Confirm that the backend service process is running."""
    return {"status": "ok"}


app = FastAPI(title="Aegis Backend Service")
app.include_router(router)
