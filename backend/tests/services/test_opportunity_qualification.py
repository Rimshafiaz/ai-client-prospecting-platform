import uuid
from datetime import UTC, datetime

import pytest

from app.models.company import Company
from app.models.opportunity_qualification import OpportunityQualification
from app.models.research_evidence import ResearchEvidence
from app.models.research_request import ResearchRequest, ResearchStatus
from app.schemas.evidence_gate import EvidenceGateState
from app.schemas.opportunity_models import EvidenceSignalType, IndustryOverlayId
from app.schemas.opportunity_qualification import (
    OpportunityQualificationRunRequest,
    OpportunityQualificationState,
)
from app.services.opportunity_model_catalog import get_opportunity_model
from app.services.aggregate_verdict import AggregateVerdict, aggregate_verdict
from app.services.opportunity_qualification import (
    QualificationEvidence,
    _evaluate_model,
    qualify_research_request,
)


NOW = datetime(2026, 9, 8, tzinfo=UTC)
SOCIAL_INDUSTRIES = (
    IndustryOverlayId.BEAUTY_WELLNESS,
    IndustryOverlayId.RESTAURANTS_CAFES,
    IndustryOverlayId.FITNESS_GYMS,
    IndustryOverlayId.BOUTIQUES_RETAIL,
)


def evidence(signal_type: EvidenceSignalType, numeric_value: float | None = None):
    return QualificationEvidence(
        signal_type=signal_type,
        numeric_value=numeric_value,
        key=f"evidence:{signal_type.value}",
    )


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class FakeSession:
    def __init__(self, evidence_records):
        self.evidence_records = evidence_records
        self.added = []
        self.committed = False

    def scalar(self, statement):
        return None

    def scalars(self, statement):
        return FakeScalars(self.evidence_records)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True


