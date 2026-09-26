from app.integrations.business_discovery import DiscoverySourceType
from app.integrations.social_enrichment import social_profile_key
from app.schemas.discovery_shortlist import (
    CandidateShortlistEntry,
    CandidateShortlistInput,
    DiscoveryShortlistRequest,
    DiscoveryShortlistResponse,
    DiscoveryShortlistState,
    NextEvidenceAction,
    OpportunityModelShortlistEvaluation,
)
from app.schemas.opportunity_models import EvidenceSignalType
from app.schemas.social_enrichment import SocialEnrichmentState
from app.services.local_business_discovery import resolve_industry
from app.services.opportunity_model_catalog import OpportunityModel, get_opportunity_model


class DiscoveryShortlistError(Exception):
    pass


SIGNAL_ACTIONS = {
    EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED: NextEvidenceAction.VERIFY_BUSINESS_IDENTITY,
    EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE: NextEvidenceAction.VERIFY_OFFICIAL_WEBSITE,
    EvidenceSignalType.NO_VERIFIED_OFFICIAL_WEB_PRESENCE: NextEvidenceAction.VERIFY_OFFICIAL_WEBSITE,
    EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED: NextEvidenceAction.VERIFY_OFFICIAL_WEBSITE,
    EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED: NextEvidenceAction.AUDIT_MOBILE_PERFORMANCE,
    EvidenceSignalType.WEBSITE_BOOKING_PATH_MANUAL_ONLY: NextEvidenceAction.INSPECT_BOOKING_CONTACT_PATH,
    EvidenceSignalType.WEBSITE_RESERVATION_PATH_MANUAL_ONLY: NextEvidenceAction.INSPECT_RESTAURANT_RESERVATION_PATH,
    EvidenceSignalType.WEBSITE_RESTAURANT_PRIMARY_PATH_NOT_OBSERVED: NextEvidenceAction.INSPECT_INDUSTRY_CONVERSION_PATHS,
    EvidenceSignalType.WEBSITE_FITNESS_ENQUIRY_PATH_NOT_OBSERVED: NextEvidenceAction.INSPECT_INDUSTRY_CONVERSION_PATHS,
    EvidenceSignalType.WEBSITE_RETAIL_PRODUCT_PATH_NOT_OBSERVED: NextEvidenceAction.INSPECT_INDUSTRY_CONVERSION_PATHS,
    EvidenceSignalType.WEBSITE_CLINIC_PATIENT_PATH_INCOMPLETE: NextEvidenceAction.INSPECT_INDUSTRY_CONVERSION_PATHS,
    EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED: NextEvidenceAction.VERIFY_OFFICIAL_SOCIAL_PROFILE,
    EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED: NextEvidenceAction.CONFIRM_BUSINESS_ACTIVITY,
    EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED: NextEvidenceAction.CONFIRM_SOCIAL_HISTORY,
    EvidenceSignalType.SOCIAL_DORMANCY_MEASURED: NextEvidenceAction.MEASURE_SOCIAL_DORMANCY,
}

SIGNAL_PRIORITY = {
    EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED: 0,
    EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE: 10,
    EvidenceSignalType.NO_VERIFIED_OFFICIAL_WEB_PRESENCE: 10,
    EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED: 10,
    EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED: 10,
    EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED: 20,
    EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED: 30,
    EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED: 40,
    EvidenceSignalType.WEBSITE_BOOKING_PATH_MANUAL_ONLY: 40,
    EvidenceSignalType.WEBSITE_RESERVATION_PATH_MANUAL_ONLY: 40,
    EvidenceSignalType.WEBSITE_RESTAURANT_PRIMARY_PATH_NOT_OBSERVED: 40,
    EvidenceSignalType.WEBSITE_FITNESS_ENQUIRY_PATH_NOT_OBSERVED: 40,
    EvidenceSignalType.WEBSITE_RETAIL_PRODUCT_PATH_NOT_OBSERVED: 40,
    EvidenceSignalType.WEBSITE_CLINIC_PATIENT_PATH_INCOMPLETE: 40,
    EvidenceSignalType.SOCIAL_DORMANCY_MEASURED: 50,
}

ACTION_PRIORITY = {
    NextEvidenceAction.VERIFY_BUSINESS_IDENTITY: 0,
    NextEvidenceAction.VERIFY_OFFICIAL_WEBSITE: 10,
    NextEvidenceAction.COLLECT_SOCIAL_PROFILE_OBSERVATIONS: 10,
    NextEvidenceAction.VERIFY_OFFICIAL_SOCIAL_PROFILE: 15,
    NextEvidenceAction.CONFIRM_BUSINESS_ACTIVITY: 20,
    NextEvidenceAction.CONFIRM_SOCIAL_HISTORY: 30,
    NextEvidenceAction.AUDIT_MOBILE_PERFORMANCE: 40,
    NextEvidenceAction.INSPECT_BOOKING_CONTACT_PATH: 40,
    NextEvidenceAction.INSPECT_RESTAURANT_RESERVATION_PATH: 40,
    NextEvidenceAction.INSPECT_INDUSTRY_CONVERSION_PATHS: 40,
    NextEvidenceAction.MEASURE_SOCIAL_DORMANCY: 50,
    NextEvidenceAction.NO_ACTION: 100,
}

