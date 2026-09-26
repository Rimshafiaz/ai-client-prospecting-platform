import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.current_user import get_current_user
from app.core.config import settings
from app.schemas.discovery_shortlist import (
    DiscoveryOpportunityPreparationRequest,
    DiscoveryOpportunityPreparationResponse,
    DiscoveryOpportunityQueueResponse,
    DiscoveryShortlistRequest,
    DiscoveryShortlistResponse,
)
from app.integrations.apify_social import (
    ApifySocialProviderError,
    create_apify_social_enrichment_provider,
)
from app.integrations.open_places import OpenPlacesProviderError
from app.integrations.serper import SerperProviderError
from app.integrations.geocoding import GeocodingProviderError
from app.models.user import User
from app.services.local_business_discovery import LocalBusinessDiscoveryError
from app.schemas.company_discovery import (
    CompanyDiscoveryRequest,
    CompanyDiscoveryResponse,
    ParseDiscoveryRequest,
    ParseDiscoveryResponse,
)
from app.schemas.social_enrichment import (
    SocialEnrichmentRequest,
    SocialEnrichmentResponse,
)
from app.services.company_discovery import (
    check_supported_objective,
    discover_companies,
    parse_discovery_objective,
)
from app.services.social_enrichment import (
    SocialEnrichmentError,
    enrich_social_profiles,
)
from app.services.discovery_shortlist import (
    DiscoveryShortlistError,
    shortlist_discovery_candidates,
)
from app.services.discovery_opportunity_queue import build_discovery_opportunity_queue
from app.services.discovery_queue_preparation import prepare_discovery_opportunity_queue


router = APIRouter(tags=["Company Discovery"])
logger = logging.getLogger(__name__)


@router.post(
    "/company-discovery/parse",
    response_model=ParseDiscoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Interpret a discovery goal into a structured objective (stateless)",
    responses={
        422: {"description": "Empty or invalid goal"},
        503: {"description": "AI failure"},
    },
)
def parse_discovery_goal_endpoint(
    request: ParseDiscoveryRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        objective = parse_discovery_objective(request)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not interpret the discovery goal. Please try again.",
        ) from error

    supported, message = check_supported_objective(objective, request.goal)
    return ParseDiscoveryResponse(
        objective=objective,
        supported=supported,
        message=message,
    )


@router.post(
    "/company-discovery",
    response_model=CompanyDiscoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Discover companies matching business criteria (stateless)",
    responses={
        422: {"description": "Empty or invalid criteria"},
        503: {"description": "Search provider or AI failure"},
    },
)
def discover_companies_endpoint(
    criteria: CompanyDiscoveryRequest,
    current_user: User = Depends(get_current_user),
):
    if criteria.objective is not None:
        supported, message = check_supported_objective(criteria.objective)
        if not supported:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=message,
            )
    try:
        return discover_companies(criteria)
    except LocalBusinessDiscoveryError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except GeocodingProviderError as error:
        logger.exception("Company discovery geocoding provider failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Location lookup is temporarily unavailable. Please try again.",
        ) from error
    except OpenPlacesProviderError as error:
        logger.exception("Company discovery Open Places provider failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local business search is temporarily unavailable. Please try again.",
        ) from error
    except SerperProviderError as error:
        logger.exception("Company discovery Serper provider failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web search is temporarily unavailable. Please try again.",
        ) from error
    except (RuntimeError, ValueError) as error:
        logger.exception("Company discovery failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Company discovery failed. Please try again.",
        ) from error


@router.post(
    "/company-discovery/social-enrichment",
    response_model=SocialEnrichmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve public social-profile observations (stateless)",
    responses={
        422: {"description": "Invalid or unsupported social-profile URL"},
        503: {"description": "Social provider failure"},
    },
)
def enrich_social_profiles_endpoint(
    request: SocialEnrichmentRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        provider = create_apify_social_enrichment_provider(
            api_token=settings.apify_token,
            instagram_actor_id=settings.apify_instagram_actor_id,
            facebook_actor_id=settings.apify_facebook_actor_id,
            tiktok_actor_id=settings.apify_tiktok_actor_id,
        )
        return enrich_social_profiles(request, provider)
    except SocialEnrichmentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (ApifySocialProviderError, RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Social enrichment failed. Please try again.",
        ) from error


@router.post(
    "/company-discovery/shortlist",
    response_model=DiscoveryShortlistResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply deterministic Opportunity Model shortlist rules (stateless)",
    responses={
        422: {"description": "Invalid model selection or candidate snapshot"},
    },
)
def shortlist_discovery_candidates_endpoint(
    request: DiscoveryShortlistRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return shortlist_discovery_candidates(request)
    except (DiscoveryShortlistError, LocalBusinessDiscoveryError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.post(
    "/company-discovery/opportunity-queue",
    response_model=DiscoveryOpportunityQueueResponse,
    status_code=status.HTTP_200_OK,
    summary="Surface evidence-backed discovery opportunities (stateless)",
    responses={
        422: {"description": "Invalid model selection or candidate snapshot"},
    },
)
def build_discovery_opportunity_queue_endpoint(
    request: DiscoveryShortlistRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return build_discovery_opportunity_queue(request)
    except (DiscoveryShortlistError, LocalBusinessDiscoveryError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.post(
    "/company-discovery/prepare-opportunity-queue",
    response_model=DiscoveryOpportunityPreparationResponse,
    status_code=status.HTTP_200_OK,
    summary="Prepare only evidence-backed discovery opportunities for user review",
    responses={
        422: {"description": "Invalid model selection or candidate snapshot"},
    },
)
def prepare_discovery_opportunity_queue_endpoint(
    request: DiscoveryOpportunityPreparationRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return prepare_discovery_opportunity_queue(request)
    except (DiscoveryShortlistError, LocalBusinessDiscoveryError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
