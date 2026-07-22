from copy import deepcopy
from typing import Any, cast

import pytest
from history_service.schemas import (
    ProviderBlacklistRequest,
    ProviderBlacklistResponse,
    ProviderErrorResponse,
)
from pydantic import ValidationError

from .test_provider_blacklist_client import REQUEST_ID, valid_blacklist_response


@pytest.mark.parametrize(
    "values",
    [
        {"confidence_minimum": -1},
        {"confidence_minimum": 101},
        {"limit": 0},
        {"limit": 1001},
        {"limit": "1000"},
        {"unknown": 1},
    ],
)
def test_blacklist_request_contract_is_strict(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProviderBlacklistRequest.model_validate(values)


def test_blacklist_response_rejects_unknown_nested_fields() -> None:
    payload = valid_blacklist_response()
    payload["rate_limit"]["raw_header"] = "secret"

    with pytest.raises(ValidationError):
        ProviderBlacklistResponse.model_validate(payload)


def test_provider_error_contract_accepts_only_normalized_retry_metadata() -> None:
    payload = {
        "error": {
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "safe",
            "request_id": REQUEST_ID,
            "retry": {
                "retry_after_seconds": 60,
                "reset_at": "2026-07-23T00:00:00Z",
            },
        }
    }
    result = ProviderErrorResponse.model_validate(payload)
    assert result.error.retry is not None
    assert result.error.retry.retry_after_seconds == 60

    invalid = cast(dict[str, Any], deepcopy(payload))
    invalid["error"]["retry"]["raw_header"] = "unexpected"
    with pytest.raises(ValidationError):
        ProviderErrorResponse.model_validate(invalid)
