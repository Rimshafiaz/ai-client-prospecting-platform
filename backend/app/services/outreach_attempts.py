from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.gmail_oauth import (
    GMAIL_METADATA_SCOPE,
    GmailOAuthProviderError,
    GmailSendRejectedError,
    GmailSendUncertainError,
)
from app.models.campaign import Campaign
from app.models.campaign_candidate_selection import CampaignCandidateSelection
from app.models.campaign_prospect import (
    CampaignProspect,
    CampaignProspectNextAction,
    CampaignProspectState,
)
from app.models.campaign_run import CampaignRun
from app.models.gmail_connection import GmailConnection, GmailConnectionStatus
from app.models.outreach_attempt import (
    OutreachAttempt,
    OutreachChannel,
    OutreachOutcome,
    OutreachSendMethod,
    OutreachStatus,
)
from app.models.research_report import ReportKind, ResearchReport
from app.models.research_request import ResearchRequest
from app.models.user import User
from app.schemas.outreach_attempt import (
    OutreachAttemptCreate,
    OutreachAttemptResponse,
    OutreachDraftUpdate,
    OutreachDraftOptionResponse,
    OutreachOutcomeUpdate,
)
from app.schemas.prospect_evidence_brief import (
    BriefContactPath,
    ContactPathType,
    ProspectEvidenceBrief,
)
from app.services.aggregate_verdict import AggregateVerdict
from app.services.gmail_connections import configured_gmail_dependencies
from app.services.gmail_token_vault import GmailTokenVaultError, decrypt_refresh_token


class OutreachAttemptError(ValueError):
    pass


def create_outreach_attempt(
    db: Session,
    campaign_id: UUID,
    prospect_id: UUID,
    current_user: User,
    request: OutreachAttemptCreate,
) -> OutreachAttempt:
    prospect = _prospect_for_user(db, campaign_id, prospect_id, current_user.id)
    if prospect is None:
        raise OutreachAttemptError("Campaign prospect not found.")
    report = db.scalar(
        select(ResearchReport).where(
            ResearchReport.id == request.research_report_id,
            ResearchReport.user_id == current_user.id,
        )
    )
    if report is None or report.report_kind is not ReportKind.PROSPECT_EVIDENCE_BRIEF:
        raise OutreachAttemptError("A Prospect Evidence Brief is required for outreach.")
    _require_report_matches_prospect(db, report, prospect)
    try:
        brief = ProspectEvidenceBrief.model_validate(report.report_data)
    except ValueError as error:
        raise OutreachAttemptError("The saved Prospect Evidence Brief is invalid.") from error
    if brief.aggregate_verdict is not AggregateVerdict.QUALIFIED:
        raise OutreachAttemptError(
            "Outreach requires a qualified prospect; this research ended "
            f"with: {brief.aggregate_verdict.value.replace('_', ' ')}."
        )
    draft = next((item for item in brief.outreach_drafts if item.channel.value == request.channel.value), None)
    if draft is None:
        raise OutreachAttemptError("The brief has no grounded draft for this channel.")
    contact = _matching_contact(brief, request.channel, request.recipient)
    if contact is None:
        raise OutreachAttemptError("The recipient is not a source-backed contact in this brief.")
    existing = db.scalar(
        select(OutreachAttempt).where(
            OutreachAttempt.campaign_prospect_id == prospect.id,
            OutreachAttempt.research_report_id == report.id,
            OutreachAttempt.channel == request.channel,
            OutreachAttempt.recipient == contact.value,
            OutreachAttempt.status.in_(
                [OutreachStatus.DRAFT, OutreachStatus.APPROVED, OutreachStatus.SENDING]
            ),
        )
    )
    if existing is not None:
        raise OutreachAttemptError("An active outreach draft already exists for this contact.")
    attempt = OutreachAttempt(
        campaign_prospect_id=prospect.id,
        research_report_id=report.id,
        user_id=current_user.id,
        channel=request.channel,
        send_method=(
            OutreachSendMethod.GMAIL
            if request.channel is OutreachChannel.EMAIL
            else OutreachSendMethod.MANUAL
        ),
        recipient=contact.value,
        subject=draft.subject,
        body=draft.message,
        offering=draft.offering,
        grounding_evidence_keys=list(
            dict.fromkeys(
                evidence_key
                for grounding in draft.grounding
                for evidence_key in grounding.evidence_keys
            )
        ),
        contact_source_keys=contact.source_keys,
        status=OutreachStatus.DRAFT,
    )
    prospect.workflow_state = CampaignProspectState.READY_FOR_OUTREACH
    prospect.next_action = CampaignProspectNextAction.PREPARE_OUTREACH
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise OutreachAttemptError(
            "An active outreach draft already exists for this contact."
        ) from error
    db.refresh(attempt)
    return attempt


