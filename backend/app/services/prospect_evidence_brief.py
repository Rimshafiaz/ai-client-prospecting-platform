import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.campaign_candidate_selection import CampaignCandidateSelection
from app.models.company import Company
from app.models.research_evidence import ResearchEvidence
from app.models.research_request import ResearchRequest, ResearchStatus
from app.repositories.opportunity_qualifications import list_opportunity_qualifications_for_user
from app.repositories.research_evidence import list_research_evidence_for_user
from app.repositories.research_social_observations import list_social_observations_for_user
from app.repositories.research_sources import list_research_sources_for_user
from app.schemas.evidence_gate import EvidenceGateState, SourceAdmissionState
from app.schemas.agent_outputs import OpportunityOutreachOutput, SocialResearchOutput, WebsiteResearchOutput
from app.schemas.opportunity_models import (
    EvidenceSignal,
    EvidenceSignalType,
    EvidenceSource,
    EvidenceType,
    OpportunityModelSelection,
    ServiceFamily,
)
from app.schemas.opportunity_qualification import OpportunityQualificationState
from app.schemas.prospect_evidence_brief import (
    BriefContactPath,
    BriefEvidence,
    BriefObjective,
    BriefProspect,
    BriefQualification,
    BriefSource,
    ContactEvidenceState,
    ContactPathType,
    OpportunityAssessmentRow,
    ProspectEvidenceBrief,
    RecommendedApproach,
)
from app.schemas.prospect_evidence_brief_context import TrustedProspectEvidenceBriefContext
from app.services.aggregate_verdict import AggregateVerdict, aggregate_verdict
from app.services.evidence_gate import target_from_research_request
from app.services.opportunity_model_catalog import get_opportunity_model


MAX_BRIEF_SOURCES = 12
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])([\w.+-]+@[\w-]+(?:\.[\w-]+)+)(?![\w.-])", re.IGNORECASE)
SOCIAL_CONTACT_TYPES = {
    "facebook.com": ContactPathType.FACEBOOK,
    "instagram.com": ContactPathType.INSTAGRAM,
    "linkedin.com": ContactPathType.LINKEDIN,
    "linkedin.cn": ContactPathType.LINKEDIN,
}


class ProspectEvidenceBriefContextError(ValueError):
    pass


def build_prospect_evidence_brief_context(
    db: Session,
    research_request: ResearchRequest,
    company: Company,
    selection: CampaignCandidateSelection | None,
) -> TrustedProspectEvidenceBriefContext:
    _require_ready_request(research_request)
    target = target_from_research_request(research_request, company, selection)
    if not target.identity_verified:
        raise ProspectEvidenceBriefContextError("A Prospect Evidence Brief requires a verified business identity.")

    objective = _objective_from_request(research_request)
    evidence = _brief_evidence(
        db,
        research_request,
        selection,
        target.identity_verified,
        target.official_website is not None,
    )
    qualifications = _brief_qualifications(db, research_request)
    sources = _brief_sources(db, research_request)
    contacts = _brief_contacts(
        db,
        research_request,
        selection,
        target.official_website,
        evidence,
        sources,
    )
    selected = _selected_models(research_request)
    selected_ids = set(selected.model_ids)
    qualifications = [
        item for item in qualifications if item.opportunity_model_id in selected_ids
    ]
    if {item.opportunity_model_id for item in qualifications} != selected_ids:
        raise ProspectEvidenceBriefContextError(
            "Every selected Opportunity Model must have a qualification result."
        )
    families = {
        get_opportunity_model(model_id).service_family for model_id in selected.model_ids
    }
    outputs = research_request.specialist_outputs or {}
    website = _specialist_output(
        outputs,
        "website",
        WebsiteResearchOutput,
        ServiceFamily.WEB_CONVERSION in families,
    )
    social = _specialist_output(
        outputs,
        "social",
        SocialResearchOutput,
        ServiceFamily.SOCIAL_PRESENCE_CONTENT in families,
    )
    evidence_keys = {item.key for item in evidence}
    for specialist in (website, social):
        if specialist is not None and any(
            not set(finding.evidence_keys) <= evidence_keys for finding in specialist.findings
        ):
            raise ProspectEvidenceBriefContextError(
                "Persisted specialist output references unavailable canonical evidence."
            )
    return TrustedProspectEvidenceBriefContext(
        objective=objective,
        prospect=BriefProspect(
            business_name=target.company_name,
            location=target.location,
            business_descriptor=_business_descriptor(selection),
            official_website=target.official_website,
            identity_verified=target.identity_verified,
        ),
        qualifications=qualifications,
        evidence=evidence,
        sources=sources,
        contacts=contacts,
        aggregate_verdict=aggregate_verdict([item.state for item in qualifications]),
        website_research=website,
        social_research=social,
    )
