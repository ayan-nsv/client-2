import json
import httpx
import requests
from sqlalchemy.orm import Session
from fastapi import Depends, APIRouter, HTTPException, status

from products.market_planner.social_media.meta.boost.schema import meta_boost_schema 
from products.market_planner.social_media.meta.facebook.repository.facebook_repo import FacebookRepository
from products.market_planner.social_media.meta.facebook.tables import facebook_tables
from products.market_planner.social_media.meta.instagram.tables import instagram_tables

from shared.database.postgres.database_config import get_db
from shared.utils.error import error

from core.repository.company_repo import CompanyRepository

router = APIRouter()

META_BOOST_API_BASE_URL = "https://graph.facebook.com/v25.0"


_TRANSLATIONS = [
    # (substrings that must all appear in Meta's message, lowercased) -> (title, suggestion)
    (
        ("performance goal", "objective"),
        (
            "optimization_goal doesn't match the campaign objective",
            "Set `destination_type` on the ad set to match `optimization_goal`: "
            "POST_ENGAGEMENT -> ON_POST, PAGE_LIKES -> ON_PAGE, THRUPLAY -> ON_VIDEO, "
            "CONVERSATIONS -> MESSENGER (or WHATSAPP/INSTAGRAM_DIRECT). "
            "Or pick a different optimization_goal that's valid for this campaign's objective.",
        ),
    ),
    (
        ("special ad categor",),
        (
            "special_ad_category_country is missing",
            "Since special_ad_categories isn't [\"NONE\"], you must also set "
            "special_ad_category_country to the ISO country codes you're targeting.",
        ),
    ),
    (
        ("minimum", "budget"),
        (
            "daily_budget is below Meta's minimum for this objective/currency",
            "Increase daily_budget. It's in the ad account's minor currency unit "
            "(e.g. öre for SEK, cents for USD) — a few hundred is usually too low.",
        ),
    ),
    (
        ("beneficiary",),
        (
            "Missing required EU transparency (DSA) info",
            "Set both dsa_payor and dsa_beneficiary on the ad set "
            "(usually your business/Page name) — required for ad accounts serving the EU.",
        ),
    ),
    (
        ("access token", "expired"),
        (
            "The Facebook connection has expired",
            "Reconnect the Facebook account/Page for this company and try again.",
        ),
    ),
    (
        ("does not have the capability", "permission"),
        (
            "Missing permission on this ad account or Page",
            "Make sure the connected Facebook user has Admin/Advertiser access to "
            "both the ad account and the Page, then reconnect.",
        ),
    ),
    (
        ("audience", "narrow"),
        (
            "Targeting is too narrow to deliver",
            "Broaden `targeting` — widen the age range, add geo_locations, or "
            "relax other targeting fields.",
        ),
    ),
    (
        ("missing field",),
        (
            "Meta needs a field that wasn't sent",
            "The ad set spec is incomplete for this objective. Send the missing field "
            "explicitly in the request (billing_event, optimization_goal, targeting, "
            "destination_type or promoted_object).",
        ),
    ),
    (
        ("external website url",),
        (
            "The ad creative is missing a destination URL",
            "Your campaign objective (e.g. OUTCOME_TRAFFIC, OUTCOME_SALES, OUTCOME_LEADS) "
            "requires a website link. Create the ad creative with `object_story_spec.link_data.link` "
            "and `call_to_action_type` instead of only `object_story_id`, or boost a post that "
            "already contains a link. For Instagram, send `instagram_call_to_action` with a link.",
        ),
    ),
    (
        ("source_instagram_media_id",),
        (
            "This Instagram media can't be used as an ad creative",
            "Confirm source_instagram_media_id is a published Instagram professional-account "
            "media id (platform_post_id), the account is connected to the Page (page_id / object_id), "
            "and instagram_user_id matches that account. The media must be boost-eligible.",
        ),
    ),
    (
        ("instagram user",),
        (
            "instagram_user_id is missing or not connected to this Page",
            "Send the Instagram professional account id (ig_user_id) that is linked to page_id.",
        ),
    ),
    (
        ("does not have access to this instagram account",),
        (
            "This ad account is not authorized to advertise on that Instagram account",
            "In Meta Business settings, assign this ad account to the Instagram profile "
            "(Accounts → Instagram accounts → Connected assets → Ad account). "
            "Confirm with GET /act_{ad_account_id}/instagram_accounts?company_id=... that "
            "instagram_user_id is in the returned list, and that page_id is the Facebook Page "
            "linked to that same IG account.",
        ),
    ),
    (
        ("maximum age", "suggestion"),
        (
            "Advantage+ audience can't use a hard age_max below 65",
            "Either set targeting.targeting_automation.advantage_audience to 0 to keep ages 23–53 as a hard range, "
            "or keep Advantage+ on, set age_max to 65, and put the preferred range in age_range "
            "with targeting_automation.individual_setting.age = 1 (suggestion, not a cap).",
        ),
    ),
]


