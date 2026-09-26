from sqlalchemy.orm import Session

from app.models.campaign_candidate_selection import CampaignCandidateSelection
from app.models.company import Company
from app.models.research_request import ResearchRequest
from app.schemas.agent_outputs import (
    OpportunityOutreachOutput,
    SocialResearchOutput,
    WebsiteResearchOutput,
)
from app.schemas.opportunity_models import (
    EvidenceSignalType,
    OpportunityModelSelection,
    ServiceFamily,
)
from app.schemas.opportunity_outreach import OpportunityOutreachHandoff
from app.schemas.opportunity_qualification import OpportunityQualificationState
from app.schemas.prospect_evidence_brief import (
    ContactEvidenceState,
    ContactPathType,
    OutreachChannel,
)
from app.schemas.prospect_evidence_brief_context import TrustedProspectEvidenceBriefContext
from app.services.aggregate_verdict import AggregateVerdict, aggregate_verdict
from app.services.opportunity_model_catalog import get_opportunity_model
from app.services.prospect_evidence_brief import (
    build_prospect_evidence_brief_context,
)


class OpportunityOutreachError(ValueError):
    pass


CHANNEL_BY_CONTACT = {
    ContactPathType.EMAIL: OutreachChannel.EMAIL,
    ContactPathType.LINKEDIN: OutreachChannel.LINKEDIN,
    ContactPathType.INSTAGRAM: OutreachChannel.INSTAGRAM,
    ContactPathType.FACEBOOK: OutreachChannel.FACEBOOK,
    ContactPathType.WHATSAPP: OutreachChannel.WHATSAPP,
    ContactPathType.PHONE: OutreachChannel.PHONE,
    ContactPathType.CONTACT_FORM: OutreachChannel.CONTACT_FORM,
}
GENERIC_PERSONALIZATION_SIGNALS = {
    EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
    EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
    EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED,
}
SOCIAL_SIGNALS = {
    EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED,
    EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED,
    EvidenceSignalType.SOCIAL_DORMANCY_MEASURED,
}


def build_opportunity_outreach_handoff(
    db: Session,
    research_request: ResearchRequest,
    company: Company,
    selection: CampaignCandidateSelection | None,
    *,
    brief_context: TrustedProspectEvidenceBriefContext | None = None,
) -> OpportunityOutreachHandoff:
    if brief_context is not None:
        context = brief_context
    else:
        context = build_prospect_evidence_brief_context(
            db, research_request, company, selection
        )
    try:
        selected = OpportunityModelSelection.model_validate(
            research_request.opportunity_model_selection
        )
    except ValueError as error:
        raise OpportunityOutreachError(
            "A valid persisted Opportunity Model selection is required."
        ) from error
    selected_ids = set(selected.model_ids)
    qualifications = [
        item for item in context.qualifications if item.opportunity_model_id in selected_ids
    ]
    if {item.opportunity_model_id for item in qualifications} != selected_ids:
        raise OpportunityOutreachError(
            "Every selected Opportunity Model must have a qualification result."
        )
    aggregate = aggregate_verdict([item.state for item in qualifications])
    if aggregate is not AggregateVerdict.QUALIFIED:
        raise OpportunityOutreachError(
            "Opportunity and outreach generation requires a QUALIFIED aggregate verdict."
        )

    families = {
        get_opportunity_model(model_id).service_family for model_id in selected.model_ids
    }
    outputs = research_request.specialist_outputs or {}
    website = _required_specialist_output(
        outputs, "website", WebsiteResearchOutput, ServiceFamily.WEB_CONVERSION in families
    )
    social = _required_specialist_output(
        outputs,
        "social",
        SocialResearchOutput,
        ServiceFamily.SOCIAL_PRESENCE_CONTENT in families,
    )
    evidence_keys = {item.key for item in context.evidence}
    for specialist in (website, social):
        if specialist is not None and any(
            not set(finding.evidence_keys) <= evidence_keys
            for finding in specialist.findings
        ):
            raise OpportunityOutreachError(
                "Persisted specialist output references unavailable canonical evidence."
            )

    channels = sorted(
        {
            CHANNEL_BY_CONTACT[contact.contact_type]
            for contact in context.contacts
            if contact.state is ContactEvidenceState.VERIFIED
            and contact.contact_type in CHANNEL_BY_CONTACT
        },
        key=lambda item: item.value,
    )
    return OpportunityOutreachHandoff(
        objective=context.objective,
        prospect=context.prospect,
        aggregate_verdict=aggregate,
        qualifications=qualifications,
        website_research=website,
        social_research=social,
        evidence=context.evidence,
        available_verified_channels=channels,
    )