def assemble_prospect_evidence_brief(
    context: TrustedProspectEvidenceBriefContext,
    opportunity_outreach: OpportunityOutreachOutput | None,
) -> ProspectEvidenceBrief:
    if context.aggregate_verdict is AggregateVerdict.QUALIFIED:
        if opportunity_outreach is None:
            raise ProspectEvidenceBriefContextError(
                "A qualified report requires approved Opportunity and Outreach output."
            )
        recommended = RecommendedApproach(
            opportunity_summary=opportunity_outreach.opportunity_summary,
            pitch_angle=opportunity_outreach.pitch_angle,
            personalization_basis=opportunity_outreach.personalization_basis,
            forbidden_claims=opportunity_outreach.forbidden_claims,
            caveats=opportunity_outreach.caveats,
        )
        drafts = opportunity_outreach.outreach_drafts
    else:
        if opportunity_outreach is not None:
            raise ProspectEvidenceBriefContextError(
                "A non-qualified report cannot include Opportunity and Outreach output."
            )
        recommended = None
        drafts = []
    assessment = [_assessment_row(item, context.evidence) for item in context.qualifications]
    unresolved = _unresolved_evidence(context)
    return ProspectEvidenceBrief(
        schema_version=2,
        objective=context.objective,
        prospect=context.prospect,
        qualifications=context.qualifications,
        aggregate_verdict=context.aggregate_verdict,
        verdict_explanation=_verdict_explanation(context.aggregate_verdict, assessment),
        opportunity_assessment=assessment,
        recommended_approach=recommended,
        outreach_drafts=drafts,
        contacts=context.contacts,
        unresolved_evidence=unresolved,
        evidence=context.evidence,
        sources=context.sources,
    )


MODEL_LABELS = {
    "web_conversion.no_verified_web_presence": "Website presence",
    "web_conversion.mobile_performance": "Mobile performance",
    "web_conversion.booking_contact_path": "Booking and contact path",
    "web_conversion.restaurant_reservation_path": "Reservation path",
    "web_conversion.restaurant_customer_path": "Customer path",
    "web_conversion.fitness_membership_path": "Membership enquiry path",
    "web_conversion.retail_product_path": "Product enquiry path",
    "web_conversion.clinic_patient_path": "Patient contact path",
    "social_presence.dormant_official_presence": "Social activity",
}

MISSING_WEBSITE_DEPENDENCY_LABELS = {
    "web_conversion.mobile_performance": "Mobile performance",
    "web_conversion.booking_contact_path": "The booking/contact path",
    "web_conversion.restaurant_reservation_path": "The restaurant booking/customer path",
    "web_conversion.restaurant_customer_path": "The restaurant booking/customer path",
    "web_conversion.fitness_membership_path": "The membership enquiry path",
    "web_conversion.retail_product_path": "The product enquiry path",
    "web_conversion.clinic_patient_path": "The patient contact path",
}


def _assessment_row(
    qualification: BriefQualification,
    evidence: list[BriefEvidence],
) -> OpportunityAssessmentRow:
    evidence_by_key = {item.key: item for item in evidence}
    supporting = [
        evidence_by_key[key]
        for key in qualification.supporting_evidence_keys
        if key in evidence_by_key
    ]
    if qualification.state is OpportunityQualificationState.LIKELY:
        result = "opportunity_found"
    elif qualification.state is OpportunityQualificationState.NOT_ELIGIBLE:
        result = (
            "not_an_opportunity"
            if qualification.opportunity_model_id == "web_conversion.no_verified_web_presence"
            else "no_issue_observed"
        )
    else:
        result = "unresolved"
    return OpportunityAssessmentRow(
        check=MODEL_LABELS[qualification.opportunity_model_id],
        result=result,
        evidence_summary=_assessment_summary(qualification, supporting),
        evidence_keys=qualification.supporting_evidence_keys,
    )