def _translate_meta_error(message: str) -> tuple[str, str] | None:
    """Map a known Meta error message to (plain-language title, concrete next step)."""
    lowered = message.lower()
    for required_substrings, translation in _TRANSLATIONS:
        if all(s in lowered for s in required_substrings):
            return translation
    return None


def _raise_meta_graph_error(response: requests.Response, context: str = "request") -> None:
    try:
        body = response.json()
    except ValueError:
        raise error.InternalServerError(message=f"Meta returned an unreadable response for the {context}: {response.text}")

    meta_error = body.get("error", body) if isinstance(body, dict) else body
    if isinstance(meta_error, dict):
        raw_message = meta_error.get("error_user_msg") or meta_error.get("message") or json.dumps(body)
        fbtrace_id = meta_error.get("fbtrace_id")
    else:
        raw_message = str(meta_error)
        fbtrace_id = None

    translation = _translate_meta_error(raw_message)
    if translation:
        title, suggestion = translation
        friendly = f"Couldn't complete the {context}: {title}. {suggestion} (Meta said: \"{raw_message}\")"
    else:
        friendly = (
            f"Couldn't complete the {context}: Meta rejected it with \"{raw_message}\". "
            "Double-check the fields you just set match what's required for the chosen "
            "objective/optimization_goal."
        )
    if fbtrace_id:
        friendly += f" [ref: {fbtrace_id}]"

    raise error.BadRequest(message=friendly)



# accounts
@router.get("/me/adaccounts", tags=["meta boost"])
def get_ad_accounts(company_id: str, db: Session = Depends(get_db)):
    try:
        access_token = FacebookRepository(db).get_access_token_from_company_id(company_id)
        url = f"{META_BOOST_API_BASE_URL}/me/adaccounts"
        response = requests.get(url, params={"access_token": access_token}, timeout=30)
        if response.status_code != 200:
            _raise_meta_graph_error(response, context="ad accounts lookup")
        return response.json()
    except HTTPException:
        raise
    except Exception as e:
        raise error.InternalServerError(message=str(e))

def _build_object_story_spec_payload(spec) -> str:
    link_data = spec.link_data.model_dump(exclude_none=True)
    call_to_action_type = link_data.pop("call_to_action_type", "LEARN_MORE")
    link_data["call_to_action"] = {"type": call_to_action_type}
    payload = {
        "page_id": spec.page_id,
        "link_data": link_data,
    }
    if spec.instagram_user_id:
        payload["instagram_user_id"] = spec.instagram_user_id
    return json.dumps(payload)


