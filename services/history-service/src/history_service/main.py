"""FastAPI application for the Aegis history service."""

from fastapi import APIRouter, FastAPI

router = APIRouter()


@router.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Confirm that the history service process is running."""
    return {"status": "ok"}


app = FastAPI(title="Aegis History Service")
app.include_router(router)