def _assessment_summary(
    qualification: BriefQualification,
    evidence: list[BriefEvidence],
) -> str:
    model_id = qualification.opportunity_model_id
    numeric = next((item.numeric_value for item in evidence if item.numeric_value is not None), None)
    if model_id == "web_conversion.no_verified_web_presence":
        if qualification.state is OpportunityQualificationState.NOT_ELIGIBLE:
            return "An official website was verified."
        if qualification.state is OpportunityQualificationState.LIKELY:
            return "Bounded website verification did not identify an official website."
        return (
            "A discovery source did not list a website, but research-level website "
            "verification remains unresolved."
        )
    if model_id == "web_conversion.mobile_performance" and numeric is not None:
        return f"The mobile PageSpeed score was {numeric:g}/100."
    if model_id == "social_presence.dormant_official_presence" and numeric is not None:
        return f"The latest verified social post was {numeric:g} days ago."
    opportunity_evidence = [
        item for item in evidence if item.signal_type is not EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED
    ]
    if opportunity_evidence:
        return opportunity_evidence[-1].supporting_value.strip()
    if qualification.state is OpportunityQualificationState.INSUFFICIENT_EVIDENCE:
        return "Required evidence is still unresolved."
    return qualification.reason.strip()


def _verdict_explanation(
    verdict: AggregateVerdict,
    assessment: list[OpportunityAssessmentRow],
) -> str:
    if verdict is AggregateVerdict.QUALIFIED:
        row = next(item for item in assessment if item.result == "opportunity_found")
        return f"{row.evidence_summary} This supports the selected opportunity."
    if verdict is AggregateVerdict.NOT_A_FIT:
        rows = [
            item.evidence_summary
            for item in assessment
            if item.result in {"not_an_opportunity", "no_issue_observed"}
        ]
        return rows[0] if rows else "The selected opportunity did not meet its requirements."
    unresolved = next(
        (item.evidence_summary for item in assessment if item.result == "unresolved"),
        "Required evidence is still unresolved.",
    )
    return f"No qualifying opportunity was confirmed. {unresolved}"


def _unresolved_evidence(context: TrustedProspectEvidenceBriefContext) -> list[str]:
    values = []
    website_blocked_models = set()
    if (
        context.website_research is not None
        and context.website_research.website_status == "not_verified"
    ):
        for qualification in context.qualifications:
            model_id = qualification.opportunity_model_id
            if (
                qualification.state is OpportunityQualificationState.INSUFFICIENT_EVIDENCE
                and model_id in MISSING_WEBSITE_DEPENDENCY_LABELS
                and EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED
                in get_opportunity_model(model_id).required_signal_types
            ):
                subject = MISSING_WEBSITE_DEPENDENCY_LABELS[model_id]
                values.append(
                    f"{subject} could not be evaluated because no official website was verified."
                )
                website_blocked_models.add(model_id)
    elif context.website_research is not None:
        values.extend(context.website_research.evidence_gaps)
    if context.social_research is not None:
        values.extend(context.social_research.evidence_gaps)
    values.extend(
        item.reason
        for item in context.qualifications
        if item.state is OpportunityQualificationState.INSUFFICIENT_EVIDENCE
        and item.opportunity_model_id not in website_blocked_models
    )
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:12]


def _selected_models(research_request: ResearchRequest) -> OpportunityModelSelection:
    try:
        return OpportunityModelSelection.model_validate(
            research_request.opportunity_model_selection
        )
    except ValueError as error:
        raise ProspectEvidenceBriefContextError(
            "A valid persisted Opportunity Model selection is required."
        ) from error