def _resolve_instagram_boost_identities(
    company_id: str,
    request: meta_boost_schema.BoostMetaPostRequest,
    db: Session,
) -> tuple[str, str]:
    """Page id (Meta object_id) and Instagram user id for an organic IG boost."""
    company_id_int = CompanyRepository(db).get_company_id_from_uuid(company_id)
    page_id = (request.page_id or "").strip() or None
    ig_user_id = (request.instagram_user_id or "").strip() or None

    if not page_id:
        page = (
            db.query(facebook_tables.FacebookInstaPage)
            .join(
                facebook_tables.FacebookInstaAccount,
                facebook_tables.FacebookInstaPage.facebook_insta_account_id == facebook_tables.FacebookInstaAccount.id,
            )
            .filter(
                facebook_tables.FacebookInstaAccount.company_id == company_id_int,
                facebook_tables.FacebookInstaPage.is_selected.is_(True),
            )
            .first()
        )
        if page is None:
            page = (
                db.query(facebook_tables.FacebookInstaPage)
                .join(
                    facebook_tables.FacebookInstaAccount,
                    facebook_tables.FacebookInstaPage.facebook_insta_account_id == facebook_tables.FacebookInstaAccount.id,
                )
                .filter(facebook_tables.FacebookInstaAccount.company_id == company_id_int)
                .first()
            )
        if page is not None:
            page_id = page.page_id

    if not ig_user_id:
        accounts = (
            db.query(instagram_tables.InstagramAccount)
            .filter(instagram_tables.InstagramAccount.company_id == company_id_int)
            .all()
        )
        if len(accounts) == 1:
            ig_user_id = accounts[0].ig_user_id
        elif accounts:
            selected_page = (
                db.query(facebook_tables.FacebookInstaPage)
                .join(
                    facebook_tables.FacebookInstaAccount,
                    facebook_tables.FacebookInstaPage.facebook_insta_account_id == facebook_tables.FacebookInstaAccount.id,
                )
                .filter(
                    facebook_tables.FacebookInstaAccount.company_id == company_id_int,
                    facebook_tables.FacebookInstaPage.is_selected.is_(True),
                )
                .first()
            )
            if selected_page is not None:
                linked = next(
                    (
                        account
                        for account in accounts
                        if account.facebook_insta_page_id == selected_page.id
                    ),
                    None,
                )
                if linked is not None:
                    ig_user_id = linked.ig_user_id
            if not ig_user_id:
                ig_user_id = accounts[0].ig_user_id

    if not page_id or not ig_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Boosting an Instagram post needs both page_id (Facebook Page, used as Meta object_id) "
                "and instagram_user_id (the professional IG account connected to that Page). "
                "Pass them explicitly, or connect/select a Page and Instagram account for this company."
            ),
        )
    return page_id, ig_user_id




# (optimization_goal, billing_event, destination_type) Meta accepts for each ODAX objective.
_OBJECTIVE_ADSET_DEFAULTS = {
    "OUTCOME_AWARENESS": ("REACH", "IMPRESSIONS", None),
    "OUTCOME_TRAFFIC": ("LINK_CLICKS", "IMPRESSIONS", "WEBSITE"),
    "OUTCOME_ENGAGEMENT": ("POST_ENGAGEMENT", "IMPRESSIONS", "ON_POST"),
    "OUTCOME_LEADS": ("LINK_CLICKS", "IMPRESSIONS", "WEBSITE"),
    "OUTCOME_SALES": ("LINK_CLICKS", "IMPRESSIONS", "WEBSITE"),
    "OUTCOME_APP_PROMOTION": ("LINK_CLICKS", "IMPRESSIONS", "WEBSITE"),
}


def _normalize_advantage_audience_targeting(targeting: dict) -> dict:
    """Advantage+ forbids a hard age_max below 65; treat the range as a suggestion instead."""
    automation = targeting.get("targeting_automation") or {}
    if automation.get("advantage_audience") != 1:
        return targeting

    age_max = targeting.get("age_max")
    if age_max is None or age_max >= 65:
        return targeting

    age_min = targeting.get("age_min")
    if targeting.get("age_range") is None and age_min is not None:
        targeting["age_range"] = [age_min, age_max]
    targeting["age_max"] = 65

    individual = automation.get("individual_setting") or {}
    individual["age"] = 1
    individual.setdefault("gender", 1)
    individual.setdefault("geo", 1)
    automation["individual_setting"] = individual
    targeting["targeting_automation"] = automation
    return targeting


