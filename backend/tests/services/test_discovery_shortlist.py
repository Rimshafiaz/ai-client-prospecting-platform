from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.company_discovery import (
    CompanyDiscoveryRequest,
    DiscoveredCompanyCandidate,
)
from app.schemas.discovery_shortlist import (
    CandidateShortlistInput,
    DiscoveryShortlistRequest,
    DiscoveryShortlistState,
    NextEvidenceAction,
)
from app.schemas.opportunity_models import (
    EvidenceSignal,
    EvidenceSignalType,
    EvidenceSource,
    EvidenceType,
    OpportunityModelSelection,
)
from app.schemas.social_enrichment import (
    SocialEnrichmentState,
    SocialPlatform,
    SocialProfileObservation,
)
from app.services.discovery_shortlist import (
    DiscoveryShortlistError,
    next_missing_signal_action,
    shortlist_discovery_candidates,
)


NOW = datetime(2026, 9, 8, tzinfo=UTC)


def criteria() -> CompanyDiscoveryRequest:
    return CompanyDiscoveryRequest(
        offering="Website redesign and social content",
        desired_outcome="Find businesses worth investigating.",
        business_category="Boutiques",
        location="Lahore",
    )


def source() -> EvidenceSource:
    return EvidenceSource(
        provider="open_places",
        provider_record_id="overture:glow",
        retrieved_at=NOW,
    )


def signal(signal_type: EvidenceSignalType) -> EvidenceSignal:
    return EvidenceSignal(
        signal_type=signal_type,
        evidence_type=EvidenceType.OBSERVED,
        supporting_value=f"Observed {signal_type.value}.",
        source=source(),
        captured_at=NOW,
    )


def candidate(
    website: str | None = None,
    source_provider: str | None = "open_places",
    source_record_id: str | None = "overture:glow",
    source_types: list[str] | None = None,
    social_profile_urls: list[str] | None = None,
) -> DiscoveredCompanyCandidate:
    return DiscoveredCompanyCandidate(
        company_name="Glow Boutique",
        website=website,
        industry="clothing_store",
        match_explanation="Discovery sources returned this possible identity.",
        source_provider=source_provider,
        source_record_id=source_record_id,
        source_retrieved_at=NOW if source_provider else None,
        discovery_source_types=source_types or ["local_places"],
        social_profile_urls=social_profile_urls or [],
    )


def selection(*model_ids: str) -> OpportunityModelSelection:
    return OpportunityModelSelection(
        model_ids=tuple(model_ids),
        confirmed_by_user=True,
    )


def request(
    candidate_input: CandidateShortlistInput,
    *model_ids: str,
) -> DiscoveryShortlistRequest:
    return DiscoveryShortlistRequest(
        criteria=criteria(),
        model_selection=selection(*model_ids),
        candidates=[candidate_input],
    )


