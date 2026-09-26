from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.campaign_candidate_selection import CampaignCandidateSelection
from app.models.campaign_run import CampaignRun
from app.models.company import Company
from app.models.research_evidence import ResearchEvidence
from app.models.research_request import ResearchRequest, ResearchStatus
from app.repositories.opportunity_qualifications import upsert_opportunity_qualification
from app.repositories.research_evidence import list_research_evidence_for_user
from app.schemas.evidence_gate import EvidenceGateState
from app.schemas.opportunity_models import (
    EvidenceSignal,
    EvidenceSignalType,
    IndustryOverlayId,
    OpportunityModelSelection,
)
from app.schemas.opportunity_qualification import (
    OpportunityQualificationRunRequest,
    OpportunityQualificationState,
)
from app.services.evidence_gate import target_from_research_request
from app.services.local_business_discovery import LocalBusinessDiscoveryError, resolve_industry
from app.services.opportunity_model_catalog import OpportunityModel, get_opportunity_model


POOR_MOBILE_PERFORMANCE_THRESHOLD = 50.0
DORMANT_SOCIAL_DAYS_THRESHOLD = 60.0
OVERLAY_MODEL_REASONS = {
    "web_conversion.restaurant_customer_path": (
        "The official homepage did not expose the expected restaurant customer paths recorded in the supporting evidence."
    ),
    "web_conversion.fitness_membership_path": (
        "The official homepage did not expose a trial, membership, class, trainer, or contact path."
    ),
    "web_conversion.retail_product_path": (
        "The official homepage did not expose a catalogue, store, product-enquiry, contact, or social path."
    ),
    "web_conversion.clinic_patient_path": (
        "The official homepage has an incomplete public path across service navigation, appointment/contact, and location/contact information."
    ),
}


class OpportunityQualificationError(ValueError):
    pass


@dataclass(frozen=True)
class QualificationEvidence:
    signal_type: EvidenceSignalType
    numeric_value: float | None
    key: str


@dataclass(frozen=True)
class QualificationDecision:
    model: OpportunityModel
    state: OpportunityQualificationState
    reason: str
    supporting_evidence_keys: list[str]


def qualify_research_request(
    db: Session,
    research_request: ResearchRequest,
    company: Company,
    selection: CampaignCandidateSelection | None,
    request: OpportunityQualificationRunRequest,
) -> list[QualificationDecision]:
    if research_request.status is not ResearchStatus.COMPLETED:
        raise OpportunityQualificationError("Finish the evidence review before qualifying opportunities.")
    if research_request.evidence_gate_state is not EvidenceGateState.READY_FOR_DEEPER_RESEARCH:
        raise OpportunityQualificationError("Accepted evidence is required before qualifying opportunities.")

    model_selection, industry = _qualification_scope(db, research_request, selection, request)
    target = target_from_research_request(research_request, company, selection)
    evidence = _qualification_evidence(
        list_research_evidence_for_user(db, research_request.id, research_request.user_id),
        selection,
        identity_verified=target.identity_verified,
        official_website_verified=target.official_website is not None,
    )
    decisions = [
        _evaluate_model(get_opportunity_model(model_id), industry, evidence)
        for model_id in model_selection.model_ids
    ]
    evaluated_at = datetime.now(UTC)
    for decision in decisions:
        upsert_opportunity_qualification(
            db=db,
            research_request_id=research_request.id,
            opportunity_model_id=decision.model.id,
            state=decision.state,
            reason=decision.reason,
            supporting_evidence_keys=decision.supporting_evidence_keys,
            evaluated_at=evaluated_at,
        )
    db.commit()
    return decisions


