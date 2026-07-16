from backend_service.main import app
from fastapi import FastAPI


def test_application_starts_with_liveness_route() -> None:
    assert isinstance(app, FastAPI)
    assert "/health/live" in app.openapi()["paths"]
