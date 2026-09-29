from fastapi import APIRouter, HTTPException, Query, Depends
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session
from dotenv import load_dotenv


from shared.utils.constants import constants
from shared.utils.auth import auth
from shared.utils.error import error
from shared.database.postgres.database_config import get_db
from products.market_planner.social_media.linkedin.services.linkedin_service import LinkedInService
from products.market_planner.social_media.linkedin.configuration import linkedin_config
from products.market_planner.social_media.linkedin.schemas import linkedin_schema

load_dotenv()

router = APIRouter(prefix="/linkedin", tags=["LinkedIn"])





def li_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Linkedin-Version": constants.LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

@router.post("/connect/start")
def connect_start():
    return {"auth_url": constants.LINKEDIN_AUTH_URL}

@router.post("/connect/callback")
def connect_callback(
    code: str = Query(...),
    company_id: str = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user)
 ):
    service = LinkedInService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    token, expires_in = linkedin_config.exchange_code_for_token(code)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    linkedin_client = linkedin_config.LinkedInClient(token)

    # Try to fetch the member profile for a personal account
    saved_accounts = []
    try:
        me = linkedin_client.get_me()
        person_id = me.get("id")
        first_name = me.get("localizedFirstName")
        last_name = me.get("localizedLastName")
        full_name_parts = [first_name, last_name]
        person_name = " ".join([p for p in full_name_parts if p]) if any(full_name_parts) else f"LinkedIn User {person_id}"
        person_urn = f"urn:li:person:{person_id}" if person_id else None
        if person_id and person_urn:
            user_payload = SimpleNamespace(
                company_id=company_id,
                acc_type="linkedin_user",
                access_token=token,
                expires_at=expires_at,
                linkedin_id=person_id,
                author_urn=None,
                display_name=person_name,
                profile_image_url=None,
            )
            user_acc = service.save_account(user_payload, db)
            saved_accounts.append(user_acc)
    except Exception:
        # If /me is not available for these scopes, just skip creating a user account
        pass

    try:
        orgs = linkedin_client.get_organizations()
    except Exception as e:
        raise HTTPException(500, "Could not fetch organizations. Make sure you are an admin of at least one LinkedIn Page.")
    if not orgs:
        raise HTTPException(400, "You need to be an ADMINISTRATOR of at least one LinkedIn Page to use this app.")

    page_rows: list[SimpleNamespace] = []
    for org in orgs:
        org_id = org["organizationalTarget"].replace("urn:li:organization:", "")
        org_urn = org["organizationalTarget"]
        try:
            org_details = linkedin_client.get_organization(org_urn)
            org_name = (
                org_details.get("localizedName")
                or org_details.get("vanityName")
                or f"LinkedIn Page {org_id}"
            )
            logo_url = None
            logo_v2 = org_details.get("logoV2") or {}
            original = logo_v2.get("original~") or {}
            elements = original.get("elements") or []
            for el in elements:
                identifiers = el.get("identifiers") or []
                if identifiers:
                    logo_url = identifiers[0].get("identifier")
                    if logo_url:
                        break
        except Exception:
            org_name = f"LinkedIn Page {org_id}"
            logo_url = None
        page_rows.append(
            SimpleNamespace(
                linkedin_id=org_id,
                author_urn=org_urn,
                display_name=org_name,
                profile_image_url=logo_url,
            )
        )

    first = page_rows[0]
    pages_payload = SimpleNamespace(
        company_id=company_id,
        acc_type="linkedin_page",
        access_token=token,
        expires_at=expires_at,
        linkedin_id=first.linkedin_id,
        author_urn=first.author_urn,
        display_name=first.display_name,
        profile_image_url=first.profile_image_url,
        pages=page_rows,
    )
    saved_account = service.save_account(pages_payload, db)

    if saved_account and saved_account.get("account_type") == "linkedin_page":
        detail = service.get_account(
            company_id, str(saved_account["id"]), db
        )
        if detail and isinstance(detail, dict) and detail.get("pages"):
            account = detail["account"]
            for page in detail["pages"]:
                page_obj = {
                    "id": account["id"],
                    "company_id": company_id,
                    "type": "linkedin_page",
                    "linkedin_id": page.get("linkedin_id"),
                    "author_urn": page.get("author_urn"),
                    "display_name": page.get("display_name"),
                    "profile_image_url": page.get("profile_image_url"),
                    "access_token": account.get("access_token"),
                    "expires_at": account.get("expires_at"),
                    "status": "ok",
                    "created_at": account.get("created_at"),
                    "updated_at": page.get("updated_at"),
                }
                saved_accounts.append(page_obj)
    
    # Mask sensitive data in response
    masked_accounts = []
    for acc in saved_accounts:
        masked_acc = acc.copy()
        if "access_token" in masked_acc:
            masked_acc["access_token"] = "********"
        if "author_urn" in masked_acc:
            masked_acc["author_urn"] = "********"
        masked_accounts.append(masked_acc)
    
    return {"status": "connected", "accounts": masked_accounts}