def list_outreach_attempts(
    db: Session,
    campaign_id: UUID,
    prospect_id: UUID,
    current_user: User,
) -> list[OutreachAttempt]:
    if _prospect_for_user(db, campaign_id, prospect_id, current_user.id) is None:
        raise OutreachAttemptError("Campaign prospect not found.")
    statement = (
        select(OutreachAttempt)
        .where(
            OutreachAttempt.campaign_prospect_id == prospect_id,
            OutreachAttempt.user_id == current_user.id,
        )
        .order_by(OutreachAttempt.created_at.desc())
    )
    return list(db.scalars(statement).all())


def list_outreach_draft_options(
    db: Session,
    campaign_id: UUID,
    prospect_id: UUID,
    current_user: User,
) -> list[OutreachDraftOptionResponse]:
    prospect = _prospect_for_user(db, campaign_id, prospect_id, current_user.id)
    if prospect is None:
        raise OutreachAttemptError("Campaign prospect not found.")
    reports = db.scalars(
        select(ResearchReport)
        .join(ResearchRequest, ResearchReport.research_request_id == ResearchRequest.id)
        .join(
            CampaignCandidateSelection,
            ResearchRequest.campaign_candidate_selection_id == CampaignCandidateSelection.id,
        )
        .join(CampaignRun, CampaignCandidateSelection.campaign_run_id == CampaignRun.id)
        .where(
            ResearchReport.user_id == current_user.id,
            ResearchReport.report_kind == ReportKind.PROSPECT_EVIDENCE_BRIEF,
            CampaignCandidateSelection.source_identity_key == prospect.source_identity_key,
            CampaignRun.campaign_id == prospect.campaign_id,
        )
        .order_by(ResearchReport.generated_at.desc())
    ).all()
    active_attempts = db.scalars(
        select(OutreachAttempt).where(
            OutreachAttempt.campaign_prospect_id == prospect.id,
            OutreachAttempt.user_id == current_user.id,
            OutreachAttempt.status.in_(
                [OutreachStatus.DRAFT, OutreachStatus.APPROVED, OutreachStatus.SENDING]
            ),
        )
    ).all()
    active_keys = {
        (attempt.research_report_id, attempt.channel, _recipient_key(attempt.channel, attempt.recipient))
        for attempt in active_attempts
    }
    for report in reports:
        try:
            brief = ProspectEvidenceBrief.model_validate(report.report_data)
        except ValueError:
            continue
        if brief.aggregate_verdict is not AggregateVerdict.QUALIFIED:
            continue
        options = []
        for draft in brief.outreach_drafts:
            channel = OutreachChannel(draft.channel.value)
            for contact in _contacts_for_channel(brief, channel):
                if (report.id, channel, _recipient_key(channel, contact.value)) in active_keys:
                    continue
                options.append(
                    OutreachDraftOptionResponse(
                        research_report_id=report.id,
                        channel=channel,
                        recipient=contact.value,
                        subject=draft.subject,
                        body=draft.message,
                    )
                )
        return options
    return []


def update_outreach_draft(
    db: Session,
    attempt_id: UUID,
    current_user: User,
    request: OutreachDraftUpdate,
) -> OutreachAttempt:
    attempt = _attempt_for_user(db, attempt_id, current_user.id)
    if attempt is None:
        raise OutreachAttemptError("Outreach attempt not found.")
    if attempt.status not in {OutreachStatus.DRAFT, OutreachStatus.APPROVED, OutreachStatus.FAILED}:
        raise OutreachAttemptError("Sent, replied, or closed outreach cannot be edited.")
    if attempt.channel is OutreachChannel.EMAIL and request.subject is None:
        raise OutreachAttemptError("Email outreach requires a subject.")
    if attempt.channel is not OutreachChannel.EMAIL and request.subject is not None:
        raise OutreachAttemptError("Only email outreach may have a subject.")
    attempt.subject = request.subject
    attempt.body = request.body
    attempt.edited_by_user = True
    attempt.status = OutreachStatus.DRAFT
    attempt.approved_at = None
    attempt.failure_reason = None
    db.commit()
    db.refresh(attempt)
    return attempt