class TestDiscoveryShortlist:
    def test_requires_user_confirmed_opportunity_model_selection(self):
        with pytest.raises(ValidationError, match="Confirm the Opportunity Model"):
            DiscoveryShortlistRequest(
                criteria=criteria(),
                model_selection=OpportunityModelSelection(
                    model_ids=("web_conversion.mobile_performance",),
                ),
                candidates=[CandidateShortlistInput(candidate=candidate())],
            )

    def test_rejects_model_not_applicable_to_campaign_industry(self):
        shortlist_request = request(
            CandidateShortlistInput(candidate=candidate()),
            "web_conversion.restaurant_reservation_path",
        )

        with pytest.raises(DiscoveryShortlistError, match="do not apply"):
            shortlist_discovery_candidates(shortlist_request)

    def test_local_candidate_without_listed_website_still_needs_identity_review(self):
        response = shortlist_discovery_candidates(
            request(
                CandidateShortlistInput(candidate=candidate()),
                "web_conversion.no_verified_web_presence",
            )
        )

        entry = response.candidates[0]
        evaluation = entry.model_evaluations[0]
        assert entry.state is DiscoveryShortlistState.NEEDS_IDENTITY_REVIEW
        assert evaluation.state is DiscoveryShortlistState.NEEDS_IDENTITY_REVIEW
        assert EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE in evaluation.observed_signal_types
        assert EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED in evaluation.missing_signal_types
        assert entry.next_evidence_action is NextEvidenceAction.VERIFY_BUSINESS_IDENTITY

    def test_candidate_with_required_light_evidence_is_only_eligible_for_deeper_research(self):
        response = shortlist_discovery_candidates(
            request(
                CandidateShortlistInput(
                    candidate=candidate(),
                    evidence_signals=[
                        signal(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                    ],
                ),
                "web_conversion.no_verified_web_presence",
            )
        )

        evaluation = response.candidates[0].model_evaluations[0]
        assert evaluation.state is DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH
        assert (
            evaluation.next_evidence_action
            is NextEvidenceAction.VERIFY_OFFICIAL_WEBSITE
        )
        assert "not outreach" in evaluation.reason

    def test_mobile_model_requests_measurement_instead_of_claiming_a_performance_problem(self):
        response = shortlist_discovery_candidates(
            request(
                CandidateShortlistInput(
                    candidate=candidate(website="https://glow.example"),
                    evidence_signals=[
                        signal(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                        signal(EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED),
                    ],
                ),
                "web_conversion.mobile_performance",
            )
        )

        entry = response.candidates[0]
        evaluation = entry.model_evaluations[0]
        assert entry.state is DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH
        assert EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED in evaluation.missing_signal_types
        assert entry.next_evidence_action is NextEvidenceAction.AUDIT_MOBILE_PERFORMANCE

    def test_missing_evidence_uses_dependency_priority_not_required_signal_order(self):
        action = next_missing_signal_action(
            CandidateShortlistInput(candidate=candidate(website="https://glow.example")),
            [
                EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED,
                EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            ],
        )

        assert action is NextEvidenceAction.VERIFY_OFFICIAL_WEBSITE

    def test_candidate_next_action_does_not_depend_on_selected_model_order(self):
        candidate_input = CandidateShortlistInput(
            candidate=candidate(website="https://glow.example"),
            evidence_signals=[
                signal(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                signal(EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED),
            ],
        )
        first = shortlist_discovery_candidates(
            request(
                candidate_input,
                "social_presence.dormant_official_presence",
                "web_conversion.mobile_performance",
            )
        )
        second = shortlist_discovery_candidates(
            request(
                candidate_input,
                "web_conversion.mobile_performance",
                "social_presence.dormant_official_presence",
            )
        )

        assert first.candidates[0].next_evidence_action is (
            NextEvidenceAction.COLLECT_SOCIAL_PROFILE_OBSERVATIONS
        )
        assert second.candidates[0].next_evidence_action is (
            NextEvidenceAction.COLLECT_SOCIAL_PROFILE_OBSERVATIONS
        )

    def test_identity_sufficient_social_candidate_can_enter_specialist_research(self):
        observation = SocialProfileObservation(
            profile_url="https://www.instagram.com/glowboutique",
            platform=SocialPlatform.INSTAGRAM,
            state=SocialEnrichmentState.OBSERVED,
            handle="glowboutique",
            source=EvidenceSource(
                provider="apify",
                source_url="https://www.instagram.com/glowboutique",
                retrieved_at=NOW,
            ),
        )
        response = shortlist_discovery_candidates(
            request(
                CandidateShortlistInput(
                    candidate=candidate(
                        source_provider="serper",
                        source_record_id="serper:glow",
                        source_types=["social_search"],
                        social_profile_urls=["https://www.instagram.com/glowboutique"],
                    ),
                    evidence_signals=[
                        signal(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                        signal(EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED),
                    ],
                    social_observations=[observation],
                ),
                "social_presence.dormant_official_presence",
            )
        )

        evaluation = response.candidates[0].model_evaluations[0]
        assert evaluation.state is DiscoveryShortlistState.ELIGIBLE_FOR_DEEPER_RESEARCH
        assert evaluation.next_evidence_action is NextEvidenceAction.VERIFY_OFFICIAL_SOCIAL_PROFILE
        assert EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED in evaluation.missing_signal_types

    def test_social_candidate_missing_business_activity_does_not_enter_specialist_research(self):
        response = shortlist_discovery_candidates(
            request(
                CandidateShortlistInput(
                    candidate=candidate(),
                    evidence_signals=[
                        signal(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                    ],
                ),
                "social_presence.dormant_official_presence",
            )
        )

        evaluation = response.candidates[0].model_evaluations[0]
        assert evaluation.state is DiscoveryShortlistState.NEEDS_EVIDENCE
        assert EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED in (
            evaluation.missing_signal_types
        )

    def test_social_candidate_without_confirmed_identity_stays_hidden(self):
        response = shortlist_discovery_candidates(
            request(
                CandidateShortlistInput(
                    candidate=candidate(
                        source_provider="serper",
                        source_record_id="serper:glow",
                        source_types=["social_search"],
                    ),
                ),
                "social_presence.dormant_official_presence",
            )
        )

        assert response.candidates[0].state is DiscoveryShortlistState.NEEDS_IDENTITY_REVIEW

    def test_candidate_without_traceable_source_is_excluded(self):
        response = shortlist_discovery_candidates(
            request(
                CandidateShortlistInput(
                    candidate=candidate(
                        source_provider=None,
                        source_record_id=None,
                    )
                ),
                "web_conversion.no_verified_web_presence",
            )
        )

        entry = response.candidates[0]
        assert entry.state is DiscoveryShortlistState.EXCLUDED
        assert entry.next_evidence_action is NextEvidenceAction.NO_ACTION

    def test_same_input_always_produces_the_same_shortlist(self):
        shortlist_request = request(
            CandidateShortlistInput(candidate=candidate()),
            "web_conversion.no_verified_web_presence",
        )

        assert shortlist_discovery_candidates(shortlist_request) == shortlist_discovery_candidates(
            shortlist_request
        )