def validate_opportunity_outreach_output(
    output: OpportunityOutreachOutput | dict,
    handoff: OpportunityOutreachHandoff,
) -> OpportunityOutreachOutput:
    if handoff.aggregate_verdict is not AggregateVerdict.QUALIFIED:
        raise OpportunityOutreachError("Outreach output requires a QUALIFIED aggregate verdict.")
    validated = OpportunityOutreachOutput.model_validate(output)
    _reject_disallowed_copy(validated)
    evidence_by_key = {item.key: item for item in handoff.evidence}
    evidence_keys = set(evidence_by_key)
    referenced_groups = [
        validated.opportunity_summary.evidence_keys,
        validated.pitch_angle.evidence_keys,
        *(item.evidence_keys for item in validated.personalization_basis),
        *(
            grounding.evidence_keys
            for draft in validated.outreach_drafts
            for grounding in draft.grounding
        ),
    ]
    if any(not set(keys) <= evidence_keys for keys in referenced_groups):
        raise OpportunityOutreachError("Opportunity or outreach output cited unavailable evidence.")

    likely = [
        item
        for item in handoff.qualifications
        if item.state is OpportunityQualificationState.LIKELY
    ]
    likely_keys = {key for item in likely for key in item.supporting_evidence_keys}
    meaningful_likely_keys = {
        key
        for key in likely_keys
        if evidence_by_key[key].signal_type not in GENERIC_PERSONALIZATION_SIGNALS
    }
    likely_families = {
        get_opportunity_model(item.opportunity_model_id).service_family for item in likely
    }
    for name, keys in (
        ("Opportunity summary", validated.opportunity_summary.evidence_keys),
        ("Pitch angle", validated.pitch_angle.evidence_keys),
    ):
        if not set(keys) & meaningful_likely_keys:
            raise OpportunityOutreachError(
                f"{name} must cite prospect-specific evidence supporting a LIKELY selected model."
            )
        cited_families = {
            family
            for key in keys
            if (family := _signal_family(evidence_by_key[key].signal_type)) is not None
        }
        if not cited_families <= likely_families:
            raise OpportunityOutreachError(
                f"{name} cites evidence outside the qualified service family."
            )

    if validated.pitch_angle.offering != handoff.objective.offering:
        raise OpportunityOutreachError("Pitch angle must use the seller's stated offering.")
    if any(draft.offering != handoff.objective.offering for draft in validated.outreach_drafts):
        raise OpportunityOutreachError("Outreach must use the seller's stated offering.")

    statements = [item.statement.casefold() for item in validated.personalization_basis]
    evidence_sets = [frozenset(item.evidence_keys) for item in validated.personalization_basis]
    if len(statements) != len(set(statements)) or len(evidence_sets) != len(set(evidence_sets)):
        raise OpportunityOutreachError("Personalization basis contains duplicates.")
    if not any(set(item.evidence_keys) & meaningful_likely_keys for item in validated.personalization_basis):
        raise OpportunityOutreachError(
            "Personalization requires prospect-specific opportunity evidence, not identity alone."
        )

    channels = [draft.channel for draft in validated.outreach_drafts]
    if len(channels) != len(set(channels)):
        raise OpportunityOutreachError("Only one outreach draft is allowed per channel.")
    allowed_channels = set(handoff.available_verified_channels)
    if any(channel not in allowed_channels for channel in channels):
        raise OpportunityOutreachError(
            "Outreach draft channel is not backed by a verified contact path."
        )
    return validated


def _reject_disallowed_copy(output: OpportunityOutreachOutput) -> None:
    generated_text = [
        output.opportunity_summary.statement,
        output.pitch_angle.statement,
        *(item.statement for item in output.personalization_basis),
        *output.forbidden_claims,
        *output.caveats,
        *(draft.subject or "" for draft in output.outreach_drafts),
        *(draft.message for draft in output.outreach_drafts),
        *(
            grounding.claim
            for draft in output.outreach_drafts
            for grounding in draft.grounding
        ),
    ]
    if any("\N{EM DASH}" in value for value in generated_text):
        raise OpportunityOutreachError(
            "Generated report and outreach copy must not contain em dashes."
        )


def _required_specialist_output(outputs, namespace, model, required):
    value = outputs.get(namespace)
    if not required:
        return None
    if value is None:
        raise OpportunityOutreachError(
            f"Required {namespace} specialist output is unavailable."
        )
    try:
        return model.model_validate(value)
    except ValueError as error:
        raise OpportunityOutreachError(
            f"Required {namespace} specialist output is invalid."
        ) from error


def _signal_family(signal: EvidenceSignalType) -> ServiceFamily | None:
    if signal in SOCIAL_SIGNALS:
        return ServiceFamily.SOCIAL_PRESENCE_CONTENT
    if signal.value.startswith("website_") or signal in {
        EvidenceSignalType.NO_LISTED_OFFICIAL_WEBSITE,
        EvidenceSignalType.NO_VERIFIED_OFFICIAL_WEB_PRESENCE,
    }:
        return ServiceFamily.WEB_CONVERSION
    return None