def approve_outreach_attempt(
    db: Session,
    attempt_id: UUID,
    current_user: User,
) -> OutreachAttempt:
    attempt = _attempt_for_user(db, attempt_id, current_user.id)
    if attempt is None:
        raise OutreachAttemptError("Outreach attempt not found.")
    if attempt.status is not OutreachStatus.DRAFT:
        raise OutreachAttemptError("Only a draft outreach attempt can be approved.")
    attempt.status = OutreachStatus.APPROVED
    attempt.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(attempt)
    return attempt


def send_approved_email(
    db: Session,
    attempt_id: UUID,
    current_user: User,
) -> OutreachAttempt:
    attempt = db.scalar(
        select(OutreachAttempt)
        .where(
            OutreachAttempt.id == attempt_id,
            OutreachAttempt.user_id == current_user.id,
        )
        .with_for_update()
    )
    if attempt is None:
        raise OutreachAttemptError("Outreach attempt not found.")
    if attempt.channel is not OutreachChannel.EMAIL or attempt.send_method is not OutreachSendMethod.GMAIL:
        raise OutreachAttemptError("Only Gmail email attempts can be sent through this endpoint.")
    if attempt.status is not OutreachStatus.APPROVED:
        raise OutreachAttemptError("Only an approved email can be sent.")
    if not attempt.subject or not attempt.body or not attempt.recipient:
        raise OutreachAttemptError("The approved email is incomplete.")

    connection = db.scalar(
        select(GmailConnection)
        .where(
            GmailConnection.user_id == current_user.id,
            GmailConnection.status == GmailConnectionStatus.CONNECTED,
        )
        .with_for_update()
    )
    if connection is None or not connection.encrypted_refresh_token:
        raise OutreachAttemptError("Connect Gmail before sending this email.")
    sent_since = datetime.now(UTC) - timedelta(days=1)
    sent_count = db.scalar(
        select(func.count(OutreachAttempt.id)).where(
            OutreachAttempt.user_id == current_user.id,
            OutreachAttempt.channel == OutreachChannel.EMAIL,
            or_(
                OutreachAttempt.sent_at >= sent_since,
                (
                    (OutreachAttempt.status == OutreachStatus.SENDING)
                    & (OutreachAttempt.updated_at >= sent_since)
                ),
            ),
        )
    )
    if int(sent_count or 0) >= settings.gmail_send_limit_per_day:
        raise OutreachAttemptError("The OpportunityCue Gmail daily send limit has been reached.")

    try:
        client, encryption_key = configured_gmail_dependencies()
        refresh_token = decrypt_refresh_token(connection.encrypted_refresh_token, encryption_key)
    except (GmailTokenVaultError, ValueError) as error:
        raise OutreachAttemptError("The Gmail connection could not be used securely.") from error

    attempt.status = OutreachStatus.SENDING
    attempt.failure_reason = None
    db.commit()

    try:
        access_token = client.refresh_access_token(refresh_token)
        message_id, thread_id = client.send_email(
            access_token,
            connection.email,
            attempt.recipient,
            attempt.subject,
            attempt.body,
        )
    except (GmailOAuthProviderError, GmailSendRejectedError) as error:
        attempt.status = OutreachStatus.FAILED
        attempt.failure_reason = str(error)
        db.commit()
        db.refresh(attempt)
        return attempt
    except GmailSendUncertainError as error:
        attempt.failure_reason = str(error)
        db.commit()
        db.refresh(attempt)
        return attempt

    now = datetime.now(UTC)
    attempt.status = OutreachStatus.SENT
    attempt.provider_message_id = message_id
    attempt.provider_thread_id = thread_id
    attempt.sent_at = now
    attempt.failure_reason = None
    prospect = db.get(CampaignProspect, attempt.campaign_prospect_id)
    if prospect is not None:
        prospect.workflow_state = CampaignProspectState.CONTACTED
        prospect.next_action = CampaignProspectNextAction.NO_ACTION
    db.commit()
    db.refresh(attempt)
    return attempt