def _specialist_output(outputs, namespace, model, required):
    value = outputs.get(namespace)
    if not required:
        return None
    if value is None:
        raise ProspectEvidenceBriefContextError(
            f"Required {namespace} specialist output is unavailable."
        )
    try:
        return model.model_validate(value)
    except ValueError as error:
        raise ProspectEvidenceBriefContextError(
            f"Required {namespace} specialist output is invalid."
        ) from error


def _business_descriptor(selection: CampaignCandidateSelection | None) -> str | None:
    if selection is None:
        return None
    for key in ("business_category", "category", "industry"):
        value = selection.candidate_snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None


def _require_ready_request(research_request: ResearchRequest) -> None:
    if research_request.status is not ResearchStatus.COMPLETED:
        raise ProspectEvidenceBriefContextError("Finish the evidence review before building a Prospect Evidence Brief.")
    if research_request.evidence_gate_state is not EvidenceGateState.READY_FOR_DEEPER_RESEARCH:
        raise ProspectEvidenceBriefContextError("Accepted evidence is required before building a Prospect Evidence Brief.")


def _objective_from_request(research_request: ResearchRequest) -> BriefObjective:
    objective = research_request.objective or {}
    try:
        return BriefObjective(
            goal=objective.get("goal"),
            offering=objective.get("offering"),
            desired_outcome=objective.get("desired_outcome"),
        )
    except ValueError as error:
        raise ProspectEvidenceBriefContextError(
            "A Prospect Evidence Brief requires the user's goal, offering, and desired outcome."
        ) from error


def _brief_evidence(
    db: Session,
    research_request: ResearchRequest,
    selection: CampaignCandidateSelection | None,
    identity_verified: bool,
    official_website_verified: bool,
) -> list[BriefEvidence]:
    evidence = [
        _persisted_evidence(item)
        for item in list_research_evidence_for_user(
            db,
            research_request.id,
            research_request.user_id,
        )
    ]
    if selection is not None:
        evidence.extend(_selection_evidence(selection))
        if _selection_has_no_listed_website(selection):
            evidence.append(_no_listed_website_evidence(selection))
    evidence.extend(
        _resolved_target_evidence(
            research_request,
            selection,
            identity_verified,
            official_website_verified,
        )
    )
    if not evidence:
        raise ProspectEvidenceBriefContextError("No structured evidence is available for the Prospect Evidence Brief.")
    return evidence


def _persisted_evidence(item: ResearchEvidence) -> BriefEvidence:
    return BriefEvidence(
        key=f"research_evidence:{item.id}",
        signal_type=EvidenceSignalType(item.signal_type),
        evidence_type=EvidenceType(item.evidence_type),
        supporting_value=item.supporting_value,
        numeric_value=item.numeric_value,
        source=EvidenceSource(
            provider=item.source_provider,
            provider_record_id=item.source_record_id,
            source_url=item.source_url,
            retrieved_at=item.retrieved_at,
        ),
        captured_at=item.captured_at,
    )


def _selection_evidence(selection: CampaignCandidateSelection) -> list[BriefEvidence]:
    evidence = []
    for index, value in enumerate(selection.evidence_snapshot):
        try:
            signal = EvidenceSignal.model_validate(value)
        except ValueError:
            continue
        evidence.append(
            BriefEvidence(
                key=f"selection_evidence:{selection.id}:{index}",
                signal_type=signal.signal_type,
                evidence_type=signal.evidence_type,
                supporting_value=signal.supporting_value,
                numeric_value=signal.numeric_value,
                source=signal.source,
                captured_at=signal.captured_at,
            )
        )
    return evidence


def _selection_has_no_listed_website(selection: CampaignCandidateSelection) -> bool:
    candidate = selection.candidate_snapshot
    return candidate.get("website") is None and "local_places" in candidate.get(
        "discovery_source_types", []
    )