def _qualification_scope(
    db: Session,
    research_request: ResearchRequest,
    selection: CampaignCandidateSelection | None,
    request: OpportunityQualificationRunRequest,
) -> tuple[OpportunityModelSelection, IndustryOverlayId]:
    try:
        model_selection = OpportunityModelSelection.model_validate(
            research_request.opportunity_model_selection
        )
    except ValueError as error:
        raise OpportunityQualificationError(
            "A valid persisted Opportunity Model selection is required before qualification."
        ) from error
    if selection is not None:
        campaign_run = db.get(CampaignRun, selection.campaign_run_id)
        if campaign_run is None:
            raise OpportunityQualificationError("The selected campaign run is unavailable.")
        try:
            return (
                model_selection,
                resolve_industry(str(campaign_run.criteria_snapshot.get("business_category", ""))),
            )
        except (LocalBusinessDiscoveryError, ValueError) as error:
            raise OpportunityQualificationError(str(error)) from error

    objective = research_request.objective or {}
    if objective.get("mode") != "known_prospect":
        raise OpportunityQualificationError(
            "Qualification requires a campaign selection or a confirmed known-prospect scope."
        )
    if request.industry is None:
        raise OpportunityQualificationError(
            "Select the business industry before qualifying a known prospect."
        )
    return model_selection, request.industry


def _qualification_evidence(
    persisted_evidence: list[ResearchEvidence],
    selection: CampaignCandidateSelection | None,
    identity_verified: bool,
    official_website_verified: bool,
) -> list[QualificationEvidence]:
    evidence = [
        QualificationEvidence(
            signal_type=EvidenceSignalType(item.signal_type),
            numeric_value=item.numeric_value,
            key=f"research_evidence:{item.id}",
        )
        for item in persisted_evidence
    ]
    if selection is not None:
        evidence.extend(_selection_evidence(selection))
        if _selection_has_no_listed_website(selection):
            evidence.append(
                QualificationEvidence(
                    signal_type=EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE,
                    numeric_value=None,
                    key=f"selection_candidate:{selection.id}:no_listed_official_website",
                )
            )
    if identity_verified:
        evidence.append(
            QualificationEvidence(
                signal_type=EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
                numeric_value=None,
                key="resolved_target:identity",
            )
        )
    if official_website_verified:
        evidence.append(
            QualificationEvidence(
                signal_type=EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
                numeric_value=None,
                key="resolved_target:official_website",
            )
        )
    return evidence


def _selection_evidence(selection: CampaignCandidateSelection) -> list[QualificationEvidence]:
    result = []
    for index, value in enumerate(selection.evidence_snapshot):
        try:
            signal = EvidenceSignal.model_validate(value)
        except ValueError:
            continue
        result.append(
            QualificationEvidence(
                signal_type=signal.signal_type,
                numeric_value=signal.numeric_value,
                key=f"selection_evidence:{selection.id}:{index}",
            )
        )
    return result


def _selection_has_no_listed_website(selection: CampaignCandidateSelection) -> bool:
    candidate = selection.candidate_snapshot
    return (
        candidate.get("website") is None
        and "local_places" in candidate.get("discovery_source_types", [])
    )


def _evaluate_model(
    model: OpportunityModel,
    industry: IndustryOverlayId,
    evidence: list[QualificationEvidence],
) -> QualificationDecision:
    if industry not in model.applicable_industries:
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.NOT_ELIGIBLE,
            reason="This Opportunity Model is not validated for the selected industry.",
            supporting_evidence_keys=[],
        )

    if (
        model.id == "web_conversion.no_verified_web_presence"
        and _for_signal(evidence, EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED)
    ):
        official_website = _for_signal(
            evidence, EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED
        )
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.NOT_ELIGIBLE,
            reason="A verified official website is now available for this business.",
            supporting_evidence_keys=[item.key for item in official_website],
        )

    missing = [
        signal_type
        for signal_type in model.required_signal_types
        if not _for_signal(evidence, signal_type)
    ]
    if missing:
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.INSUFFICIENT_EVIDENCE,
            reason=(
                "More evidence is needed before this Opportunity Model can be evaluated: "
                + ", ".join(signal_type.value.replace("_", " ") for signal_type in missing)
                + "."
            ),
            supporting_evidence_keys=[],
        )

    if model.id == "web_conversion.mobile_performance":
        return _mobile_performance_decision(model, evidence)
    if model.id == "social_presence.dormant_official_presence":
        return _social_dormancy_decision(model, evidence)
    if model.id == "web_conversion.no_verified_web_presence":
        no_website = _for_signal(
            evidence, EvidenceSignalType.NO_VERIFIED_OFFICIAL_WEB_PRESENCE
        )
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.LIKELY,
            reason=(
                "Bounded identity-aware website verification completed without verifying "
                "an official website. This does not prove that no website exists elsewhere."
            ),
            supporting_evidence_keys=[item.key for item in no_website],
        )

    if model.id in OVERLAY_MODEL_REASONS:
        supporting = _supporting_evidence(model, evidence)
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.LIKELY,
            reason=OVERLAY_MODEL_REASONS[model.id],
            supporting_evidence_keys=[item.key for item in supporting],
        )

    supporting = _supporting_evidence(model, evidence)
    return QualificationDecision(
        model=model,
        state=OpportunityQualificationState.LIKELY,
        reason="All required observable evidence for this Opportunity Model is present.",
        supporting_evidence_keys=[item.key for item in supporting],
    )