def check_gmail_reply(
    db: Session,
    attempt_id: UUID,
    current_user: User,
) -> OutreachAttempt:
    attempt = _attempt_for_user(db, attempt_id, current_user.id)
    if attempt is None:
        raise OutreachAttemptError("Outreach attempt not found.")
    if attempt.channel is not OutreachChannel.EMAIL or attempt.send_method is not OutreachSendMethod.GMAIL:
        raise OutreachAttemptError("Only Gmail email attempts support reply checking.")
    if attempt.status is OutreachStatus.REPLIED:
        return attempt
    if attempt.status is not OutreachStatus.SENT or not attempt.provider_message_id or not attempt.provider_thread_id:
        raise OutreachAttemptError("Only a confirmed sent Gmail email can be checked for replies.")

    connection = db.scalar(
        select(GmailConnection).where(
            GmailConnection.user_id == current_user.id,
            GmailConnection.status == GmailConnectionStatus.CONNECTED,
        )
    )
    if connection is None or not connection.encrypted_refresh_token:
        raise OutreachAttemptError("Connect Gmail before checking for replies.")
    if GMAIL_METADATA_SCOPE not in connection.granted_scopes:
        raise OutreachAttemptError("Reconnect Gmail to enable reply tracking.")

    try:
        client, encryption_key = configured_gmail_dependencies()
        refresh_token = decrypt_refresh_token(connection.encrypted_refresh_token, encryption_key)
        access_token = client.refresh_access_token(refresh_token)
        thread = client.thread_metadata(access_token, attempt.provider_thread_id)
    except (GmailTokenVaultError, GmailOAuthProviderError, ValueError) as error:
        raise OutreachAttemptError("The Gmail reply check could not be completed.") from error

    reply = _first_incoming_message_after(thread, attempt.provider_message_id)
    if reply is None:
        return attempt
    attempt.status = OutreachStatus.REPLIED
    attempt.provider_reply_message_id = reply["id"]
    attempt.replied_at = datetime.fromtimestamp(reply["internal_date"] / 1000, UTC)
    db.commit()
    db.refresh(attempt)
    return attempt


def record_manual_send(
    db: Session,
    attempt_id: UUID,
    current_user: User,
) -> OutreachAttempt:
    attempt = _attempt_for_user(db, attempt_id, current_user.id)
    if attempt is None:
        raise OutreachAttemptError("Outreach attempt not found.")
    if attempt.send_method is not OutreachSendMethod.MANUAL:
        raise OutreachAttemptError("Email sent state must come from the Gmail provider.")
    if attempt.status is not OutreachStatus.APPROVED:
        raise OutreachAttemptError("Approve the message before recording it as sent.")
    attempt.status = OutreachStatus.SENT
    attempt.sent_at = datetime.now(UTC)
    db.commit()
    db.refresh(attempt)
    return attempt


record_manual_linkedin_send = record_manual_send


def record_manual_outcome(
    db: Session,
    attempt_id: UUID,
    current_user: User,
    request: OutreachOutcomeUpdate,
) -> OutreachAttempt:
    attempt = _attempt_for_user(db, attempt_id, current_user.id)
    if attempt is None:
        raise OutreachAttemptError("Outreach attempt not found.")
    if attempt.send_method is not OutreachSendMethod.MANUAL:
        raise OutreachAttemptError("Gmail replies and delivery outcomes must come from Gmail.")
    if attempt.status not in {OutreachStatus.SENT, OutreachStatus.REPLIED}:
        raise OutreachAttemptError("Only sent outreach may receive an outcome.")
    if request.outcome is OutreachOutcome.BOUNCED:
        raise OutreachAttemptError("Manual outreach cannot be marked as bounced.")
    if request.replied and request.outcome is OutreachOutcome.NO_RESPONSE:
        raise OutreachAttemptError("A replied attempt cannot have a no-response outcome.")
    if not request.replied and request.outcome in {
        OutreachOutcome.INTERESTED,
        OutreachOutcome.NOT_INTERESTED,
    }:
        raise OutreachAttemptError("Interested outcomes require a recorded reply.")
    now = datetime.now(UTC)
    attempt.outcome = request.outcome
    attempt.outcome_recorded_at = now
    if request.replied:
        attempt.status = OutreachStatus.REPLIED
        attempt.replied_at = attempt.replied_at or now
    elif request.outcome is OutreachOutcome.NO_RESPONSE:
        attempt.status = OutreachStatus.CLOSED
    db.commit()
    db.refresh(attempt)
    return attempt


def outreach_attempt_response(attempt: OutreachAttempt) -> OutreachAttemptResponse:
    return OutreachAttemptResponse.model_validate(attempt)


