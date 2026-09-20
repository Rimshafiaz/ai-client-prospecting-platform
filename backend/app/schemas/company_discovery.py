from datetime import datetime
from typing import Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_serializer,
    field_validator,
    model_validator,
)

GoalType = Literal[
    "service_pitch",
    "client_prospecting",
    "investment",
    "hiring",
    "market_research",
    "other",
]
SupportedGoalType = Literal["service_pitch", "client_prospecting"]

ObjectiveChip = Literal["service_pitch", "client_prospecting", "investment", "hiring"]

SUPPORTED_GOAL_TYPES: tuple[str, ...] = ("service_pitch", "client_prospecting")

UNSUPPORTED_GOAL_MESSAGE = (
    "That goal type is not supported yet. OpportunityCue currently finds local "
    "businesses with measurable digital-growth opportunities: pitching a "
    "service or finding clients. Jobs, investment, and other discovery modes "
    "come later."
)


def _first_value(values: list[str]) -> str | None:
    return values[0] if values else None


class ParseDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=3, max_length=2_000)
    objective_hint: ObjectiveChip | None = None
    region: str | None = Field(default=None, max_length=100)
    company_size: str | None = Field(default=None, max_length=100)

    @field_validator("goal", "region", "company_size", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def require_goal(self) -> Self:
        if not self.goal:
            raise ValueError("A discovery goal is required.")
        return self


class DiscoveryObjective(BaseModel):
    goal_type: GoalType
    seller_role: str | None = Field(default=None, max_length=60)
    offering: str | None = Field(default=None, max_length=300)
    target_sectors: list[str] = Field(default_factory=list, max_length=6)
    target_geographies: list[str] = Field(default_factory=list, max_length=4)
    company_size: str | None = Field(default=None, max_length=100)
    stage: str | None = Field(default=None, max_length=60)
    triggers: list[str] = Field(default_factory=list, max_length=8)
    signals_to_look_for: list[str] = Field(default_factory=list, max_length=8)
    decision_makers: list[str] = Field(default_factory=list, max_length=6)
    search_queries: list[str] = Field(min_length=2, max_length=5)
    fit_rubric: str = Field(min_length=3, max_length=1_000)
    desired_outcome: str = Field(min_length=3, max_length=300)

    @field_validator(
        "seller_role",
        "offering",
        "company_size",
        "stage",
        "fit_rubric",
        "desired_outcome",
        mode="before",
    )
    @classmethod
    def normalize_scalar_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator(
        "target_sectors",
        "target_geographies",
        "triggers",
        "signals_to_look_for",
        "decision_makers",
        "search_queries",
        mode="before",
    )
    @classmethod
    def normalize_list_text(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ]
        return value

    @field_validator("search_queries", mode="after")
    @classmethod
    def clamp_query_lengths(cls, value: list[str]) -> list[str]:
        return [query[:200] for query in value]


class ParseDiscoveryResponse(BaseModel):
    objective: DiscoveryObjective
    supported: bool
    message: str | None = None


class CompanyDiscoveryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "goal_type": "service_pitch",
                    "offering": "Website design and online booking setup",
                    "desired_outcome": "Decide which businesses are worth pitching.",
                    "business_category": "Beauty salons",
                    "location": "Lahore",
                }
            ]
        },
    )

    goal_type: SupportedGoalType = "service_pitch"
    goal: str | None = Field(default=None, max_length=2_000)
    objective: DiscoveryObjective | None = None
    offering: str | None = Field(default=None, max_length=300)
    desired_outcome: str | None = Field(default=None, max_length=300)
    business_category: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("business_category", "industry"),
    )
    location: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("location", "region"),
    )
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_miles: float = Field(default=15, gt=0, le=50)
    max_results: int = Field(default=50, ge=1, le=100)
    company_size: str | None = Field(default=None, max_length=100)
    keywords: str | None = Field(default=None, max_length=255)

    @field_validator(
        "goal",
        "offering",
        "desired_outcome",
        "business_category",
        "location",
        "company_size",
        "keywords",
        mode="before",
    )
    @classmethod
    def normalize_criteria(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value

    @model_validator(mode="after")
    def require_supported_local_discovery_input(self) -> Self:
        if self.objective is not None:
            if self.objective.goal_type not in SUPPORTED_GOAL_TYPES:
                raise ValueError(UNSUPPORTED_GOAL_MESSAGE)
            self.goal_type = self.objective.goal_type
            self.offering = self.offering or self.objective.offering
            self.desired_outcome = (
                self.desired_outcome or self.objective.desired_outcome
            )
            self.business_category = (
                self.business_category
                or _first_value(self.objective.target_sectors)
            )
            self.location = self.location or _first_value(
                self.objective.target_geographies
            )

        missing_fields = [
            label
            for label, value in {
                "offering": self.offering,
                "desired_outcome": self.desired_outcome,
                "business_category": self.business_category,
                "location": self.location,
            }.items()
            if not value
        ]
        if missing_fields:
            raise ValueError(
                "Local business discovery requires: "
                + ", ".join(missing_fields)
                + "."
            )

        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "Local discovery coordinates require both latitude and longitude."
            )

        return self

    @property
    def industry(self) -> str:
        return self.business_category or ""

    @property
    def region(self) -> str:
        return self.location or ""


class DiscoveredCompanyCandidate(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    website: HttpUrl | None = None
    industry: str | None = Field(default=None, max_length=100)
    short_description: str | None = Field(default=None, max_length=1_000)
    match_explanation: str = Field(min_length=1, max_length=1_000)
    supporting_source_urls: list[HttpUrl] = Field(default_factory=list, max_length=5)
    source_provider: str | None = Field(default=None, max_length=100)
    source_record_id: str | None = Field(default=None, max_length=255)
    source_retrieved_at: datetime | None = None
    source_data_release: str | None = Field(default=None, max_length=100)
    formatted_address: str | None = Field(default=None, max_length=500)
    business_status: str | None = Field(default=None, max_length=100)
    phone_number: str | None = Field(default=None, max_length=100)
    website_verification_state: Literal["listed_unverified"] | None = None
    identity_state: Literal["needs_review"] = "needs_review"
    discovery_source_types: list[
        Literal["local_places", "web_search", "social_search"]
    ] = Field(default_factory=list, max_length=3)
    social_profile_urls: list[HttpUrl] = Field(default_factory=list, max_length=5)

    @field_serializer("website")
    def serialize_website(self, value: HttpUrl | None) -> str | None:
        return str(value).rstrip("/") if value is not None else None

    @field_serializer("supporting_source_urls")
    def serialize_supporting_source_urls(self, value: list[HttpUrl]) -> list[str]:
        return [str(url).rstrip("/") for url in value]

    @field_serializer("social_profile_urls")
    def serialize_social_profile_urls(self, value: list[HttpUrl]) -> list[str]:
        return [str(url).rstrip("/") for url in value]

    @field_validator(
        "company_name",
        "industry",
        "short_description",
        "match_explanation",
        "source_provider",
        "source_record_id",
        "source_data_release",
        "formatted_address",
        "business_status",
        "phone_number",
        mode="before",
    )
    @classmethod
    def normalize_text_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value


class CompanyDiscoveryResponse(BaseModel):
    candidates: list[DiscoveredCompanyCandidate] = Field(max_length=100)
