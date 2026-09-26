from datetime import UTC, datetime

import pytest

from app.schemas.agent_outputs import OpportunityOutreachOutput, WebsiteResearchOutput
from app.schemas.prospect_evidence_brief import (
    BriefEvidence,
    BriefObjective,
    BriefProspect,
    BriefQualification,
)
from app.schemas.prospect_evidence_brief_context import TrustedProspectEvidenceBriefContext
from app.services.aggregate_verdict import AggregateVerdict
from app.services.prospect_evidence_brief import assemble_prospect_evidence_brief


NOW = datetime(2026, 9, 16, tzinfo=UTC)
MOBILE_KEY = "research_evidence:mobile"


def _context(verdict: AggregateVerdict) -> TrustedProspectEvidenceBriefContext:
    state = {
        AggregateVerdict.QUALIFIED: "likely",
        AggregateVerdict.NEEDS_REVIEW: "insufficient_evidence",
        AggregateVerdict.NOT_A_FIT: "not_eligible",
    }[verdict]
    evidence = BriefEvidence(
        key=MOBILE_KEY,
        signal_type="website_mobile_performance_measured",
        evidence_type="observed",
        supporting_value="Mobile PageSpeed was measured at 31/100.",
        numeric_value=31,
        source={
            "provider": "pagespeed_insights",
            "provider_record_id": "mobile",
            "retrieved_at": NOW,
        },
        captured_at=NOW,
    )
    return TrustedProspectEvidenceBriefContext(
        objective=BriefObjective(
            goal="Find suitable redesign prospects.",
            offering="Website redesign",
            desired_outcome="Prepare grounded outreach.",
        ),
        prospect=BriefProspect(
            business_name="Glow Salon",
            location="Lahore",
            business_descriptor="Beauty salon",
            official_website="https://glow.example",
            identity_verified=True,
        ),
        qualifications=[BriefQualification(
            opportunity_model_id="web_conversion.mobile_performance",
            state=state,
            reason="The mobile measurement was evaluated deterministically.",
            supporting_evidence_keys=[MOBILE_KEY],
            evaluated_at=NOW,
        )],
        evidence=[evidence],
        aggregate_verdict=verdict,
    )


def _opportunity() -> OpportunityOutreachOutput:
    finding = {
        "statement": "The measured mobile score supports a focused redesign pitch.",
        "claim_kind": "derived_metric",
        "evidence_keys": [MOBILE_KEY],
    }
    return OpportunityOutreachOutput(
        opportunity_summary=finding,
        pitch_angle={
            "statement": "Offer a mobile-focused website redesign.",
            "offering": "Website redesign",
            "evidence_keys": [MOBILE_KEY],
        },
        personalization_basis=[finding],
        forbidden_claims=["Do not claim the score proves lost sales."],
        outreach_drafts=[],
        caveats=["The score does not establish commercial impact."],
    )


def test_qualified_v2_report_is_deterministic_and_omits_legacy_sections():
    brief = assemble_prospect_evidence_brief(
        _context(AggregateVerdict.QUALIFIED), _opportunity()
    )
    dumped = brief.model_dump(mode="json")
    assert dumped["schema_version"] == 2
    assert dumped["opportunity_assessment"][0]["check"] == "Mobile performance"
    assert dumped["recommended_approach"]["forbidden_claims"]
    assert "findings" not in dumped
    assert "verdict" not in dumped
    assert "web_conversion.mobile_performance" not in str(dumped["opportunity_assessment"])


@pytest.mark.parametrize(
    "verdict",
    [AggregateVerdict.NEEDS_REVIEW, AggregateVerdict.NOT_A_FIT],
)
def test_nonqualified_v2_report_has_no_approach_or_outreach(verdict):
    brief = assemble_prospect_evidence_brief(_context(verdict), None)
    assert brief.recommended_approach is None
    assert brief.outreach_drafts == []
    if verdict is AggregateVerdict.NEEDS_REVIEW:
        assert brief.unresolved_evidence


def test_research_verified_website_absence_is_evidence_not_an_unresolved_requirement():
    qualifications = [
        BriefQualification(
            opportunity_model_id="web_conversion.no_verified_web_presence",
            state="likely",
            reason="No official website was verified.",
            supporting_evidence_keys=[MOBILE_KEY],
            evaluated_at=NOW,
        ),
        BriefQualification(
            opportunity_model_id="web_conversion.mobile_performance",
            state="insufficient_evidence",
            reason="More evidence is needed before this Opportunity Model can be evaluated: official website confirmed, website mobile performance measured.",
            evaluated_at=NOW,
        ),
        BriefQualification(
            opportunity_model_id="web_conversion.restaurant_customer_path",
            state="insufficient_evidence",
            reason="More evidence is needed before this Opportunity Model can be evaluated: official website confirmed, website restaurant primary path not observed.",
            evaluated_at=NOW,
        ),
    ]
    website_research = WebsiteResearchOutput(
        website_status="not_verified",
        findings=[],
        evidence_gaps=[
            "Official website is not confirmed or listed.",
            "Website mobile performance cannot be measured without a verified website.",
            "Website restaurant primary path cannot be observed without a verified website.",
        ],
        caveats=[
            "No official website was verified in the trusted provider record, not proof none exists elsewhere."
        ],
    )
    context = _context(AggregateVerdict.QUALIFIED).model_copy(
        update={
            "qualifications": qualifications,
            "website_research": website_research,
        }
    )

    brief = assemble_prospect_evidence_brief(context, _opportunity())

    assert [row.check for row in brief.opportunity_assessment] == [
        "Website presence",
        "Mobile performance",
        "Customer path",
    ]
    assert brief.unresolved_evidence == [
        "Mobile performance could not be evaluated because no official website was verified.",
        "The restaurant booking/customer path could not be evaluated because no official website was verified.",
    ]


def test_discovery_only_website_absence_is_rendered_as_unresolved():
    context = _context(AggregateVerdict.NEEDS_REVIEW).model_copy(
        update={
            "qualifications": [
                BriefQualification(
                    opportunity_model_id="web_conversion.no_verified_web_presence",
                    state="insufficient_evidence",
                    reason=(
                        "More evidence is needed before this Opportunity Model can be "
                        "evaluated: no verified official web presence."
                    ),
                    evaluated_at=NOW,
                )
            ],
            "website_research": WebsiteResearchOutput(
                website_status="not_verified",
                findings=[],
                evidence_gaps=[],
                caveats=[
                    "A directory omission does not prove that no website exists."
                ],
            ),
        }
    )

    brief = assemble_prospect_evidence_brief(context, None)

    assert brief.aggregate_verdict is AggregateVerdict.NEEDS_REVIEW
    assert brief.opportunity_assessment[0].result == "unresolved"
    assert brief.opportunity_assessment[0].evidence_summary == (
        "A discovery source did not list a website, but research-level website "
        "verification remains unresolved."
    )
    assert brief.recommended_approach is None
    assert brief.outreach_drafts == []