def _no_listed_website_evidence(selection: CampaignCandidateSelection) -> BriefEvidence:
    candidate = selection.candidate_snapshot
    source = EvidenceSource(
        provider=candidate["source_provider"],
        provider_record_id=candidate.get("source_record_id"),
        source_url=_first_url(candidate.get("supporting_source_urls", [])),
        retrieved_at=candidate["source_retrieved_at"],
    )
    return BriefEvidence(
        key=f"selection_candidate:{selection.id}:no_listed_official_website",
        signal_type=EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE,
        evidence_type=EvidenceType.OBSERVED,
        supporting_value="No official website was listed in the accepted business source.",
        source=source,
        captured_at=source.retrieved_at,
    )


def _resolved_target_evidence(
    research_request: ResearchRequest,
    selection: CampaignCandidateSelection | None,
    identity_verified: bool,
    official_website_verified: bool,
) -> list[BriefEvidence]:
    if not identity_verified:
        return []
    source = _resolved_target_source(research_request, selection)
    if source is None:
        return []
    evidence = [
        BriefEvidence(
            key="resolved_target:identity",
            signal_type=EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            evidence_type=EvidenceType.OBSERVED,
            supporting_value="The business identity was verified.",
            source=source,
            captured_at=source.retrieved_at,
        )
    ]
    if official_website_verified:
        evidence.append(
            BriefEvidence(
                key="resolved_target:official_website",
                signal_type=EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
                evidence_type=EvidenceType.OBSERVED,
                supporting_value="An official website was verified for the business.",
                source=source,
                captured_at=source.retrieved_at,
            )
        )
    return evidence


def _resolved_target_source(
    research_request: ResearchRequest,
    selection: CampaignCandidateSelection | None,
) -> EvidenceSource | None:
    objective = research_request.objective or {}
    target = objective.get("resolved_target")
    if isinstance(target, dict) and isinstance(target.get("source"), dict):
        try:
            return EvidenceSource.model_validate(target["source"])
        except ValueError:
            return None
    if selection is None:
        return None
    for item in _selection_evidence(selection):
        if item.signal_type is EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED:
            return item.source
    return None


def _brief_qualifications(
    db: Session,
    research_request: ResearchRequest,
) -> list[BriefQualification]:
    qualifications = list_opportunity_qualifications_for_user(
        db,
        research_request.id,
        research_request.user_id,
        include_not_eligible=True,
    )
    if not qualifications:
        raise ProspectEvidenceBriefContextError("Run opportunity qualification before building a Prospect Evidence Brief.")
    return [
        BriefQualification(
            opportunity_model_id=item.opportunity_model_id,
            state=item.state,
            reason=item.reason,
            supporting_evidence_keys=item.supporting_evidence_keys,
            evaluated_at=item.evaluated_at,
        )
        for item in qualifications
    ]


def _brief_sources(db: Session, research_request: ResearchRequest) -> list[BriefSource]:
    sources = list_research_sources_for_user(
        db,
        research_request.id,
        research_request.user_id,
        limit=MAX_BRIEF_SOURCES,
        admission_state=SourceAdmissionState.ACCEPTED,
    )
    return [
        BriefSource(
            key=f"research_source:{item.id}",
            provider=item.source_type,
            source_url=item.url,
            retrieved_at=item.retrieved_at,
            title=item.title,
            excerpt=item.excerpt,
        )
        for item in sources
    ]