WEBSITE_RESEARCH_SIGNALS = {
    EvidenceSignalType.NO_VERIFIED_OFFICIAL_WEB_PRESENCE,
    EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED,
    EvidenceSignalType.WEBSITE_BOOKING_PATH_MANUAL_ONLY,
    EvidenceSignalType.WEBSITE_RESERVATION_PATH_MANUAL_ONLY,
    EvidenceSignalType.WEBSITE_RESTAURANT_PRIMARY_PATH_NOT_OBSERVED,
    EvidenceSignalType.WEBSITE_FITNESS_ENQUIRY_PATH_NOT_OBSERVED,
    EvidenceSignalType.WEBSITE_RETAIL_PRODUCT_PATH_NOT_OBSERVED,
    EvidenceSignalType.WEBSITE_CLINIC_PATIENT_PATH_INCOMPLETE,
}

SOCIAL_RESEARCH_SIGNALS = {
    EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED,
    EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED,
    EvidenceSignalType.SOCIAL_DORMANCY_MEASURED,
}


def shortlist_discovery_candidates(
    request: DiscoveryShortlistRequest,
) -> DiscoveryShortlistResponse:
    industry = resolve_industry(request.criteria.industry)
    models = [
        get_opportunity_model(model_id)
        for model_id in request.model_selection.model_ids
    ]
    unsupported_models = [
        model.display_name
        for model in models
        if industry not in model.applicable_industries
    ]
    if unsupported_models:
        raise DiscoveryShortlistError(
            "The selected Opportunity Models do not apply to this industry: "
            + ", ".join(unsupported_models)
            + "."
        )

    entries = [
        shortlist_candidate(index, candidate_input, models)
        for index, candidate_input in enumerate(request.candidates)
    ]
    return DiscoveryShortlistResponse(candidates=entries)


def shortlist_candidate(
    candidate_index: int,
    candidate_input: CandidateShortlistInput,
    models: list[OpportunityModel],
) -> CandidateShortlistEntry:
    candidate = candidate_input.candidate
    if not has_traceable_discovery_source(candidate_input):
        evaluations = [
            OpportunityModelShortlistEvaluation(
                model_id=model.id,
                state=DiscoveryShortlistState.EXCLUDED,
                reason=(
                    "The candidate has no traceable discovery source, so it cannot "
                    "enter the evidence workflow."
                ),
                next_evidence_action=NextEvidenceAction.NO_ACTION,
            )
            for model in models
        ]
        return CandidateShortlistEntry(
            candidate_index=candidate_index,
            company_name=candidate.company_name,
            state=DiscoveryShortlistState.EXCLUDED,
            model_evaluations=evaluations,
            next_evidence_action=NextEvidenceAction.NO_ACTION,
        )

    observed_signal_types = observed_signal_types_for(candidate_input)
    evaluations = [
        evaluate_model(candidate_input, model, observed_signal_types)
        for model in models
    ]
    state = candidate_state(evaluations)
    return CandidateShortlistEntry(
        candidate_index=candidate_index,
        company_name=candidate.company_name,
        state=state,
        model_evaluations=evaluations,
        next_evidence_action=next_action_for_state(evaluations, state),
    )


def has_traceable_discovery_source(candidate_input: CandidateShortlistInput) -> bool:
    candidate = candidate_input.candidate
    return bool(
        candidate.source_provider
        and candidate.source_retrieved_at
        and (
            candidate.source_record_id
            or candidate.supporting_source_urls
        )
    )


def observed_signal_types_for(
    candidate_input: CandidateShortlistInput,
) -> set[EvidenceSignalType]:
    candidate = candidate_input.candidate
    observed = {
        signal.signal_type
        for signal in candidate_input.evidence_signals
    }
    source_types = set(candidate.discovery_source_types)
    if (
        DiscoverySourceType.LOCAL_PLACES.value in source_types
        and candidate.website is None
    ):
        observed.add(EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE)
    return observed


