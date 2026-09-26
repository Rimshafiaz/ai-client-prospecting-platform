import httpx
import pytest

from app.integrations.geocoding import (
    GeocodingProviderError,
    NominatimGeocodingProvider,
    ResolvedLocation,
)
from app.schemas.company_discovery import CompanyDiscoveryRequest
from app.services.local_business_discovery import (
    LocalBusinessDiscoveryError,
    collect_local_businesses,
    resolve_area,
)


class FakeGeocodingProvider:
    def __init__(self, resolved=None):
        self.resolved = resolved
        self.queries = []

    def geocode(self, query):
        self.queries.append(query)
        return self.resolved


class FakeProvider:
    def __init__(self):
        self.requests = []

    def discover(self, request):
        self.requests.append(request)
        return []

    @property
    def last_request(self):
        return self.requests[-1]


def criteria(location="Karachi, Pakistan", **updates):
    payload = {
        "offering": "Website development services",
        "business_category": "dental clinics",
        "location": location,
        "desired_outcome": "Find dental clinics worth pitching.",
        "max_results": 6,
    }
    return CompanyDiscoveryRequest(**payload)


def test_karachi_pakistan_resolves_without_supplied_coordinates():
    geocoder = FakeGeocodingProvider(
        ResolvedLocation(latitude=24.8607, longitude=67.0011, display_name="Karachi, Pakistan")
    )
    area = resolve_area(criteria(), geocoding_provider=geocoder)
    assert area.display_name == "Karachi, Pakistan"
    assert abs(area.latitude - 24.8607) < 1e-9
    assert area.longitude == 67.0011
    assert geocoder.queries == ["Karachi, Pakistan"]


def test_international_city_resolves_the_same_way():
    geocoder = FakeGeocodingProvider(
        ResolvedLocation(latitude=43.6532, longitude=-79.3832, display_name="Toronto, ON, Canada")
    )
    area = resolve_area(criteria(location="Toronto, Canada"), geocoding_provider=geocoder)
    assert area.latitude == 43.6532
    assert area.longitude == -79.3832


def test_explicit_coordinates_bypass_geocoding_completely():
    geocoder = FakeGeocodingProvider()
    request = criteria()
    area = resolve_area(
        request.model_copy(update={"latitude": 10.0, "longitude": 20.0}),
        geocoding_provider=geocoder,
    )
    assert area.latitude == 10.0
    assert area.longitude == 20.0
    assert geocoder.queries == []


def test_unresolvable_location_produces_clean_error():
    geocoder = FakeGeocodingProvider()
    try:
        resolve_area(criteria(location="Atlantis"), geocoding_provider=geocoder)
        raise AssertionError("expected LocalBusinessDiscoveryError")
    except __import__("app.services.local_business_discovery", fromlist=["LocalBusinessDiscoveryError"]).LocalBusinessDiscoveryError as error:
        assert "Could not resolve location 'Atlantis'" in str(error)
        assert "Karachi, Pakistan" in str(error)


def test_existing_lahore_behavior_still_works():
    geocoder = FakeGeocodingProvider(
        ResolvedLocation(latitude=31.5204, longitude=74.3587, display_name="Lahore, Punjab, Pakistan")
    )
    area = resolve_area(criteria(location="Lahore"), geocoding_provider=geocoder)
    assert 31.5204 == pytest.approx(area.latitude, abs=1e-9)


def test_collect_local_businesses_passes_resolved_area_to_provider():
    geocoder = FakeGeocodingProvider(
        ResolvedLocation(latitude=24.8607, longitude=67.0011, display_name="Karachi, Pakistan")
    )
    provider = FakeProvider()
    collect_local_businesses(criteria(), provider, geocoding_provider=geocoder)
    assert provider.last_request.area.latitude == 24.8607
    assert provider.last_request.max_results == 6


def nominatim_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_nominatim_resolves_faisalabad_with_injected_client():
    def handler(request):
        assert request.url.params["q"] == "Faisalabad, Pakistan"
        assert request.headers["user-agent"].startswith("OpportunityCue/1.0")
        return httpx.Response(
            200,
            json=[
                {
                    "lat": "31.416667",
                    "lon": "73.091111",
                    "display_name": "Faisalabad, Punjab, Pakistan",
                }
            ],
        )

    with nominatim_client(handler) as client:
        result = NominatimGeocodingProvider(client=client).geocode(
            "Faisalabad, Pakistan"
        )

    assert result == ResolvedLocation(
        latitude=31.416667,
        longitude=73.091111,
        display_name="Faisalabad, Punjab, Pakistan",
    )


@pytest.mark.parametrize(
    "query",
    [
        "  Lahore, Pakistan  ",
        "London, United Kingdom",
        "Toronto, Canada",
        "Sydney, Australia",
        "Berlin, Germany",
    ],
)
def test_nominatim_normalizes_ordinary_city_country_queries(query):
    expected_query = query.strip()

    def handler(request):
        assert request.url.params["q"] == expected_query
        return httpx.Response(
            200,
            json=[{"lat": "1.5", "lon": "2.5", "display_name": expected_query}],
        )

    with nominatim_client(handler) as client:
        result = NominatimGeocodingProvider(client=client).geocode(query)

    assert result == ResolvedLocation(1.5, 2.5, expected_query)


def test_nominatim_empty_result_is_unresolved():
    with nominatim_client(lambda request: httpx.Response(200, json=[])) as client:
        assert NominatimGeocodingProvider(client=client).geocode("Atlantis") is None


def test_nominatim_http_failure_is_not_reported_as_unresolved():
    with nominatim_client(lambda request: httpx.Response(429)) as client:
        with pytest.raises(GeocodingProviderError, match="HTTP 429"):
            NominatimGeocodingProvider(client=client).geocode("Faisalabad, Pakistan")


def test_nominatim_timeout_is_a_controlled_provider_error():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with nominatim_client(handler) as client:
        with pytest.raises(GeocodingProviderError, match="timed out"):
            NominatimGeocodingProvider(client=client).geocode("Faisalabad, Pakistan")