@router.get("/callback")
def linkedin_callback_from_browser(
    code: str,
    state: str = None,
    company_id: str = "default_company",
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user)
 ):

    service = LinkedInService(db)
    # only authorized users can access this endpoint
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise HTTPException(status_code=403, detail=f"User does not have access to this company {company_id}")

    try:


        token, expires_in = linkedin_config.exchange_code_for_token(code)
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)
        linkedin_client = linkedin_config.LinkedInClient(token)

        # -------------------------
        # 🔹 Try USER first
        # -------------------------
        try:
            me = linkedin_client.get_me()
            person_id = me.get("id")
            first_name = me.get("localizedFirstName")
            last_name = me.get("localizedLastName")

            person_name = " ".join([p for p in [first_name, last_name] if p]) \
                if any([first_name, last_name]) else f"LinkedIn User {person_id}"

            person_urn = f"urn:li:person:{person_id}" if person_id else None

            if person_id and person_urn:
                user_payload = {
                    "company_id": company_id,
                    "acc_type": "linkedin_user",
                    "access_token": token,
                    "expires_at": expires_at,
                    "linkedin_id": person_id,
                    "author_urn": person_urn,
                    "display_name": person_name,
                    "profile_image_url": None,
                }

                service.save_account(user_payload)

                return {
                    "status": "✅ LinkedIn User Connected Successfully!",
                    "account": {
                        "acc_type": "linkedin_user",
                        "linkedin_id": person_id,
                        "display_name": person_name,
                        "access_token": "********",
                        "author_urn": "********",
                        "status": "ok",
                    }
                }

        except Exception:
            pass

        # -------------------------
        # 🔹 Otherwise try PAGES
        # -------------------------
        orgs = linkedin_client.get_organizations()

        if not orgs:
            return {
                "status": "❌ No Organizations Found",
                "message": "You need to be an ADMINISTRATOR of at least one LinkedIn Page to use this app."
            }

        pages = []

        for org in orgs:
            org_id = org["organizationalTarget"].replace("urn:li:organization:", "")
            org_urn = org["organizationalTarget"]

            try:
                org_details = linkedin_client.get_organization(org_urn)
                org_name = (
                    org_details.get("localizedName")
                    or org_details.get("vanityName")
                    or f"LinkedIn Page {org_id}"
                )
            except Exception:
                org_name = f"LinkedIn Page {org_id}"

            pages.append({
                "linkedin_id": org_id,
                "author_urn": org_urn,
                "display_name": org_name,
                "profile_image_url": None,
                "updated_at": datetime.datetime.utcnow(),
            })

        linkedin_pages_payload = {
            "company_id": company_id,
            "acc_type": "linkedin_pages",
            "access_token": token,
            "expires_at": expires_at,
            "pages": pages
        }

        service.save_account(linkedin_pages_payload)

        return {
            "status": "✅ LinkedIn Pages Connected Successfully!",
            "accounts": [
                {
                    "acc_type": "linkedin_page",
                    "linkedin_id": page.get("linkedin_id"),
                    "display_name": page.get("display_name"),
                    "access_token": "********",
                    "author_urn": "********",
                    "status": "ok",
                }
                for page in pages
            ]
        }

    except Exception as e:
        return {
            "status": "❌ Error",
            "error": str(e),
            "code": code,
            "message": "Connection failed. Check server logs for details."
        }

        
@router.get("/accounts")
def list_accounts(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = LinkedInService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    return service.list_accounts(company_id)


@router.delete("/logout")
def logout_linkedin(
    company_id: str = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user)
  ):
    service = LinkedInService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    result = service.deactivate_company_accounts(company_id)
    return result




@router.post("/posts")
def create_post(payload: linkedin_schema.PostCreateRequest, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = LinkedInService(db)
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(payload.company_id, user["uid"], db)
    if not company_id_int:
        raise HTTPException(status_code=403, detail=f"User does not have access to this company {payload.company_id}")

    res = service.publish_post(company_id_int, payload.caption, payload.media_urls)
    # Check if publish_post returned an error
    if "error" in res or res.get("status") == "ERROR":
        return {"status": "ERROR", "response": res}
    else:
        return {"status": "posted", "response": res}
 
@router.get("/posts/{post_id}")
def get_post(post_id: str, company_id: str = Query(...), db: Session = Depends(get_db)):
    service = LinkedInService(db)
    post = service.get_post(company_id, post_id)
    if not post:
        raise error.NotFound("Post not found")
    return post

@router.get("/all-posts")
def list_posts(company_id: str = Query(...), db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = LinkedInService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    """Fetch all LinkedIn posts for a company."""
    return service.list_posts(company_id)


@router.post("/account/select")
def select_page(page_id: str, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = LinkedInService(db)
    
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    return service.select_page(page_id,company_id)

@router.get("/connected-page")
def get_connected_page(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = LinkedInService(db)
    # only authorized users can access this endpoint
    if not user:
        raise error.PermissionDenied("Unauthorized")

    company_id_int = auth.check_user_company_access(company_id, user["uid"], db)
    if not company_id_int:
        raise error.PermissionDenied(f"User does not have access to this company {company_id}")

    return service.get_connected_page(company_id)

