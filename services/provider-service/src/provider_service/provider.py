"""AbuseIPDB reputation client and deterministic test provider."""

from datetime import datetime
from hashlib import sha256
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Literal, Self

import httpx
from fastapi import Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from provider_service.exceptions import (
    AbuseIPDBAuthenticationError,
    AbuseIPDBUnavailableError,
    RateLimitExceededError,
    UpstreamInvalidResponseError,
    UpstreamRequestRejectedError,
    UpstreamTimeoutError,
)
from provider_service.schemas import ReputationResult


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class AbuseIPDBData(BaseModel):
    """Validated data object returned by AbuseIPDB's check endpoint."""

    model_config = ConfigDict(
        alias_generator=lambda name: _to_camel(name), extra="ignore"
    )

    ip_address: StrictStr = Field(min_length=1, max_length=39)
    is_public: StrictBool
    ip_version: Literal[4, 6]
    is_whitelisted: StrictBool | None = None
    abuse_confidence_score: StrictInt = Field(ge=0, le=100)
    country_code: StrictStr | None = Field(default=None, min_length=2, max_length=2)
    usage_type: StrictStr | None = Field(default=None, max_length=100)
    isp: StrictStr | None = Field(default=None, max_length=255)
    domain: StrictStr | None = Field(default=None, max_length=255)
    total_reports: StrictInt = Field(ge=0, le=2_147_483_647)
    num_distinct_users: StrictInt = Field(ge=0, le=2_147_483_647)
    last_reported_at: datetime | None = None

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("last_reported_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("AbuseIPDB timestamps must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_ip_metadata(self) -> Self:
        try:
            address = ip_address(self.ip_address)
        except ValueError as error:
            raise ValueError("AbuseIPDB returned an invalid IP address.") from error
        self.ip_address = str(address)
        if address.version != self.ip_version:
            raise ValueError("AbuseIPDB returned a mismatched IP version.")
        if (
            not self.is_public
            or address.is_loopback
            or address.is_private
            or address.is_multicast
            or address.is_link_local
            or address.is_unspecified
            or not address.is_global
        ):
            raise ValueError("AbuseIPDB returned a non-public result.")
        return self


class AbuseIPDBEnvelope(BaseModel):
    """Top-level AbuseIPDB check response."""

    model_config = ConfigDict(extra="ignore")

    data: AbuseIPDBData


class AbuseIPDBProvider:
    """Perform validated lookups with a lifecycle-owned HTTPX client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def lookup(
        self, address: IPv4Address | IPv6Address, max_age_days: int
    ) -> ReputationResult:
        try:
            response = await self.client.get(
                "/api/v2/check",
                params={
                    "ipAddress": str(address),
                    "maxAgeInDays": max_age_days,
                },
            )
        except httpx.TimeoutException as error:
            raise UpstreamTimeoutError from error
        except httpx.RequestError as error:
            raise AbuseIPDBUnavailableError from error

        self._raise_for_status(response.status_code)
        try:
            envelope = AbuseIPDBEnvelope.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise UpstreamInvalidResponseError from error

        data = envelope.data
        if data.ip_address != str(address):
            raise UpstreamInvalidResponseError
        return ReputationResult(
            ip_address=data.ip_address,
            ip_version=data.ip_version,
            is_public=data.is_public,
            is_whitelisted=data.is_whitelisted,
            abuse_confidence_score=data.abuse_confidence_score,
            country_code=data.country_code,
            usage_type=data.usage_type,
            isp=data.isp,
            domain=data.domain,
            total_reports=data.total_reports,
            num_distinct_users=data.num_distinct_users,
            last_reported_at=data.last_reported_at,
            source="AbuseIPDB",
        )

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            raise AbuseIPDBAuthenticationError
        if status_code == 429:
            raise RateLimitExceededError
        if 400 <= status_code < 500:
            raise UpstreamRequestRejectedError
        if 500 <= status_code < 600:
            raise AbuseIPDBUnavailableError
        raise UpstreamInvalidResponseError


class FakeReputationProvider:
    """Return repeatable reputation data for automated tests only."""

    async def lookup(
        self, address: IPv4Address | IPv6Address, max_age_days: int
    ) -> ReputationResult:
        del max_age_days
        digest = sha256(address.packed).digest()
        score = digest[0] % 101
        total_reports = int.from_bytes(digest[1:3], "big") % 500
        distinct_users = min(total_reports, digest[3] % 100)
        return ReputationResult(
            ip_address=str(address),
            ip_version=address.version,
            is_public=True,
            is_whitelisted=score == 0,
            abuse_confidence_score=score,
            country_code="ZZ",
            usage_type="Fake development data",
            isp="Aegis Fake Provider",
            domain=None,
            total_reports=total_reports,
            num_distinct_users=distinct_users,
            last_reported_at=None,
            source="FakeReputationProvider",
        )


async def get_reputation_provider(request: Request) -> AbuseIPDBProvider:
    """Return the provider created by the application lifespan."""
    return request.app.state.reputation_provider
