from datetime import UTC, datetime

import pytest
from provider_service.schemas import (
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
