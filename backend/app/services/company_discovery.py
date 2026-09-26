from app.ai.tasks.goal_parser_task import (
    create_goal_parser_task,
    run_goal_parser_task,
)
from app.core.config import settings
from app.integrations.open_places import create_open_places_provider
from app.integrations.serper import create_serper_search_provider
from app.schemas.company_discovery import (
    SUPPORTED_GOAL_TYPES,
    UNSUPPORTED_GOAL_MESSAGE,
    CompanyDiscoveryRequest,
    CompanyDiscoveryResponse,
    DiscoveryObjective,
    ParseDiscoveryRequest,
)
from app.services.candidate_pool import merge_candidate_pool
from app.services.local_business_discovery import (
    collect_local_businesses,
    resolve_discovery_scope,
)
from app.services.web_candidate_discovery import discover_web_and_social_candidates


def check_supported_objective(
    objective: DiscoveryObjective,
    goal: str | None = None,
) -> tuple[bool, str | None]:
    if objective.goal_type not in SUPPORTED_GOAL_TYPES:
        return False, UNSUPPORTED_GOAL_MESSAGE
    if not objective.offering:
        return (
            False,
            "Say what you are offering so we know what a good match looks "
            "like, for example: website redesign services.",
        )
    if not objective.target_sectors:
        return (
            False,
            "Add the business category you are looking for, for example: "
            "dental clinics or beauty salons.",
        )
    if not objective.target_geographies:
        return (
            False,
            "Add a location to continue.",
        )
    sectors, has_generic_clinic = resolve_discovery_scope(
        " ".join(filter(None, [goal, *objective.target_sectors]))
    )
    if len(sectors) > 1 or (has_generic_clinic and sectors):
        choices = ", ".join(sectors)
        clinic_note = (
            " Generic clinics are not supported yet." if has_generic_clinic else ""
        )
        return (
            False,
            "We found more than one business category in your goal. "
            f"Edit the goal and choose one primary category: {choices}."
            f"{clinic_note}",
        )
    if has_generic_clinic:
        return (
            False,
            "Generic clinics are not supported yet. Choose Dental & selected "
            "clinics only if you mean dental practices.",
        )
    if not sectors:
        return (
            False,
            "Choose one supported business category: Beauty & wellness, "
            "Restaurants & cafes, Fitness & gyms, Boutiques & retail, or "
            "Dental & selected clinics.",
        )
    return True, None


def parse_discovery_objective(
    request: ParseDiscoveryRequest,
) -> DiscoveryObjective:
    objective = run_goal_parser_task(create_goal_parser_task(request))
    updates: dict[str, object] = {}
    if request.region and not objective.target_geographies:
        updates["target_geographies"] = [request.region]
    sectors, has_generic_clinic = resolve_discovery_scope(
        " ".join([request.goal, *objective.target_sectors])
    )
    if len(sectors) == 1 and not has_generic_clinic:
        updates["target_sectors"] = sectors
    return objective.model_copy(update=updates) if updates else objective


def discover_companies(
    criteria: CompanyDiscoveryRequest,
) -> CompanyDiscoveryResponse:
    local_provider = create_open_places_provider(settings.open_places_api_key)
    web_provider = create_serper_search_provider(settings.serper_api_key)
    local_candidates = collect_local_businesses(criteria, local_provider)
    web_candidates = discover_web_and_social_candidates(criteria, web_provider)
    return merge_candidate_pool(criteria, [*local_candidates, *web_candidates])