def _build_boost_adset_payload(request: meta_boost_schema.BoostMetaPostRequest, campaign_id: str, access_token: str) -> dict:
    default_goal, default_billing_event, default_destination = _OBJECTIVE_ADSET_DEFAULTS.get(
        request.objective, (None, "IMPRESSIONS", None)
    )

    if request.targeting is not None:
        targeting = request.targeting.model_dump(exclude_none=True)
        targeting = _normalize_advantage_audience_targeting(targeting)
    elif request.special_ad_category_country:
        targeting = {"geo_locations": {"countries": request.special_ad_category_country}}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Meta requires targeting on the ad set. Send `targeting` "
                "(at least geo_locations.countries) or `special_ad_category_country`."
            ),
        )

    payload = {
        "name": request.name,
        "campaign_id": campaign_id,
        "daily_budget": request.daily_budget,
        "status": request.status,
        "billing_event": request.billing_event or default_billing_event,
        "optimization_goal": request.optimization_goal or default_goal,
        "targeting": json.dumps(targeting),
        "access_token": access_token,
    }

    # Budget lives on the ad set here, so the bid strategy has to as well.
    if request.bid_strategy is not None:
        payload["bid_strategy"] = request.bid_strategy
    if request.bid_amount is not None:
        payload["bid_amount"] = request.bid_amount

    destination_type = request.destination_type or default_destination
    if destination_type is not None:
        payload["destination_type"] = destination_type

    promoted_object = request.promoted_object
    if promoted_object is not None:
        payload["promoted_object"] = json.dumps(promoted_object.model_dump(exclude_none=True))
    if request.dsa_payor is not None:
        payload["dsa_payor"] = request.dsa_payor
    if request.dsa_beneficiary is not None:
        payload["dsa_beneficiary"] = request.dsa_beneficiary

    return {key: value for key, value in payload.items() if value is not None}


def get_access_token_from_company_id(company_id: str, db: Session) -> str:
    """Get Meta user long-lived access token for a company."""
    company_id_int = CompanyRepository(db).get_company_id_from_uuid(company_id)
    account = db.query(facebook_tables.FacebookInstaAccount).filter(
        facebook_tables.FacebookInstaAccount.company_id == company_id_int
    ).first()
    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"Facebook account not found for company {company_id}",
        )
    access_token = account.user_long_token
    if not access_token:
        raise HTTPException(
            status_code=404,
            detail=f"Access token not found for company {company_id}",
        )
    return access_token

@router.post("/boost")
async def boost_meta_post(request: meta_boost_schema.BoostMetaPostRequest, company_id: str, db: Session = Depends(get_db)):
    try:
        access_token = get_access_token_from_company_id(company_id, db)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Could not get access token from company ID: {str(err)}"
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Step 1: Create Campaign
            url = f"{META_BOOST_API_BASE_URL}/act_{request.ad_account_id}/campaigns"
            payload = {
                "name": request.name,
                "objective": request.objective,
                "status": request.status,
                "access_token": access_token,
                "special_ad_categories": json.dumps(request.special_ad_categories),
                "is_adset_budget_sharing_enabled": "0",
            }
            if request.special_ad_category_country:
                payload["special_ad_category_country"] = json.dumps(request.special_ad_category_country)
            
            response = await client.post(url, data=payload)
            if response.status_code != 200:
                _raise_meta_graph_error(response, context="campaign creation")
            campaign_id = response.json()["id"]

            # Step 2: Create AdSet
            url = f"{META_BOOST_API_BASE_URL}/act_{request.ad_account_id}/adsets"
            payload = _build_boost_adset_payload(request, campaign_id, access_token)
            response = await client.post(url, data=payload)
            if response.status_code != 200:
                _raise_meta_graph_error(response, context="ad set creation")
            adset_id = response.json()["id"]

            # Step 3: Create Ad Creative
            url = f"{META_BOOST_API_BASE_URL}/act_{request.ad_account_id}/adcreatives"
            payload = {
                "name": request.name,
                "access_token": access_token,
            }
            if request.object_story_id:
                payload["object_story_id"] = request.object_story_id
                if request.instagram_user_id:
                    payload["instagram_user_id"] = request.instagram_user_id
            elif request.source_instagram_media_id:
                page_id, ig_user_id = _resolve_instagram_boost_identities(
                    company_id, request, db
                )
                payload["object_id"] = page_id
                payload["instagram_user_id"] = ig_user_id
                payload["source_instagram_media_id"] = request.source_instagram_media_id
                if request.instagram_call_to_action is not None:
                    cta_type = request.instagram_call_to_action.type
                    if hasattr(cta_type, "value"):
                        cta_type = cta_type.value
                    call_to_action = {"type": cta_type}
                    if request.instagram_call_to_action.link:
                        call_to_action["value"] = {
                            "link": request.instagram_call_to_action.link
                        }
                    payload["call_to_action"] = json.dumps(call_to_action)
            elif getattr(request, "object_story_spec", None):
                payload["object_story_spec"] = _build_object_story_spec_payload(
                    request.object_story_spec
                )
            
            response = await client.post(url, data=payload)
            if response.status_code != 200:
                _raise_meta_graph_error(response, context="ad creative creation")
            ad_creative_id = response.json()["id"]

            # Step 4: Create Ad
            url = f"{META_BOOST_API_BASE_URL}/act_{request.ad_account_id}/ads"
            payload = {
                "name": request.name,
                "adset_id": adset_id,
                "creative": json.dumps({"creative_id": ad_creative_id}),
                "status": request.status,
                "access_token": access_token,
            }
            if getattr(request, "engagement_audience", None):
                payload["engagement_audience"] = request.engagement_audience

            response = await client.post(url, data=payload)
            if response.status_code != 200:
                _raise_meta_graph_error(response, context="ad creation")
            
            return {"ad_id": response.json()["id"]}

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred while creating Meta Boost pipeline: {str(exc)}"
            )




