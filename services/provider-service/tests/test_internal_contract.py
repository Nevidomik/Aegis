from datetime import UTC, datetime

import pytest
from provider_service.schemas import (
    InternalBlacklistRequest,
    InternalBlacklistResponse,
    InternalReputationRequest,
    InternalReputationResponse,
)
from pydantic import ValidationError


def test_internal_request_accepts_only_the_strict_normalized_contract() -> None:
    request = InternalReputationRequest(
        ip_address="2606:4700:4700::1111", max_age_days=90
    )

    assert request.model_dump() == {
        "ip_address": "2606:4700:4700::1111",
        "max_age_days": 90,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"ip_address": "2606:4700:4700:0:0:0:0:1111", "max_age_days": 90},
        {"ip_address": "192.168.1.1", "max_age_days": 90},
        {"ip_address": "8.8.8.8", "max_age_days": "90"},
        {"ip_address": "8.8.8.8", "max_age_days": 90, "provider_url": "x"},
    ],
)
def test_internal_request_rejects_noncanonical_or_extra_data(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InternalReputationRequest.model_validate(payload)


def test_internal_response_rejects_application_and_unbounded_fields() -> None:
    valid = {
        "ip_address": "8.8.8.8",
        "ip_version": 4,
        "is_public": True,
        "is_whitelisted": None,
        "abuse_confidence_score": 12,
        "country_code": "US",
        "usage_type": None,
        "isp": "Example ISP",
        "domain": None,
        "total_reports": 7,
        "num_distinct_users": 3,
        "last_reported_at": None,
        "max_age_days": 90,
        "source": "AbuseIPDB",
        "checked_at": datetime(2026, 7, 15, 18, 30, tzinfo=UTC),
    }

    response = InternalReputationResponse.model_validate(valid)
    assert "history_id" not in response.model_dump()
    assert "request_id" not in response.model_dump()

    with pytest.raises(ValidationError):
        InternalReputationResponse.model_validate({**valid, "history_id": 145})

    with pytest.raises(ValidationError):
        InternalReputationResponse.model_validate({**valid, "total_reports": -1})


def test_blacklist_query_defaults_and_bounds() -> None:
    assert InternalBlacklistRequest().model_dump() == {
        "confidence_minimum": 90,
        "limit": 1000,
    }
    assert InternalBlacklistRequest(confidence_minimum=0, limit=1)
    assert InternalBlacklistRequest(confidence_minimum=100, limit=1000)

    with pytest.raises(ValidationError):
        InternalBlacklistRequest(confidence_minimum=-1)
    with pytest.raises(ValidationError):
        InternalBlacklistRequest(confidence_minimum=101)
    with pytest.raises(ValidationError):
        InternalBlacklistRequest(limit=1001)


def test_blacklist_response_rejects_more_than_1000_items() -> None:
    entry = {
        "ip_address": "8.8.8.8",
        "ip_version": 4,
        "abuse_confidence_score": 100,
        "country_code": "US",
        "last_reported_at": None,
    }
    payload = {
        "provider": "AbuseIPDB",
        "generated_at": datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        "fetched_at": datetime(2026, 7, 22, 12, 0, 2, tzinfo=UTC),
        "request": {"confidence_minimum": 90, "limit": 1000},
        "rate_limit": {},
        "items": [entry] * 1001,
    }
    with pytest.raises(ValidationError):
        InternalBlacklistResponse.model_validate(payload)
