from datetime import datetime
from enum import Enum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ServiceFamily(str, Enum):
    WEB_CONVERSION = "web_conversion"
    SOCIAL_PRESENCE_CONTENT = "social_presence_content"


class IndustryOverlayId(str, Enum):
    BEAUTY_WELLNESS = "beauty_wellness"
    RESTAURANTS_CAFES = "restaurants_cafes"
    FITNESS_GYMS = "fitness_gyms"
    BOUTIQUES_RETAIL = "boutiques_retail"
    DENTAL_SELECTED_CLINICS = "dental_selected_clinics"


OpportunityModelId = Literal[
    "web_conversion.no_verified_web_presence",
    "web_conversion.mobile_performance",
    "web_conversion.booking_contact_path",
    "web_conversion.restaurant_reservation_path",
    "web_conversion.restaurant_customer_path",
    "web_conversion.fitness_membership_path",
    "web_conversion.retail_product_path",
    "web_conversion.clinic_patient_path",
    "social_presence.dormant_official_presence",
]


class IdentityState(str, Enum):
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class EvidenceType(str, Enum):
    OBSERVED = "observed"
    INFERENCE = "inference"


class EvidenceSignalType(str, Enum):
    BUSINESS_IDENTITY_CONFIRMED = "business_identity_confirmed"
    OFFICIAL_WEBSITE_CONFIRMED = "official_website_confirmed"
    NO_LISTED_OFFICIAL_WEBSITE = "no_listed_official_website"
    NO_VERIFIED_OFFICIAL_WEB_PRESENCE = "no_verified_official_web_presence"
    WEBSITE_MOBILE_PERFORMANCE_MEASURED = "website_mobile_performance_measured"
    WEBSITE_BOOKING_PATH_MANUAL_ONLY = "website_booking_path_manual_only"
    WEBSITE_RESERVATION_PATH_MANUAL_ONLY = "website_reservation_path_manual_only"
    WEBSITE_RESTAURANT_PRIMARY_PATH_NOT_OBSERVED = "website_restaurant_primary_path_not_observed"
    WEBSITE_FITNESS_ENQUIRY_PATH_NOT_OBSERVED = "website_fitness_enquiry_path_not_observed"
    WEBSITE_RETAIL_PRODUCT_PATH_NOT_OBSERVED = "website_retail_product_path_not_observed"
    WEBSITE_CLINIC_PATIENT_PATH_INCOMPLETE = "website_clinic_patient_path_incomplete"
    OFFICIAL_SOCIAL_PROFILE_CONFIRMED = "official_social_profile_confirmed"
    BUSINESS_ACTIVITY_CONFIRMED = "business_activity_confirmed"
    SOCIAL_HISTORIC_ACTIVITY_CONFIRMED = "social_historic_activity_confirmed"
    SOCIAL_DORMANCY_MEASURED = "social_dormancy_measured"
    PUBLIC_EMAIL_OBSERVED = "public_email_observed"
    PUBLIC_PHONE_OBSERVED = "public_phone_observed"
    PUBLIC_WHATSAPP_OBSERVED = "public_whatsapp_observed"
    WEBSITE_CONTACT_FORM_OBSERVED = "website_contact_form_observed"



class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=2, max_length=100)
    provider_record_id: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: HttpUrl | None = None
    retrieved_at: datetime

    @model_validator(mode="after")
    def require_a_stable_source_reference(self) -> Self:
        if not self.provider_record_id and self.source_url is None:
            raise ValueError(
                "Evidence must include a provider record ID or a source URL."
            )
        return self


class EvidenceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_type: EvidenceSignalType
    evidence_type: EvidenceType
    supporting_value: str = Field(min_length=1, max_length=1_000)
    numeric_value: float | None = None
    source: EvidenceSource
    captured_at: datetime
    inference_basis: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def require_basis_for_inferences_only(self) -> Self:
        if self.evidence_type is EvidenceType.INFERENCE and not self.inference_basis:
            raise ValueError("An inference must include its evidence basis.")
        if self.evidence_type is not EvidenceType.INFERENCE and self.inference_basis:
            raise ValueError("Only an inference may include an inference basis.")
        return self


class OpportunityModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_ids: tuple[OpportunityModelId, ...] = Field(min_length=1, max_length=3)
    confirmed_by_user: bool = False

    @model_validator(mode="after")
    def require_unique_model_ids(self) -> Self:
        if len(self.model_ids) != len(set(self.model_ids)):
            raise ValueError("Each Opportunity Model may be selected only once.")
        return self