def _mobile_performance_decision(
    model: OpportunityModel,
    evidence: list[QualificationEvidence],
) -> QualificationDecision:
    measurements = _for_signal(evidence, EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED)
    score = next((item.numeric_value for item in measurements if item.numeric_value is not None), None)
    if score is None:
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.INSUFFICIENT_EVIDENCE,
            reason="The mobile performance measurement does not contain a usable numeric score.",
            supporting_evidence_keys=[item.key for item in measurements],
        )
    if score > POOR_MOBILE_PERFORMANCE_THRESHOLD:
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.NOT_ELIGIBLE,
            reason=(
                f"The measured mobile performance score is {score:g}/100, above the "
                f"current poor-performance threshold of {POOR_MOBILE_PERFORMANCE_THRESHOLD:g}/100."
            ),
            supporting_evidence_keys=[item.key for item in _supporting_evidence(model, evidence)],
        )
    return QualificationDecision(
        model=model,
        state=OpportunityQualificationState.LIKELY,
        reason=(
            f"The verified official website measured {score:g}/100 on mobile, at or below the "
            f"current poor-performance threshold of {POOR_MOBILE_PERFORMANCE_THRESHOLD:g}/100."
        ),
        supporting_evidence_keys=[item.key for item in _supporting_evidence(model, evidence)],
    )


def _social_dormancy_decision(
    model: OpportunityModel,
    evidence: list[QualificationEvidence],
) -> QualificationDecision:
    measurements = _for_signal(evidence, EvidenceSignalType.SOCIAL_DORMANCY_MEASURED)
    days = next((item.numeric_value for item in measurements if item.numeric_value is not None), None)
    if days is None:
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.INSUFFICIENT_EVIDENCE,
            reason="The social dormancy measurement does not contain a usable number of days.",
            supporting_evidence_keys=[item.key for item in measurements],
        )
    if days < DORMANT_SOCIAL_DAYS_THRESHOLD:
        return QualificationDecision(
            model=model,
            state=OpportunityQualificationState.NOT_ELIGIBLE,
            reason=(
                f"The latest observed official post was {days:g} day(s) ago, below the "
                f"current dormancy threshold of {DORMANT_SOCIAL_DAYS_THRESHOLD:g} days."
            ),
            supporting_evidence_keys=[item.key for item in _supporting_evidence(model, evidence)],
        )
    return QualificationDecision(
        model=model,
        state=OpportunityQualificationState.LIKELY,
        reason=(
            f"The verified official profile's latest observed post was {days:g} day(s) ago, "
            f"meeting the current dormancy threshold of {DORMANT_SOCIAL_DAYS_THRESHOLD:g} days."
        ),
        supporting_evidence_keys=[item.key for item in _supporting_evidence(model, evidence)],
    )


def _for_signal(
    evidence: list[QualificationEvidence],
    signal_type: EvidenceSignalType,
) -> list[QualificationEvidence]:
    return [item for item in evidence if item.signal_type is signal_type]


def _supporting_evidence(
    model: OpportunityModel,
    evidence: list[QualificationEvidence],
) -> list[QualificationEvidence]:
    return [
        item
        for signal_type in model.required_signal_types
        for item in _for_signal(evidence, signal_type)
    ]