def evaluate_model(
    candidate_input: CandidateShortlistInput,
    model: OpportunityModel,
    observed_signal_types: set[EvidenceSignalType],
) -> OpportunityModelShortlistEvaluation:
    missing_signal_types = [
        signal_type
        for signal_type in model.required_signal_types
        if signal_type not in observed_signal_types
    ]
    observed_for_model = [
        signal_type
        for signal_type in model.required_signal_types
        if signal_type in observed_signal_types
    ]
    if (
        model.id == "web_conversion.no_verified_web_presence"
        and EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE in observed_signal_types
    ):
        observed_for_model.append(EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE)
    if EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED in missing_signal_types:
        return OpportunityModelShortlistEvaluation(
            model_id=model.id,
            state=DiscoveryShortlistState.NEEDS_IDENTITY_REVIEW,
            observed_signal_types=observed_for_model,
            missing_signal_types=missing_signal_types,
            reason=(
                "The candidate has not been linked to a verified business identity. "
                "Discovery data alone cannot support an opportunity claim."
            ),
            next_evidence_action=NextEvidenceAction.VERIFY_BUSINESS_IDENTITY,
        )
    if missing_signal_types:
        next_action = next_missing_signal_action(
            candidate_input,
            missing_signal_types,
        )
        missing_signals = set(missing_signal_types)
        if (
            missing_signals & WEBSITE_RESEARCH_SIGNALS
            or missing_signals <= SOCIAL_RESEARCH_SIGNALS
        ):
            return OpportunityModelShortlistEvaluation(
                model_id=model.id,
                state=DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH,
                observed_signal_types=observed_for_model,
                missing_signal_types=missing_signal_types,
                reason=(
                    "The verified business identity matches the campaign, but the "
                    "selected check requires bounded specialist research. This permits "
                    "research, not outreach."
                ),
                next_evidence_action=next_action,
            )
        return OpportunityModelShortlistEvaluation(
            model_id=model.id,
            state=DiscoveryShortlistState.NEEDS_EVIDENCE,
            observed_signal_types=observed_for_model,
            missing_signal_types=missing_signal_types,
            reason=(
                "The verified business identity is in scope, but required evidence "
                "for this Opportunity Model is still missing."
            ),
            next_evidence_action=next_action,
        )
    return OpportunityModelShortlistEvaluation(
        model_id=model.id,
        state=DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH,
        observed_signal_types=observed_for_model,
        reason=(
            "The candidate has the model's required light evidence. It is eligible "
            "for deeper research, not outreach or a service-opportunity claim."
        ),
        next_evidence_action=NextEvidenceAction.NO_ACTION,
    )


def next_missing_signal_action(
    candidate_input: CandidateShortlistInput,
    missing_signal_types: list[EvidenceSignalType],
) -> NextEvidenceAction:
    social_observations_available = has_observed_social_profile(candidate_input)
    for signal_type in sorted(
        missing_signal_types,
        key=lambda signal_type: SIGNAL_PRIORITY[signal_type],
    ):
        if signal_type is EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED:
            if social_observations_available:
                return NextEvidenceAction.VERIFY_OFFICIAL_SOCIAL_PROFILE
            return NextEvidenceAction.COLLECT_SOCIAL_PROFILE_OBSERVATIONS
        action = SIGNAL_ACTIONS.get(signal_type)
        if action is not None:
            return action
    return NextEvidenceAction.NO_ACTION


def has_observed_social_profile(candidate_input: CandidateShortlistInput) -> bool:
    candidate_keys = {
        key
        for url in candidate_input.candidate.social_profile_urls
        if (key := social_profile_key(str(url))) is not None
    }
    if not candidate_keys:
        return False
    return any(
        observation.state is SocialEnrichmentState.OBSERVED
        and social_profile_key(str(observation.profile_url)) in candidate_keys
        for observation in candidate_input.social_observations
    )


def candidate_state(
    evaluations: list[OpportunityModelShortlistEvaluation],
) -> DiscoveryShortlistState:
    states = {evaluation.state for evaluation in evaluations}
    if states == {DiscoveryShortlistState.EXCLUDED}:
        return DiscoveryShortlistState.EXCLUDED
    if DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH in states:
        return DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH
    if DiscoveryShortlistState.NEEDS_IDENTITY_REVIEW in states:
        return DiscoveryShortlistState.NEEDS_IDENTITY_REVIEW
    if DiscoveryShortlistState.NEEDS_EVIDENCE in states:
        return DiscoveryShortlistState.NEEDS_EVIDENCE
    return DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH


def next_action_for_state(
    evaluations: list[OpportunityModelShortlistEvaluation],
    state: DiscoveryShortlistState,
) -> NextEvidenceAction:
    actions = [
        evaluation.next_evidence_action
        for evaluation in evaluations
        if evaluation.state is state
        or (
            state is DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH
            and evaluation.next_evidence_action is not NextEvidenceAction.NO_ACTION
        )
    ]
    return min(
        actions,
        key=lambda action: (ACTION_PRIORITY[action], action.value),
        default=NextEvidenceAction.NO_ACTION,
    )
