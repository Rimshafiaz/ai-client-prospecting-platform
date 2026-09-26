import logging
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.routes.company_discovery import discover_companies_endpoint
from app.integrations.geocoding import GeocodingProviderError
from app.integrations.open_places import OpenPlacesProviderError
from app.integrations.serper import SerperProviderError
from app.schemas.company_discovery import CompanyDiscoveryRequest


@pytest.mark.parametrize(
    ("error", "log_message", "detail"),
    [
        (
            GeocodingProviderError("Location provider returned HTTP 429."),
            "geocoding provider failed",
            "Location lookup is temporarily unavailable. Please try again.",
        ),
        (
            OpenPlacesProviderError("Open Places quota is exhausted."),
            "Open Places provider failed",
            "Local business search is temporarily unavailable. Please try again.",
        ),
        (
            SerperProviderError("Serper quota or rate limit was reached."),
            "Serper provider failed",
            "Web search is temporarily unavailable. Please try again.",
        ),
    ],
)
def test_discovery_provider_failures_are_classified_and_logged(
    error, log_message, detail, caplog
):
    criteria = CompanyDiscoveryRequest(
        offering="Website development",
        desired_outcome="Find restaurant prospects",
        business_category="Restaurants & cafes",
        location="Faisalabad, Pakistan",
    )

    with (
        patch(
            "app.api.routes.company_discovery.discover_companies",
            side_effect=error,
        ),
        caplog.at_level(logging.ERROR),
        pytest.raises(HTTPException) as raised,
    ):
        discover_companies_endpoint(criteria, current_user=None)

    assert raised.value.status_code == 503
    assert raised.value.detail == detail
    assert log_message in caplog.text
    assert str(error) in caplog.text