class TestOpportunityModelEvaluation:
    def test_discovery_no_listed_website_alone_is_insufficient_evidence(self):
        decision = _evaluate_model(
            get_opportunity_model("web_conversion.no_verified_web_presence"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE),
            ],
        )

        assert decision.state is OpportunityQualificationState.INSUFFICIENT_EVIDENCE
        assert "no verified official web presence" in decision.reason

    def test_not_verified_status_without_research_level_evidence_is_insufficient(self):
        decision = _evaluate_model(
            get_opportunity_model("web_conversion.no_verified_web_presence"),
            IndustryOverlayId.RESTAURANTS_CAFES,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE),
            ],
        )

        assert decision.state is OpportunityQualificationState.INSUFFICIENT_EVIDENCE
        assert aggregate_verdict([decision.state]) is AggregateVerdict.NEEDS_REVIEW

    def test_research_level_no_verified_web_presence_is_likely(self):
        decision = _evaluate_model(
            get_opportunity_model("web_conversion.no_verified_web_presence"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE),
                evidence(EvidenceSignalType.NO_VERIFIED_OFFICIAL_WEB_PRESENCE),
            ],
        )

        assert decision.state is OpportunityQualificationState.LIKELY
        assert decision.supporting_evidence_keys == [
            "evidence:no_verified_official_web_presence"
        ]

    def test_low_mobile_score_is_a_likely_mobile_performance_opportunity(self):
        decision = _evaluate_model(
            get_opportunity_model("web_conversion.mobile_performance"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED),
                evidence(EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED, 31),
            ],
        )

        assert decision.state is OpportunityQualificationState.LIKELY
        assert "31/100" in decision.reason

    def test_healthy_mobile_score_is_not_eligible(self):
        decision = _evaluate_model(
            get_opportunity_model("web_conversion.mobile_performance"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED),
                evidence(EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED, 91),
            ],
        )

        assert decision.state is OpportunityQualificationState.NOT_ELIGIBLE
        assert "91/100" in decision.reason

    def test_social_dormancy_requires_independent_business_activity_evidence(self):
        decision = _evaluate_model(
            get_opportunity_model("social_presence.dormant_official_presence"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_DORMANCY_MEASURED, 120),
            ],
        )

        assert decision.state is OpportunityQualificationState.INSUFFICIENT_EVIDENCE
        assert "business activity confirmed" in decision.reason

    @pytest.mark.parametrize("industry", SOCIAL_INDUSTRIES)
    def test_social_dormancy_is_likely_for_opted_in_visual_industries(self, industry):
        decision = _evaluate_model(
            get_opportunity_model("social_presence.dormant_official_presence"),
            industry,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED),
                evidence(EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_DORMANCY_MEASURED, 90),
            ],
        )

        assert decision.state is OpportunityQualificationState.LIKELY

    def test_social_dormancy_is_not_validated_for_clinics(self):
        decision = _evaluate_model(
            get_opportunity_model("social_presence.dormant_official_presence"),
            IndustryOverlayId.DENTAL_SELECTED_CLINICS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED),
                evidence(EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_DORMANCY_MEASURED, 90),
            ],
        )

        assert decision.state is OpportunityQualificationState.NOT_ELIGIBLE

    def test_recent_social_activity_is_not_a_dormancy_opportunity(self):
        decision = _evaluate_model(
            get_opportunity_model("social_presence.dormant_official_presence"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED),
                evidence(EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_DORMANCY_MEASURED, 14),
            ],
        )

        assert decision.state is OpportunityQualificationState.NOT_ELIGIBLE

    def test_five_day_social_activity_is_not_a_dormancy_opportunity(self):
        decision = _evaluate_model(
            get_opportunity_model("social_presence.dormant_official_presence"),
            IndustryOverlayId.RESTAURANTS_CAFES,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED),
                evidence(EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED),
                evidence(EvidenceSignalType.SOCIAL_DORMANCY_MEASURED, 5),
            ],
        )

        assert decision.state is OpportunityQualificationState.NOT_ELIGIBLE

    @pytest.mark.parametrize(
        "missing_signal",
        [
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED,
            EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED,
            EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED,
            EvidenceSignalType.SOCIAL_DORMANCY_MEASURED,
        ],
    )
    def test_social_dormancy_requires_every_evidence_dimension(self, missing_signal):
        complete_evidence = [
            evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
            evidence(EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED),
            evidence(EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED),
            evidence(EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED),
            evidence(EvidenceSignalType.SOCIAL_DORMANCY_MEASURED, 90),
        ]
        decision = _evaluate_model(
            get_opportunity_model("social_presence.dormant_official_presence"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [item for item in complete_evidence if item.signal_type is not missing_signal],
        )

        assert decision.state is OpportunityQualificationState.INSUFFICIENT_EVIDENCE

    def test_no_verified_web_presence_is_not_eligible_after_an_official_site_is_verified(self):
        decision = _evaluate_model(
            get_opportunity_model("web_conversion.no_verified_web_presence"),
            IndustryOverlayId.BEAUTY_WELLNESS,
            [
                evidence(EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED),
                evidence(EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE),
                evidence(EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED),
            ],
        )

        assert decision.state is OpportunityQualificationState.NOT_ELIGIBLE
        assert "verified official website" in decision.reason


class TestOpportunityQualificationPersistence:
    def test_known_prospect_qualification_persists_a_repeatable_decision(self):
        request_id = uuid.uuid4()
        research_request = ResearchRequest(
            id=request_id,
            company_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            status=ResearchStatus.COMPLETED,
            evidence_gate_state=EvidenceGateState.READY_FOR_DEEPER_RESEARCH,
            opportunity_model_selection={
                "model_ids": ["web_conversion.mobile_performance"],
                "confirmed_by_user": True,
            },
            objective={
                "mode": "known_prospect",
                "resolved_target": {
                    "business_name": "Glow Salon",
                    "website": "https://glowsalon.example",
                    "identity_state": "verified",
                    "source": {"source_url": "https://glowsalon.example/about"},
                },
            },
            specialist_outputs={
                "website": {
                    "website_status": "verified",
                    "findings": [],
                    "evidence_gaps": ["Agent prose must not affect qualification."],
                    "caveats": [],
                },
                "social": {
                    "presence_status": "unresolved",
                    "findings": [],
                    "evidence_gaps": ["Agent prose must not affect qualification."],
                    "caveats": [],
                },
            },
        )
        measurement = ResearchEvidence(
            id=uuid.uuid4(),
            research_request_id=request_id,
            signal_type=EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED.value,
            evidence_type="observed",
            supporting_value="Measured 31/100.",
            numeric_value=31,
            source_provider="pagespeed_insights",
            source_identity_key="pagespeed:https://glowsalon.example",
            source_url="https://glowsalon.example",
            retrieved_at=NOW,
            captured_at=NOW,
        )
        db = FakeSession([measurement])
        scope = OpportunityQualificationRunRequest(
            industry=IndustryOverlayId.BEAUTY_WELLNESS,
            model_selection={
                "model_ids": ["web_conversion.mobile_performance"],
                "confirmed_by_user": True,
            },
        )

        decisions = qualify_research_request(
            db,
            research_request,
            Company(id=research_request.company_id, user_id=research_request.user_id, name="Glow Salon"),
            None,
            scope,
        )

        assert decisions[0].state is OpportunityQualificationState.LIKELY
        assert db.committed is True
        saved = db.added[0]
        assert isinstance(saved, OpportunityQualification)
        assert saved.opportunity_model_id == "web_conversion.mobile_performance"
        assert saved.state == OpportunityQualificationState.LIKELY.value