@router.post("/boost/facebook-post")
async def boost_facebook_post(
    request: meta_boost_schema.BoostFacebookPostRequest,
    company_id: str,
    db: Session = Depends(get_db),
):
    try:
        access_token = get_access_token_from_company_id(company_id, db)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not get access token from company ID: {str(err)}",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Step 1: Create Campaign
            campaign_id = await _create_boost_campaign(
                client=client,
                request=request,
                access_token=access_token,
            )

            # Step 2: Create Ad Set
            adset_id = await _create_boost_adset(
                client=client,
                request=request,
                campaign_id=campaign_id,
                access_token=access_token,
            )

            # Step 3: Create Facebook Post Creative
            ad_creative_id = await _create_facebook_post_creative(
                client=client,
                request=request,
                access_token=access_token,
            )

            # Step 4: Create Ad
            ad_id = await _create_boost_ad(
                client=client,
                request=request,
                adset_id=adset_id,
                ad_creative_id=ad_creative_id,
                access_token=access_token,
            )

            return {"ad_id": ad_id}

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"An error occurred while boosting Facebook post: {str(exc)}"
                ),
            )

@router.post("/boost/instagram-post")
async def boost_instagram_post(
    request: meta_boost_schema.BoostInstagramPostRequest,
    company_id: str,
    db: Session = Depends(get_db),
):
    try:
        access_token = get_access_token_from_company_id(company_id, db)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not get access token from company ID: {str(err)}",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Step 1: Create Campaign
            campaign_id = await _create_boost_campaign(
                client=client,
                request=request,
                access_token=access_token,
            )

            # Step 2: Create Ad Set
            adset_id = await _create_boost_adset(
                client=client,
                request=request,
                campaign_id=campaign_id,
                access_token=access_token,
            )

            # Step 3: Create Instagram Post Creative
            ad_creative_id = await _create_instagram_post_creative(
                client=client,
                request=request,
                company_id=company_id,
                db=db,
                access_token=access_token,
            )

            # Step 4: Create Ad
            ad_id = await _create_boost_ad(
                client=client,
                request=request,
                adset_id=adset_id,
                ad_creative_id=ad_creative_id,
                access_token=access_token,
            )

            return {"ad_id": ad_id}

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"An error occurred while boosting Instagram post: {str(exc)}"
                ),
            )


