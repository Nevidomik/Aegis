"""FastAPI application for the Aegis UI service."""

from fastapi import FastAPI

from ui_service.routes import router

app = FastAPI(title="Aegis UI Service")
app.include_router(router)
