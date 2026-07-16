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


class HistoryListQuery(BaseModel):
    """Public pagination and optional IP filtering parameters."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    ip_address: str | None = Field(default=None, min_length=1, max_length=100)


class HistoryListResponse(BaseModel):
    """One validated page returned by History."""

    model_config = ConfigDict(extra="forbid")

    items: list[CheckResponse]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
