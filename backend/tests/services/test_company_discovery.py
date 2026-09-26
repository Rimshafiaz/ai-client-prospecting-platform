from unittest.mock import patch

import pytest

from pydantic import ValidationError

from app.schemas.company_discovery import (
    CompanyDiscoveryRequest,
    DiscoveryObjective,
    ParseDiscoveryRequest,
)
from app.services.company_discovery import (
    check_supported_objective,
    parse_discovery_objective,
)


def objective(*, sectors: list[str] | None = None) -> DiscoveryObjective:
    return DiscoveryObjective(
        goal_type="client_prospecting",
        seller_role="Freelance web developer",
        offering="Website redesign",
        target_sectors=sectors or ["local businesses"],
        target_geographies=["Lahore"],
        search_queries=["local businesses Lahore", "businesses Lahore"],
        fit_rubric="Independent local businesses",
        desired_outcome="Find prospects",
    )


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("Find restaurants in Lahore", "Restaurants & cafes"),
        ("Find cafes in Lahore", "Restaurants & cafes"),
        ("Find dental practices in Lahore", "Dental & selected clinics"),
        ("Find dentists in Lahore", "Dental & selected clinics"),
        ("Find beauty salons in Lahore", "Beauty & wellness"),
    ],
)
def test_parser_normalizes_one_unambiguous_supported_vertical(
    goal: str, expected: str
):
    with patch(
        "app.services.company_discovery.run_goal_parser_task",
        return_value=objective(),
    ):
        parsed = parse_discovery_objective(ParseDiscoveryRequest(goal=goal))

    assert parsed.target_sectors == [expected]
    assert check_supported_objective(parsed, goal) == (True, None)
    assert check_supported_objective(parsed) == (True, None)


def test_generic_clinic_is_rejected_before_discovery():
    supported, message = check_supported_objective(
        objective(sectors=["clinics"]), "Find clinics in Lahore"
    )

    assert supported is False
    assert message and "Generic clinics are not supported yet" in message


def test_related_restaurant_taxonomy_labels_collapse_to_one_supported_vertical():
    parsed_objective = objective(
        sectors=["Restaurants", "Food and Beverage", "Hospitality"]
    )

    assert check_supported_objective(parsed_objective) == (True, None)

    with patch(
        "app.services.company_discovery.run_goal_parser_task",
        return_value=parsed_objective,
    ):
        normalized = parse_discovery_objective(
            ParseDiscoveryRequest(
                goal="Find restaurants in Faisalabad that need website services"
            )
        )

    assert normalized.target_sectors == ["Restaurants & cafes"]


def test_genuinely_mixed_supported_verticals_still_require_narrowing():
    supported, message = check_supported_objective(
        objective(sectors=["Restaurants", "Beauty salon"])
    )

    assert supported is False
    assert message and "more than one business category" in message
    assert "Restaurants & cafes" in message
    assert "Beauty & wellness" in message


def test_mixed_goal_requires_one_primary_vertical_before_discovery():
    goal = "Find clinics, dental practices, or wellness businesses in Lahore"
    supported, message = check_supported_objective(
        objective(sectors=["clinics", "dental practices", "wellness businesses"]),
        goal,
    )

    assert supported is False
    assert message and "more than one business category" in message
    assert "Dental & selected clinics" in message
    assert "Beauty & wellness" in message
    assert "Generic clinics are not supported yet" in message


def test_geography_parsed_from_goal_is_accepted_without_manual_region():
    with patch(
        "app.services.company_discovery.run_goal_parser_task",
        return_value=objective(),
    ):
        parsed = parse_discovery_objective(
            ParseDiscoveryRequest(
                goal="Find restaurants in Lahore that may need social media management"
            )
        )

    assert parsed.target_geographies == ["Lahore"]
    assert check_supported_objective(parsed) == (True, None)


def test_manual_region_supplies_missing_parsed_geography():
    parsed_without_location = objective().model_copy(
        update={"target_geographies": []}
    )
    with patch(
        "app.services.company_discovery.run_goal_parser_task",
        return_value=parsed_without_location,
    ):
        parsed = parse_discovery_objective(
            ParseDiscoveryRequest(
                goal="Find restaurants that may need social media management",
                region="United Kingdom",
            )
        )

    assert parsed.target_geographies == ["United Kingdom"]
    assert check_supported_objective(parsed) == (True, None)


def test_missing_geography_is_blocked_before_discovery():
    supported, message = check_supported_objective(
        objective().model_copy(update={"target_geographies": []})
    )

    assert supported is False
    assert message == "Add a location to continue."


@pytest.mark.parametrize("location", [None, "", "   "])
def test_discovery_request_rejects_missing_or_blank_geography(location):
    with pytest.raises(ValidationError, match="location"):
        CompanyDiscoveryRequest(
            offering="Social media management",
            desired_outcome="Find prospects",
            business_category="Restaurants & cafes",
            location=location,
        )