def _brief_contacts(
    db: Session,
    research_request: ResearchRequest,
    selection: CampaignCandidateSelection | None,
    official_website: str | None,
    evidence: list[BriefEvidence],
    sources: list[BriefSource],
) -> list[BriefContactPath]:
    contacts = []
    evidence_keys = {item.key for item in evidence}
    contact_type_by_signal = {
        EvidenceSignalType.PUBLIC_EMAIL_OBSERVED: ContactPathType.EMAIL,
        EvidenceSignalType.PUBLIC_PHONE_OBSERVED: ContactPathType.PHONE,
        EvidenceSignalType.PUBLIC_WHATSAPP_OBSERVED: ContactPathType.WHATSAPP,
        EvidenceSignalType.WEBSITE_CONTACT_FORM_OBSERVED: ContactPathType.CONTACT_FORM,
    }
    contacts.extend(
        BriefContactPath(
            contact_type=contact_type_by_signal[item.signal_type],
            value=item.supporting_value,
            state=ContactEvidenceState.VERIFIED,
            source_keys=[item.key],
        )
        for item in evidence
        if item.signal_type in contact_type_by_signal
    )
    if official_website and "resolved_target:official_website" in evidence_keys:
        contacts.append(
            BriefContactPath(
                contact_type=ContactPathType.WEBSITE,
                value=official_website,
                state=ContactEvidenceState.VERIFIED,
                source_keys=["resolved_target:official_website"],
            )
        )
    if selection is not None:
        phone = selection.candidate_snapshot.get("phone_number")
        identity_source_key = next(
            (
                item.key
                for item in evidence
                if item.signal_type is EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED
                and item.key.startswith("selection_evidence:")
            ),
            None,
        )
        if isinstance(phone, str) and phone.strip():
            if identity_source_key:
                contacts.append(
                    BriefContactPath(
                        contact_type=ContactPathType.PHONE,
                        value=phone.strip(),
                        state=ContactEvidenceState.OBSERVED,
                        source_keys=[identity_source_key],
                    )
                )
    for observation in list_social_observations_for_user(
        db,
        research_request.id,
        research_request.user_id,
    ):
        if observation.state != "observed":
            continue
        matching_evidence_keys = [
            item.key
            for item in evidence
            if item.signal_type is EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED
            and str(item.source.source_url).rstrip("/").casefold()
            == observation.profile_url.rstrip("/").casefold()
        ]
        if matching_evidence_keys:
            contact_type = _social_contact_type(observation.profile_url)
            contacts.append(
                BriefContactPath(
                    contact_type=contact_type or ContactPathType.SOCIAL_PROFILE,
                    value=observation.profile_url,
                    state=ContactEvidenceState.VERIFIED,
                    source_keys=matching_evidence_keys,
                )
            )
            contacts.extend(
                BriefContactPath(
                    contact_type=ContactPathType.EMAIL,
                    value=email,
                    state=ContactEvidenceState.VERIFIED,
                    source_keys=matching_evidence_keys,
                )
                for email in (observation.public_emails or [])
            )
            contacts.extend(
                BriefContactPath(
                    contact_type=ContactPathType.PHONE,
                    value=phone,
                    state=ContactEvidenceState.VERIFIED,
                    source_keys=matching_evidence_keys,
                )
                for phone in (observation.public_phones or [])
            )
    for source in sources:
        source_text = " ".join(value for value in (source.title, source.excerpt) if value)
        for email in EMAIL_PATTERN.findall(source_text):
            contacts.append(
                BriefContactPath(
                    contact_type=ContactPathType.EMAIL,
                    value=email,
                    state=ContactEvidenceState.OBSERVED,
                    source_keys=[source.key],
                )
            )
        social_type = _social_contact_type(str(source.source_url))
        if social_type is not None:
            contacts.append(
                BriefContactPath(
                    contact_type=social_type,
                    value=str(source.source_url).rstrip("/"),
                    state=ContactEvidenceState.OBSERVED,
                    source_keys=[source.key],
                )
            )
    return _unique_contacts(contacts)


def _social_contact_type(value: str) -> ContactPathType | None:
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    contact_type = SOCIAL_CONTACT_TYPES.get(host)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if contact_type in {ContactPathType.FACEBOOK, ContactPathType.INSTAGRAM}:
        return contact_type if len(segments) == 1 else None
    if contact_type is ContactPathType.LINKEDIN:
        return contact_type if len(segments) == 2 and segments[0] in {"company", "in"} else None
    return None


def _unique_contacts(contacts: list[BriefContactPath]) -> list[BriefContactPath]:
    unique = {}
    for contact in contacts:
        key = (contact.contact_type, contact.value.strip().rstrip("/").casefold())
        existing = unique.get(key)
        if existing is None or (
            existing.state is ContactEvidenceState.OBSERVED
            and contact.state is ContactEvidenceState.VERIFIED
        ):
            unique[key] = contact
    return list(unique.values())[:10]


def _first_url(values: object) -> str | None:
    if not isinstance(values, list):
        return None
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None
