from dataclasses import dataclass

from app.schemas.opportunity_models import (
    EvidenceSignalType,
    IndustryOverlayId,
    OpportunityModelId,
    ServiceFamily,
)


@dataclass(frozen=True)
class OpportunityModel:
    id: OpportunityModelId
    display_name: str
    service_family: ServiceFamily
    applicable_industries: tuple[IndustryOverlayId, ...]
    required_signal_types: tuple[EvidenceSignalType, ...]


INDUSTRY_OVERLAYS = {
    IndustryOverlayId.BEAUTY_WELLNESS: {
        "display_name": "Beauty & wellness",
        "expected_conversion_paths": ("appointment", "contact"),
    },
    IndustryOverlayId.RESTAURANTS_CAFES: {
        "display_name": "Restaurants & cafes",
        "expected_conversion_paths": ("menu", "reservation", "ordering", "contact"),
    },
    IndustryOverlayId.FITNESS_GYMS: {
        "display_name": "Fitness & gyms",
        "expected_conversion_paths": ("trial", "membership_inquiry", "contact"),
    },
    IndustryOverlayId.BOUTIQUES_RETAIL: {
        "display_name": "Boutiques & retail",
        "expected_conversion_paths": ("store", "product_inquiry", "contact"),
    },
    IndustryOverlayId.DENTAL_SELECTED_CLINICS: {
        "display_name": "Dental & selected clinics",
        "expected_conversion_paths": ("appointment", "contact"),
    },
}


OPPORTUNITY_MODELS: dict[OpportunityModelId, OpportunityModel] = {
    "web_conversion.no_verified_web_presence": OpportunityModel(
        id="web_conversion.no_verified_web_presence",
        display_name="No verified web presence",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(
            IndustryOverlayId.BEAUTY_WELLNESS,
            IndustryOverlayId.RESTAURANTS_CAFES,
            IndustryOverlayId.FITNESS_GYMS,
            IndustryOverlayId.BOUTIQUES_RETAIL,
            IndustryOverlayId.DENTAL_SELECTED_CLINICS,
        ),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.NO_VERIFIED_OFFICIAL_WEB_PRESENCE,
        ),
    ),
    "web_conversion.mobile_performance": OpportunityModel(
        id="web_conversion.mobile_performance",
        display_name="Measured mobile performance",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(
            IndustryOverlayId.BEAUTY_WELLNESS,
            IndustryOverlayId.RESTAURANTS_CAFES,
            IndustryOverlayId.FITNESS_GYMS,
            IndustryOverlayId.BOUTIQUES_RETAIL,
            IndustryOverlayId.DENTAL_SELECTED_CLINICS,
        ),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            EvidenceSignalType.WEBSITE_MOBILE_PERFORMANCE_MEASURED,
        ),
    ),
    "web_conversion.booking_contact_path": OpportunityModel(
        id="web_conversion.booking_contact_path",
        display_name="Appointment or inquiry path",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(
            IndustryOverlayId.BEAUTY_WELLNESS,
            IndustryOverlayId.FITNESS_GYMS,
            IndustryOverlayId.DENTAL_SELECTED_CLINICS,
        ),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            EvidenceSignalType.WEBSITE_BOOKING_PATH_MANUAL_ONLY,
        ),
    ),
    "web_conversion.restaurant_reservation_path": OpportunityModel(
        id="web_conversion.restaurant_reservation_path",
        display_name="Restaurant reservation path",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(IndustryOverlayId.RESTAURANTS_CAFES,),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            EvidenceSignalType.WEBSITE_RESERVATION_PATH_MANUAL_ONLY,
        ),
    ),
    "web_conversion.restaurant_customer_path": OpportunityModel(
        id="web_conversion.restaurant_customer_path",
        display_name="Restaurant customer path",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(IndustryOverlayId.RESTAURANTS_CAFES,),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            EvidenceSignalType.WEBSITE_RESTAURANT_PRIMARY_PATH_NOT_OBSERVED,
        ),
    ),
    "web_conversion.fitness_membership_path": OpportunityModel(
        id="web_conversion.fitness_membership_path",
        display_name="Fitness membership path",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(IndustryOverlayId.FITNESS_GYMS,),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            EvidenceSignalType.WEBSITE_FITNESS_ENQUIRY_PATH_NOT_OBSERVED,
        ),
    ),
    "web_conversion.retail_product_path": OpportunityModel(
        id="web_conversion.retail_product_path",
        display_name="Retail product path",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(IndustryOverlayId.BOUTIQUES_RETAIL,),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            EvidenceSignalType.WEBSITE_RETAIL_PRODUCT_PATH_NOT_OBSERVED,
        ),
    ),
    "web_conversion.clinic_patient_path": OpportunityModel(
        id="web_conversion.clinic_patient_path",
        display_name="Clinic patient path",
        service_family=ServiceFamily.WEB_CONVERSION,
        applicable_industries=(IndustryOverlayId.DENTAL_SELECTED_CLINICS,),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_WEBSITE_CONFIRMED,
            EvidenceSignalType.WEBSITE_CLINIC_PATIENT_PATH_INCOMPLETE,
        ),
    ),
    "social_presence.dormant_official_presence": OpportunityModel(
        id="social_presence.dormant_official_presence",
        display_name="Measured official social dormancy",
        service_family=ServiceFamily.SOCIAL_PRESENCE_CONTENT,
        applicable_industries=(
            IndustryOverlayId.BEAUTY_WELLNESS,
            IndustryOverlayId.RESTAURANTS_CAFES,
            IndustryOverlayId.FITNESS_GYMS,
            IndustryOverlayId.BOUTIQUES_RETAIL,
        ),
        required_signal_types=(
            EvidenceSignalType.BUSINESS_IDENTITY_CONFIRMED,
            EvidenceSignalType.OFFICIAL_SOCIAL_PROFILE_CONFIRMED,
            EvidenceSignalType.BUSINESS_ACTIVITY_CONFIRMED,
            EvidenceSignalType.SOCIAL_HISTORIC_ACTIVITY_CONFIRMED,
            EvidenceSignalType.SOCIAL_DORMANCY_MEASURED,
        ),
    ),
}


def get_opportunity_model(model_id: OpportunityModelId) -> OpportunityModel:
    return OPPORTUNITY_MODELS[model_id]