async def _create_boost_campaign(
    client: httpx.AsyncClient,
    request: meta_boost_schema.CommonBoostAdRequest,
    access_token: str,
) -> str:

    url = (
        f"{META_BOOST_API_BASE_URL}/"
        f"act_{request.ad_account_id}/campaigns"
    )

    payload = {
        "name": request.name,
        "objective": request.objective,
        "status": request.status,
        "access_token": access_token,
        "special_ad_categories": json.dumps(
            request.special_ad_categories
        ),
        "is_adset_budget_sharing_enabled": "0",
    }

    if request.special_ad_category_country:
        payload["special_ad_category_country"] = json.dumps(
            request.special_ad_category_country
        )

    response = await client.post(url, data=payload)

    if response.status_code != 200:
        _raise_meta_graph_error(
            response,
            context="campaign creation",
        )

    return response.json()["id"]



async def _create_boost_adset(
    client: httpx.AsyncClient,
    request: meta_boost_schema.CommonBoostAdRequest,
    campaign_id: str,
    access_token: str,
) -> str:

    url = (
        f"{META_BOOST_API_BASE_URL}/"
        f"act_{request.ad_account_id}/adsets"
    )

    payload = _build_boost_adset_payload(
        request,
        campaign_id,
        access_token,
    )

    response = await client.post(url, data=payload)

    if response.status_code != 200:
        _raise_meta_graph_error(
            response,
            context="ad set creation",
        )

    return response.json()["id"]



async def _create_facebook_post_creative(
    client: httpx.AsyncClient,
    request: meta_boost_schema.BoostFacebookPostRequest,
    access_token: str,
) -> str:

    url = (
        f"{META_BOOST_API_BASE_URL}/"
        f"act_{request.ad_account_id}/adcreatives"
    )

    payload = {
        "name": request.name,
        "access_token": access_token,
    }
    if request.object_story_spec:
        payload["object_story_spec"] = _build_object_story_spec_payload(
            request.object_story_spec
        )
    else:
        payload["object_story_id"] = request.object_story_id

    response = await client.post(url, data=payload)

    if response.status_code != 200:
        _raise_meta_graph_error(
            response,
            context="Facebook post creative creation",
        )

    return response.json()["id"]



async def _create_instagram_post_creative(
    client: httpx.AsyncClient,
    request: meta_boost_schema.BoostInstagramPostRequest,
    company_id: str,
    db: Session,
    access_token: str,
) -> str:

    url = (
        f"{META_BOOST_API_BASE_URL}/"
        f"act_{request.ad_account_id}/adcreatives"
    )

    page_id, ig_user_id = _resolve_instagram_boost_identities(
        company_id,
        request,
        db,
    )

    payload = {
        "name": request.name,
        "object_id": page_id,
        "instagram_user_id": ig_user_id,
        "source_instagram_media_id": request.source_instagram_media_id,
        "access_token": access_token,
    }

    if request.instagram_call_to_action is not None:
        cta_type = request.instagram_call_to_action.type

        if hasattr(cta_type, "value"):
            cta_type = cta_type.value

        call_to_action = {
            "type": cta_type,
        }

        if request.instagram_call_to_action.link:
            call_to_action["value"] = {
                "link": request.instagram_call_to_action.link,
            }

        payload["call_to_action"] = json.dumps(
            call_to_action
        )

    response = await client.post(url, data=payload)

    if response.status_code != 200:
        _raise_meta_graph_error(
            response,
            context="Instagram post creative creation",
        )

    return response.json()["id"]



async def _create_boost_ad(
    client: httpx.AsyncClient,
    request: meta_boost_schema.CommonBoostAdRequest,
    adset_id: str,
    ad_creative_id: str,
    access_token: str,
) -> str:

    url = (
        f"{META_BOOST_API_BASE_URL}/"
        f"act_{request.ad_account_id}/ads"
    )

    payload = {
        "name": request.name,
        "adset_id": adset_id,
        "creative": json.dumps({
            "creative_id": ad_creative_id,
        }),
        "status": request.status,
        "access_token": access_token,
    }

    if request.engagement_audience:
        payload["engagement_audience"] = request.engagement_audience

    response = await client.post(url, data=payload)

    if response.status_code != 200:
        _raise_meta_graph_error(
            response,
            context="ad creation",
        )

    return response.json()["id"]