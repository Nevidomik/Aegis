"""Pydantic contracts for Backend checks and History persistence."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CheckRequest(BaseModel):
    """Public request to check one IP address."""

    model_config = ConfigDict(extra="forbid")

    ip_address: str = Field(min_length=1, max_length=100)
    max_age_days: int = Field(default=30, ge=1, le=365)


class ReputationResult(BaseModel):
    """Normalized provider result before persistence."""

    model_config = ConfigDict(extra="forbid")

    ip_address: str
    ip_version: int
    is_public: bool
    is_whitelisted: bool | None
    abuse_confidence_score: int = Field(ge=0, le=100)
    country_code: str | None
    usage_type: str | None
    isp: str | None
    domain: str | None
    total_reports: int = Field(ge=0)
    num_distinct_users: int = Field(ge=0)
    last_reported_at: datetime | None
    source: str


class HistoryCheckCreate(ReputationResult):
    """Normalized check sent to History."""

    request_id: UUID
    max_age_days: int = Field(ge=1, le=365)
    checked_at: datetime


class CheckResponse(HistoryCheckCreate):
    """Persisted check returned to the public caller."""

    history_id: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