def _prospect_for_user(
    db: Session,
    campaign_id: UUID,
    prospect_id: UUID,
    user_id: UUID,
) -> CampaignProspect | None:
    return db.scalar(
        select(CampaignProspect)
        .join(Campaign)
        .where(
            CampaignProspect.id == prospect_id,
            CampaignProspect.campaign_id == campaign_id,
            Campaign.user_id == user_id,
        )
    )


def _attempt_for_user(db: Session, attempt_id: UUID, user_id: UUID) -> OutreachAttempt | None:
    return db.scalar(
        select(OutreachAttempt).where(
            OutreachAttempt.id == attempt_id,
            OutreachAttempt.user_id == user_id,
        )
    )


def _require_report_matches_prospect(
    db: Session,
    report: ResearchReport,
    prospect: CampaignProspect,
) -> None:
    research_request = db.get(ResearchRequest, report.research_request_id)
    selection = (
        db.get(CampaignCandidateSelection, research_request.campaign_candidate_selection_id)
        if research_request is not None and research_request.campaign_candidate_selection_id is not None
        else None
    )
    campaign_run = db.get(CampaignRun, selection.campaign_run_id) if selection is not None else None
    if (
        selection is None
        or campaign_run is None
        or selection.source_identity_key != prospect.source_identity_key
        or campaign_run.campaign_id != prospect.campaign_id
    ):
        raise OutreachAttemptError("The evidence brief does not belong to this campaign prospect.")


def _matching_contact(
    brief: ProspectEvidenceBrief,
    channel: OutreachChannel,
    recipient: str,
) -> BriefContactPath | None:
    normalized_recipient = _recipient_key(channel, recipient)
    for contact in _contacts_for_channel(brief, channel):
        if _recipient_key(channel, contact.value) == normalized_recipient:
            return contact
    return None


def _recipient_key(channel: OutreachChannel, recipient: str) -> str:
    value = recipient.strip().rstrip("/")
    return value.casefold() if channel is OutreachChannel.EMAIL else value


def _contacts_for_channel(
    brief: ProspectEvidenceBrief,
    channel: OutreachChannel,
) -> list[BriefContactPath]:
    if channel is OutreachChannel.EMAIL:
        return [
            contact
            for contact in brief.contacts
            if contact.contact_type is ContactPathType.EMAIL
        ]
    contact_type_by_channel = {
        OutreachChannel.LINKEDIN: ContactPathType.LINKEDIN,
        OutreachChannel.INSTAGRAM: ContactPathType.INSTAGRAM,
        OutreachChannel.FACEBOOK: ContactPathType.FACEBOOK,
        OutreachChannel.WHATSAPP: ContactPathType.WHATSAPP,
        OutreachChannel.PHONE: ContactPathType.PHONE,
        OutreachChannel.CONTACT_FORM: ContactPathType.CONTACT_FORM,
    }
    expected_type = contact_type_by_channel[channel]
    contacts = [contact for contact in brief.contacts if contact.contact_type is expected_type]
    if channel is OutreachChannel.LINKEDIN:
        contacts.extend(
            contact
            for contact in brief.contacts
            if contact.contact_type is ContactPathType.SOCIAL_PROFILE
            and (urlparse(contact.value).hostname or "").casefold().removeprefix("www.")
            in {"linkedin.com", "linkedin.cn"}
        )
    return contacts


def _first_incoming_message_after(thread: dict, original_message_id: str) -> dict | None:
    messages = [message for message in thread["messages"] if isinstance(message, dict)]
    original = next((message for message in messages if message.get("id") == original_message_id), None)
    if original is None:
        raise OutreachAttemptError("The original sent message was not found in its Gmail thread.")
    try:
        original_date = int(original["internalDate"])
    except (KeyError, TypeError, ValueError) as error:
        raise OutreachAttemptError("Gmail returned incomplete metadata for the sent message.") from error

    incoming = []
    for message in messages:
        try:
            internal_date = int(message["internalDate"])
        except (KeyError, TypeError, ValueError):
            continue
        labels = set(message.get("labelIds") or [])
        if (
            isinstance(message.get("id"), str)
            and internal_date > original_date
            and "SENT" not in labels
            and "DRAFT" not in labels
        ):
            incoming.append({"id": message["id"], "internal_date": internal_date})
    return min(incoming, key=lambda message: message["internal_date"], default=None)
