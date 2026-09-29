from datetime import date
from enum import Enum
from typing import List, Literal, Optional
 
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator
 
 
# ---------------------------------------------------------------------------
# Shared / common types
# ---------------------------------------------------------------------------
 
class TimeRange(BaseModel):
    since: date
    until: date
 
    @model_validator(mode="after")
    def check_range_order(self) -> "TimeRange":
        if self.until < self.since:
            raise ValueError("`until` must not be earlier than `since`")
        return self
 
 
class DatePreset(str, Enum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    THIS_QUARTER = "this_quarter"
    MAXIMUM = "maximum"
    DATA_MAXIMUM = "data_maximum"
    LAST_3D = "last_3D"
    LAST_7D = "last_7D"
    LAST_14D = "last_14D"
    LAST_28D = "last_28D"
    LAST_30D = "last_30D"
    LAST_90D = "last_90D"
    LAST_WEEK_MON_SUN = "last_week_mon_sun"
    LAST_WEEK_SUN_SAT = "last_week_sun_sat"
    LAST_QUARTER = "last_quarter"
    THIS_YEAR = "this_year"
    THIS_WEEK_MON_TODAY = "this_week_mon_today"
    THIS_WEEK_SUN_TODAY = "this_week_sun_today"
 
 
class Status(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"
 

 
class BidStrategy(str, Enum):
    LOWEST_COST_WITHOUT_CAP = "LOWEST_COST_WITHOUT_CAP"
    LOWEST_COST_WITH_BID_CAP = "LOWEST_COST_WITH_BID_CAP"
    # COST_CAP = "COST_CAP"
    # LOWEST_COST_WITH_MIN_ROAS = "LOWEST_COST_WITH_MIN_ROAS"
 
 
class Fields(BaseModel):
    """Comma-separated list of fields to request from the Meta API."""
 
    fields: List[str] = Field(
        default=["name", "id", "status"],
        description="List of fields to fetch from the Meta API",
    )
 
    @field_serializer("fields")
    def serialize_fields(self, fields: List[str]) -> str:
        return ",".join(fields)
 
 
class BaseGetRequest(BaseModel):
    """Common shape shared by all *GetRequest models."""

    model_config = ConfigDict(use_enum_values=True)

    fields: Fields = Field(default_factory=Fields)
    date_preset: DatePreset
    time_range: TimeRange
    is_completed: bool


class BaseAdAccountRequest(BaseModel):
    ad_account_id: str = Field(
        description=(
            "Meta ad account ID (numeric only, without act_ prefix). "
            "Get it from GET /me/adaccounts — use the id with act_ stripped."
        ),
        examples=["1234567890"],
    )

    @field_validator("ad_account_id")
    @classmethod
    def validate_ad_account_id(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("act_"):
            normalized = normalized[4:]
        if not normalized.isdigit():
            raise ValueError(
                "ad_account_id must be a numeric Meta ad account ID. "
                "Call GET /me/adaccounts?company_id=... and use the numeric id "
                "(e.g. from act_1234567890 use 1234567890)."
            )
        return normalized


class DestinationType(str, Enum):
    """Required for ODAX (OUTCOME_*) ad sets. Must match `optimization_goal`,
    e.g. POST_ENGAGEMENT -> ON_POST, PAGE_LIKES -> ON_PAGE."""

    WEBSITE = "WEBSITE"
    APP = "APP"
    INSTAGRAM_DIRECT = "INSTAGRAM_DIRECT"
    INSTAGRAM_PROFILE = "INSTAGRAM_PROFILE"
    FACEBOOK = "FACEBOOK"
    FACEBOOK_PAGE = "FACEBOOK_PAGE"
    ON_POST = "ON_POST"
    ON_PAGE = "ON_PAGE"
    NONE = "NONE"



class BaseAdAccountGetRequest(BaseGetRequest):
    ad_account_id: str = Field(
        description=(
            "Meta ad account ID (numeric only, without act_ prefix). "
            "Get it from GET /me/adaccounts — use the id with act_ stripped."
        ),
        examples=["1234567890"],
    )

    @field_validator("ad_account_id")
    @classmethod
    def validate_ad_account_id(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("act_"):
            normalized = normalized[4:]
        if not normalized.isdigit():
            raise ValueError(
                "ad_account_id must be a numeric Meta ad account ID. "
                "Call GET /me/adaccounts?company_id=... and use the numeric id "
                "(e.g. from act_1234567890 use 1234567890)."
            )
        return normalized
 
 
class Objective(str, Enum):
    """Meta Marketing API v25+ campaign objectives (ODAX / outcome-based only)."""

    OUTCOME_LEADS = "OUTCOME_LEADS"
    OUTCOME_SALES = "OUTCOME_SALES"
    OUTCOME_ENGAGEMENT = "OUTCOME_ENGAGEMENT"
    OUTCOME_AWARENESS = "OUTCOME_AWARENESS"
    OUTCOME_TRAFFIC = "OUTCOME_TRAFFIC"


class SpecialAdCategory(str, Enum):
    NONE = "NONE"
    EMPLOYMENT = "EMPLOYMENT"
    HOUSING = "HOUSING"
    CREDIT = "CREDIT"
    ISSUES_ELECTIONS_POLITICS = "ISSUES_ELECTIONS_POLITICS"
    ONLINE_GAMBLING_AND_GAMING = "ONLINE_GAMBLING_AND_GAMING"
    FINANCIAL_PRODUCTS_SERVICES = "FINANCIAL_PRODUCTS_SERVICES"



# ---------------------------------------------------------------------------
# Adset
# ---------------------------------------------------------------------------
 
class BillingEvent(str, Enum):
    APP_INSTALLS = "APP_INSTALLS"
    IMPRESSIONS = "IMPRESSIONS"
    LINK_CLICKS = "LINK_CLICKS"
    PAGE_LIKES = "PAGE_LIKES"
    POST_ENGAGEMENT = "POST_ENGAGEMENT"
 
 
class OptimizationGoal(str, Enum):
    REACH = "REACH"
    LINK_CLICKS = "LINK_CLICKS"
    LANDING_PAGE_VIEWS = "LANDING_PAGE_VIEWS"
    POST_ENGAGEMENT = "POST_ENGAGEMENT"
    LEAD_GENERATION = "LEAD_GENERATION"
    OFFSITE_CONVERSIONS = "OFFSITE_CONVERSIONS"
    VALUE = "VALUE"
    APP_INSTALLS = "APP_INSTALLS"
 
 
class PromotedObject(BaseModel):
    # NOTE: Meta's real `promoted_object` is polymorphic and varies by
    # objective (pixel_id, application_id, product_set_id, custom_event_type,
    # etc). This currently only covers the page_id case (e.g. PAGE_LIKES,
    # BRAND_AWARENESS). Extend with optional fields or a discriminated
    # union keyed on Objective if/when other objectives are supported.
    page_id: str
 
 
# Valid `user_os` values per Meta's targeting spec.
UserOs = Literal[
    "iOS",
    "Android",
    "Android_ver_4.2_and_above",
    "iOS_ver_8.0_to_9.0",
]
 
Gender = Literal[1, 2, 3]  # 1: male, 2: female, 3: unknown
 
 
class City(BaseModel):
    key: str
    radius: int
    distance_unit: str
 
 
class GeoLocation(BaseModel):
    countries: Optional[List[str]] = Field(default=None, description="Countries")
    cities: Optional[List[City]] = Field(default=None, description="Cities")
 
 
class IndividualSetting(BaseModel):
    """Per-dimension strict vs. relaxed matching toggles."""

    age: Literal[0, 1] = Field(description="0: strict age matching, 1: relaxed age matching")
    gender: Literal[0, 1] = Field(description="0: strict gender matching, 1: relaxed gender matching")
    geo: Literal[0, 1] = Field(description="0: strict geo matching, 1: relaxed geo matching")

 
 
class TargetingAutomation(BaseModel):
    advantage_audience: Literal[0, 1] = 1
    individual_setting: Optional[IndividualSetting] = Field(default=None, description="Individual setting")
 
 
class Targeting(BaseModel):
    user_os: Optional[List[UserOs]] = Field(default=None, description="User OS")
    age_min: Optional[int] = Field(default=None, ge=13, le=65)
    age_max: Optional[int] = Field(
        default=None,
        ge=13,
        le=65,
        description=(
            "Hard max age. With targeting_automation.advantage_audience = 1, Meta rejects "
            "age_max below 65; send 65 and put the preferred range in age_range, or set "
            "advantage_audience to 0."
        ),
    )
    age_range: Optional[List[int]] = Field(default=None, min_length=2, max_length=2)
    genders: Optional[List[Gender]] = Field(default=None, description="Genders")
    geo_locations: Optional[GeoLocation] = Field(default=None, description="Geo locations")
    targeting_automation: Optional[TargetingAutomation] = Field(default=None, description="Targeting automation")
 
    @model_validator(mode="after")
    def check_age_bounds(self) -> "Targeting":
        if (
            self.age_min is not None
            and self.age_max is not None
            and self.age_min > self.age_max
        ):
            raise ValueError("`age_min` must not be greater than `age_max`")
        return self
 

# ---------------------------------------------------------------------------
# Ad / Creative
# ---------------------------------------------------------------------------

class CallToActionType(str, Enum):
    LEARN_MORE = "LEARN_MORE"
    SHOP_NOW = "SHOP_NOW"
    SIGN_UP = "SIGN_UP"
    BOOK_TRAVEL = "BOOK_TRAVEL"
    CONTACT_US = "CONTACT_US"
    DOWNLOAD = "DOWNLOAD"
    GET_OFFER = "GET_OFFER"
    GET_QUOTE = "GET_QUOTE"
    SUBSCRIBE = "SUBSCRIBE"
    WATCH_MORE = "WATCH_MORE"
    APPLY_NOW = "APPLY_NOW"
    BUY_NOW = "BUY_NOW"
    GET_DIRECTIONS = "GET_DIRECTIONS"
    MESSAGE_PAGE = "MESSAGE_PAGE"
    CALL_NOW = "CALL_NOW"
    LISTEN_NOW = "LISTEN_NOW"
    WATCH_VIDEO = "WATCH_VIDEO"
    NO_BUTTON = "NO_BUTTON"


class CreativeLinkData(BaseModel):
    link: str = Field(description="Destination website URL (required for traffic/conversion objectives)")
    message: Optional[str] = Field(default=None, description="Primary ad text")
    call_to_action_type: CallToActionType = Field(
        default=CallToActionType.LEARN_MORE,
        description="Button type shown on the ad",
    )
    name: Optional[str] = Field(default=None, description="Link headline")
    picture: Optional[str] = Field(default=None, description="Image URL for the link preview")
    image_hash: Optional[str] = Field(
        default=None,
        description="Image hash from POST /act_{id}/adimages (alternative to picture)",
    )


class CreativeCallToAction(BaseModel):
    type: CallToActionType = Field(
        default=CallToActionType.LEARN_MORE,
        description="Button type shown on the Instagram boost.",
    )
    link: Optional[str] = Field(
        default=None,
        description="Destination URL. Required for LEARN_MORE and other URL CTAs.",
    )


class CreativeObjectStorySpec(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "page_id": "string",
                "link_data": {
                    "link": "string",
                    "message": "string",
                    "call_to_action_type": "LEARN_MORE",
                },
            }
        }
    )

    page_id: str = Field(description="Facebook Page ID that publishes the ad")
    link_data: CreativeLinkData
    instagram_user_id: Optional[str] = Field(
        default=None,
        description="Instagram professional account ID so the ad can also run on Instagram.",
    )






#########################################################################

class BoostMetaPostRequest(BaseAdAccountRequest):
    model_config = ConfigDict(use_enum_values=True)

    name: str
    objective: Objective
    status: Status
    bid_strategy: Optional[BidStrategy] = None
    bid_amount: Optional[int] = Field(
        default=None,
        description="Required for bid-cap/cost-cap strategies, in minor currency units.",
    )
    daily_budget: int = Field(
        ge=1,
        description=(
            "Daily budget in the ad account's minor currency unit "
            "(e.g. cents for USD, öre for SEK). "
            "Typical Meta minimums: ~100 ($1/day) for traffic/awareness; "
            "~4000 ($40/day) for app promotion (OUTCOME_APP_PROMOTION). "
            "Exact minimum depends on ad account currency and objective."
        ),
    )
    special_ad_categories: List[SpecialAdCategory] = Field(
        default_factory=list,
        description="Required by Meta. Use [] for regular (non-special) campaigns.",
    )
    special_ad_category_country: Optional[List[str]] = Field(
        default=None,
        description="ISO country codes. Required when special_ad_categories is not empty.",
    )
    object_story_id: Optional[str] = Field(
        default=None,
        description=(
            "Existing Facebook Page post ID ({page_id}_{post_id}). "
            "Use for boosting an existing Facebook post. "
            "Do not pass an Instagram media id here."
        ),
    )
    object_story_spec: Optional[CreativeObjectStorySpec] = Field(
        default=None,
        description=(
            "Specification for creating an inline ad creative when boosting "
            "without an existing page or Instagram post ID."
        ),
    )
    source_instagram_media_id: Optional[str] = Field(
        default=None,
        description=(
            "Existing Instagram media ID to boost "
            "(published post platform_post_id / media_id). "
            "Use this instead of object_story_id for Instagram."
        ),
    )
    instagram_user_id: Optional[str] = Field(
        default=None,
        description=(
            "Instagram professional account ID (ig_user_id). Required when boosting "
            "an Instagram post unless the company has exactly one connected IG account."
        ),
    )
    page_id: Optional[str] = Field(
        default=None,
        description=(
            "Facebook Page ID Meta needs as object_id when boosting Instagram. "
            "If omitted, the company's selected Page is used."
        ),
    )
    instagram_call_to_action: Optional[CreativeCallToAction] = Field(
        default=None,
        description=(
            "Optional CTA overlay when boosting an Instagram post "
            "(e.g. LEARN_MORE + link for traffic objectives)."
        ),
    )
    engagement_audience: Optional[bool] = Field(
        default=None,
        description="Optional toggle for engagement targeting.",
    )
    optimization_goal: Optional[OptimizationGoal] = Field(
        default=None,
        description="Defaults to a goal that's valid for the chosen objective.",
    )
    billing_event: Optional[BillingEvent] = Field(
        default=None,
        description="Defaults to a billing event compatible with optimization_goal.",
    )
    destination_type: Optional[DestinationType] = Field(
        default=None,
        description=(
            "Required for ODAX (OUTCOME_*) ad sets; defaults to the value that "
            "matches optimization_goal (e.g. POST_ENGAGEMENT -> ON_POST)."
        ),
    )
    targeting: Optional[Targeting] = Field(
        default=None,
        description=(
            "Defaults to the countries in special_ad_category_country when omitted."
        ),
    )
    promoted_object: Optional[PromotedObject] = Field(
        default=None,
        description="Required by some optimization goals (e.g. PAGE_LIKES, LEAD_GENERATION).",
    )
    dsa_payor: Optional[str] = Field(
        default=None,
        description="EU transparency (DSA) payor — required for ad accounts serving the EU.",
    )
    dsa_beneficiary: Optional[str] = Field(
        default=None,
        description="EU transparency (DSA) beneficiary — required for ad accounts serving the EU.",
    )

    @model_validator(mode="after")
    def validate_bid_strategy_and_amount(self) -> "BoostMetaPostRequest":
        if self.bid_strategy == BidStrategy.LOWEST_COST_WITHOUT_CAP and self.bid_amount is not None:
            raise ValueError(
                "Cannot set `bid_amount` when `bid_strategy` is `LOWEST_COST_WITHOUT_CAP`. "
                "Remove `bid_amount` or change `bid_strategy` to `LOWEST_COST_WITH_BID_CAP`."
            )
        return self

    @model_validator(mode="after")
    def check_special_ad_category_country(self) -> "BoostMetaPostRequest":
        active_categories = [
            category
            for category in self.special_ad_categories
            if category not in (SpecialAdCategory.NONE, "NONE")
        ]
        if active_categories and not self.special_ad_category_country:
            raise ValueError(
                "special_ad_category_country is required when special_ad_categories is set"
            )
        return self

    @model_validator(mode="after")
    def check_creative_source(self) -> "BoostMetaPostRequest":
        sources = [
            bool(self.object_story_id),
            bool(self.object_story_spec),
            bool(self.source_instagram_media_id),
        ]
        if sum(sources) == 0:
            raise ValueError(
                "Provide object_story_id (Facebook Page post), "
                "source_instagram_media_id (Instagram post), or object_story_spec"
            )
        if sum(sources) > 1:
            raise ValueError(
                "Provide only one of object_story_id, source_instagram_media_id, "
                "or object_story_spec"
            )
        return self


class CommonBoostAdRequest(BaseAdAccountRequest):
    model_config = ConfigDict(use_enum_values=True)

    name: str
    objective: Objective
    status: Status

    bid_strategy: Optional[BidStrategy] = None

    bid_amount: Optional[int] = Field(
        default=None,
        description=(
            "Required for bid-cap/cost-cap strategies, in minor currency units."
        ),
    )

    daily_budget: int = Field(
        ge=1,
        description=(
            "Daily budget in the ad account's minor currency unit."
        ),
    )

    special_ad_categories: List[SpecialAdCategory] = Field(
        default_factory=list,
        description="Use [] for regular (non-special) campaigns.",
    )

    special_ad_category_country: Optional[List[str]] = Field(
        default=None,
        description=(
            "ISO country codes. Required when special_ad_categories "
            "contains a category other than NONE."
        ),
    )

    engagement_audience: Optional[bool] = Field(
        default=None,
        description="Optional toggle for engagement targeting.",
    )

    optimization_goal: Optional[OptimizationGoal] = Field(
        default=None,
        description=(
            "Defaults to a goal compatible with the selected objective."
        ),
    )

    billing_event: Optional[BillingEvent] = Field(
        default=None,
        description=(
            "Defaults to a billing event compatible with optimization_goal."
        ),
    )

    destination_type: Optional[DestinationType] = Field(
        default=None,
        description=(
            "Required for ODAX (OUTCOME_*) ad sets. "
            "Must be compatible with optimization_goal."
        ),
    )

    targeting: Optional[Targeting] = Field(
        default=None,
        description=(
            "Defaults to the countries in special_ad_category_country "
            "when omitted."
        ),
    )

    promoted_object: Optional[PromotedObject] = Field(
        default=None,
        description=(
            "Required by optimization goals that need a promoted object."
        ),
    )

    dsa_payor: Optional[str] = Field(
        default=None,
        description=(
            "EU transparency (DSA) payor."
        ),
    )

    dsa_beneficiary: Optional[str] = Field(
        default=None,
        description=(
            "EU transparency (DSA) beneficiary."
        ),
    )

    @model_validator(mode="after")
    def validate_bid_strategy_and_amount(self) -> "CommonBoostAdRequest":
        if (
            self.bid_strategy == BidStrategy.LOWEST_COST_WITHOUT_CAP
            and self.bid_amount is not None
        ):
            raise ValueError(
                "Cannot set `bid_amount` when `bid_strategy` is "
                "`LOWEST_COST_WITHOUT_CAP`. Remove `bid_amount` or change "
                "`bid_strategy` to `LOWEST_COST_WITH_BID_CAP`."
            )

        return self

    @model_validator(mode="after")
    def check_special_ad_category_country(self) -> "CommonBoostAdRequest":
        active_categories = [
            category
            for category in self.special_ad_categories
            if category not in (
                SpecialAdCategory.NONE,
                "NONE",
            )
        ]

        if active_categories and not self.special_ad_category_country:
            raise ValueError(
                "special_ad_category_country is required when "
                "special_ad_categories is set"
            )

        return self


class BoostFacebookPostRequest(CommonBoostAdRequest):
    object_story_id: Optional[str] = Field(
        default=None,
        description=(
            "Existing Facebook Page post ID in the format "
            "{page_id}_{post_id}. Provide this or object_story_spec, not both."
        ),
    )

    page_id: Optional[str] = Field(
        default=None,
        description=(
            "Facebook Page ID that owns the post. "
            "If omitted, it may be resolved from object_story_id."
        ),
    )

    object_story_spec: Optional[CreativeObjectStorySpec] = Field(
        default=None,
        description=(
            "Inline creative with a destination URL (page_id + link_data). "
            "Use this instead of object_story_id for WEBSITE destination. "
            "Provide this or object_story_id, not both."
        ),
        examples=[
            {
                "page_id": "string",
                "link_data": {
                    "link": "string",
                    "message": "string",
                    "call_to_action_type": "LEARN_MORE",
                },
            }
        ],
    )

    @model_validator(mode="after")
    def check_creative_source(self) -> "BoostFacebookPostRequest":
        has_story_id = bool(self.object_story_id)
        has_story_spec = self.object_story_spec is not None
        if has_story_id == has_story_spec:
            raise ValueError(
                "Provide exactly one of object_story_id or object_story_spec, not both."
            )
        return self

class BoostInstagramPostRequest(CommonBoostAdRequest):
    source_instagram_media_id: str = Field(
        ...,
        description=(
            "Existing Instagram media ID to boost."
        ),
    )

    instagram_user_id: str = Field(
        ...,
        description=(
            "Instagram professional account ID (ig_user_id) "
            "that owns the media."
        ),
    )

    page_id: str = Field(
        ...,
        description=(
            "Facebook Page ID connected to the Instagram professional "
            "account."
        ),
    )

    instagram_call_to_action: Optional[CreativeCallToAction] = Field(
        default=None,
        description=(
            "CTA used when boosting an Instagram post. "
            "For website destinations, this contains the destination link."
        ),
    )