import re

from app.integrations.business_discovery import (
    BusinessDiscoveryProvider,
    DiscoveredBusiness,
    LocalBusinessDiscoveryRequest,
    LocalDiscoveryArea,
)
from app.integrations.geocoding import GeocodingProvider, NominatimGeocodingProvider
from app.schemas.company_discovery import (
    CompanyDiscoveryRequest,
    DiscoveredCompanyCandidate,
)
from app.schemas.opportunity_models import IndustryOverlayId


class LocalBusinessDiscoveryError(Exception):
    pass


INDUSTRY_ALIASES: dict[IndustryOverlayId, tuple[str, ...]] = {
    IndustryOverlayId.BEAUTY_WELLNESS: (
        "beauty",
        "salon",
        "salons",
        "spa",
        "wellness",
    ),
    IndustryOverlayId.RESTAURANTS_CAFES: (
        "restaurant",
        "restaurants",
        "cafe",
        "cafes",
    ),
    IndustryOverlayId.FITNESS_GYMS: (
        "gym",
        "gyms",
        "fitness",
    ),
    IndustryOverlayId.BOUTIQUES_RETAIL: (
        "boutique",
        "boutiques",
        "retail",
        "clothing",
        "fashion",
    ),
    IndustryOverlayId.DENTAL_SELECTED_CLINICS: (
        "dental",
        "dental clinic",
        "dental clinics",
        "dental practice",
        "dental practices",
        "dentist",
        "dentists",
    ),
}

INDUSTRY_LABELS: dict[IndustryOverlayId, str] = {
    IndustryOverlayId.BEAUTY_WELLNESS: "Beauty & wellness",
    IndustryOverlayId.RESTAURANTS_CAFES: "Restaurants & cafes",
    IndustryOverlayId.FITNESS_GYMS: "Fitness & gyms",
    IndustryOverlayId.BOUTIQUES_RETAIL: "Boutiques & retail",
    IndustryOverlayId.DENTAL_SELECTED_CLINICS: "Dental & selected clinics",
}

_INDUSTRY_PATTERNS: dict[IndustryOverlayId, re.Pattern[str]] = {
    IndustryOverlayId.BEAUTY_WELLNESS: re.compile(
        r"\b(?:beauty|salons?|spas?|wellness)\b", re.IGNORECASE
    ),
    IndustryOverlayId.RESTAURANTS_CAFES: re.compile(
        r"\b(?:restaurants?|cafes?|food\s*(?:and|&)\s*beverage|hospitality)\b",
        re.IGNORECASE,
    ),
    IndustryOverlayId.FITNESS_GYMS: re.compile(
        r"\b(?:fitness|gyms?)\b", re.IGNORECASE
    ),
    IndustryOverlayId.BOUTIQUES_RETAIL: re.compile(
        r"\b(?:boutiques?|retail|clothing|fashion)\b", re.IGNORECASE
    ),
    IndustryOverlayId.DENTAL_SELECTED_CLINICS: re.compile(
        r"\b(?:dentists?|dental(?:\s*&\s*selected\s+clinics?|\s+(?:clinics?|practices?))?)\b",
        re.IGNORECASE,
    ),
}


def resolve_discovery_scope(value: str) -> tuple[list[str], bool]:
    """Return supported verticals plus whether an unsupported generic clinic was named."""
    industries = [
        industry
        for industry, pattern in _INDUSTRY_PATTERNS.items()
        if pattern.search(value)
    ]
    without_dental = _INDUSTRY_PATTERNS[
        IndustryOverlayId.DENTAL_SELECTED_CLINICS
    ].sub("", value)
    has_generic_clinic = bool(
        re.search(r"\bclinics?\b", without_dental, re.IGNORECASE)
    )
    return [INDUSTRY_LABELS[industry] for industry in industries], has_generic_clinic


def collect_local_businesses(
    criteria: CompanyDiscoveryRequest,
    provider: BusinessDiscoveryProvider,
    geocoding_provider: GeocodingProvider | None = None,
) -> list[DiscoveredBusiness]:
    request = LocalBusinessDiscoveryRequest(
        industry=resolve_industry(criteria.industry),
        area=resolve_area(criteria, geocoding_provider),
        max_results=criteria.max_results,
    )
    return provider.discover(request)


def resolve_industry(value: str) -> IndustryOverlayId:
    normalized = value.casefold().strip()
    for industry, aliases in INDUSTRY_ALIASES.items():
        if normalized in aliases or any(alias in normalized for alias in aliases):
            return industry
    raise LocalBusinessDiscoveryError(
        "Local discovery currently supports Beauty & wellness, Restaurants & cafes, "
        "Fitness & gyms, Boutiques & retail, and Dental & selected clinics."
    )


def resolve_area(
    criteria: CompanyDiscoveryRequest,
    geocoding_provider: GeocodingProvider | None = None,
) -> LocalDiscoveryArea:
    if criteria.latitude is not None and criteria.longitude is not None:
        return LocalDiscoveryArea(
            display_name=criteria.location,
            latitude=criteria.latitude,
            longitude=criteria.longitude,
            radius_miles=criteria.radius_miles,
        )

    provider = geocoding_provider or NominatimGeocodingProvider()
    location_text = criteria.location or ""
    resolved = provider.geocode(location_text)
    if resolved is None:
        raise LocalBusinessDiscoveryError(
            f"Could not resolve location '{location_text}'. Try a city and "
            "country, e.g. Karachi, Pakistan."
        )
    return LocalDiscoveryArea(
        display_name=resolved.display_name,
        latitude=resolved.latitude,
        longitude=resolved.longitude,
        radius_miles=criteria.radius_miles,
    )


def business_to_candidate(
    criteria: CompanyDiscoveryRequest,
    business: DiscoveredBusiness,
) -> DiscoveredCompanyCandidate:
    return DiscoveredCompanyCandidate(
        company_name=business.name,
        website=business.website,
        industry=business.category or criteria.industry,
        short_description=business.formatted_address,
        match_explanation=(
            "Open Places returned this physical business listing for the requested "
            "category and location. It has not been qualified as an opportunity yet."
        ),
        source_provider=business.provider,
        source_record_id=business.provider_record_id,
        source_retrieved_at=business.retrieved_at,
        source_data_release=business.source_data_release,
        formatted_address=business.formatted_address,
        business_status=business.business_status,
        phone_number=business.phone_number,
        website_verification_state=(
            "listed_unverified" if business.website is not None else None
        ),
    )
