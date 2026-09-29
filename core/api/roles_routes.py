from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import os
import uuid as uuid_lib

from sqlalchemy.orm import Session
from sqlalchemy import func

from shared.database.postgres.database_config import get_db
from shared.utils.error import error_handler, error
from shared.utils.email.email_service import send_email
from shared.utils.email.roles_email_utils import get_invitation_email_template
from shared.logger.log import setup_logger
from shared.utils.auth.auth import get_current_user, GUEST_USER_UID, STATIC_ADMIN_UID
from shared.utils.auth import auth

from core.schema.roles_schema import (
    InvitationCreate,
    AcceptInviteRequest,
)
from core.tables import user_tables, company_tables, invitation_tables

router = APIRouter()

logger = setup_logger("marketing-app")

# Helper to get role of current user in current company
def get_user_role_in_company(user_id: int, company_uuid: str, db: Session) -> Optional[str]:
    if not company_uuid:
        return None
    
    # Get company ID from UUID
    company = db.query(company_tables.Company).filter(company_tables.Company.uuid == company_uuid).first()
    if not company:
        return None
        
    company_user = db.query(company_tables.CompanyUser).filter(
        company_tables.CompanyUser.user_id == user_id,
        company_tables.CompanyUser.company_id == company.id
    ).first()
    
    if company_user and company_user.role:
        return company_user.role.name # Assuming Role model has 'name' field
        
    return None


@router.post("/invite", response_model=Dict[str, Any], status_code=status.HTTP_200_OK)
async def send_invite(
    invitation: InvitationCreate,
    background_tasks: BackgroundTasks,
    user_payload: Dict[str, Any] = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
 ):
    """
    Send an invitation to join the company.
    Required: inviter must have role 'admin' in the specified company.
    """
    try:
        # 1) Resolve Inviter
        inviter = db.query(user_tables.User).filter(user_tables.User.uuid == invitation.inviter_uuid).first()
        if not inviter:
            raise error.NotFound(message="Inviter not found")

        # 2) Resolve Company
        company = db.query(company_tables.Company).filter(company_tables.Company.uuid == invitation.company_uuid).first()
        if not company:
            raise error.NotFound(message="Company not found")

        # 3) Verify inviter is admin in this company
        caller_membership = db.query(company_tables.CompanyUser).join(user_tables.Role).filter(
            company_tables.CompanyUser.company_id == company.id,
            company_tables.CompanyUser.user_id == inviter.id
        ).first()

        if not caller_membership or not caller_membership.role or caller_membership.role.name != "admin":
             raise error.Forbidden(message="Only company admins can invite users to this company")

        # 4) Reject only if this email is already a member of THIS company.
        # (If the email exists in DB for a different company, we allow the invite.)
        existing_user = db.query(user_tables.User).filter(user_tables.User.email == invitation.email.lower()).first()
        if existing_user:
            is_member = db.query(company_tables.CompanyUser).filter(
                company_tables.CompanyUser.user_id == existing_user.id,
                company_tables.CompanyUser.company_id == company.id
            ).first()
            if is_member:
                raise error.BadRequest(message="User is already a member of this company")

        # 5) Create Invitation
        token = uuid_lib.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        # 6) Verify role is valid
        role_record = db.query(user_tables.Role).filter(user_tables.Role.name == invitation.role).first()
        if not role_record:
            raise error.BadRequest(message=f"Invalid role: {invitation.role}")
        
        new_invite = invitation_tables.Invitation(
            token=token,
            email=invitation.email.lower(),
            role_id=role_record.id,
            status="pending",
            company_id=company.id,
            inviter_id=inviter.id,
            expires_at=expires_at,
            email_status="pending"
        )
        
        db.add(new_invite)
        db.commit()
        db.refresh(new_invite)

        # 6) Send Email
        invite_url = f"{os.getenv('FRONTEND_URL', 'apps.holdflight.se')}/accept-invite?token={token}"
        logger.info(f"Invitation URL: {invite_url}")
        
        subject, html_content, text_content = get_invitation_email_template(
            inviter_name=inviter.name or "Admin",
            company_name=company.company_name,
            invite_url=invite_url,
            company_logo=company.logo_url,
        )

        try:
            await send_email(
                to_email=invitation.email.lower(),
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                company_id=company.id,
            )
            new_invite.email_status = "sent"
            new_invite.email_sent_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            new_invite.email_status = "failed"
            db.commit()
            try:
                
                error_handler.record_integration_error(
                    db=db,
                    company_id=company.id,
                    status="email_webhook",
                    error_message=f"Invitation email send failed to {invitation.email}. Error: {str(e)}",
                    status_code=500
                )
            except Exception as db_err:
                logger.error(f"Failed to record invitation email error to db: {db_err}")

        return {
            "success": True,
            "message": "Invitation sent successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise error.InternalServerError(message="An unexpected error occurred")


@router.get("/invitations", response_model=Dict[str, Any])
async def list_invitations(
    company_uuid: str = Query(..., description="Company UUID to list invitations for"),
    user_payload: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
 ):
    """List all invitations for the company (pending and accepted). Admins see all; non-admins get 200 with message and empty data."""
    firebase_uid = user_payload.get("uid")
    current_user = db.query(user_tables.User).filter(user_tables.User.firebase_uid == firebase_uid).first()
    if not current_user:
        raise error.NotFound(message="User not found")

    company = db.query(company_tables.Company).filter(company_tables.Company.uuid == company_uuid).first()
    if not company:
        raise error.NotFound(message="Company not found")

    caller_membership = db.query(company_tables.CompanyUser).join(user_tables.Role).filter(
        company_tables.CompanyUser.company_id == company.id,
        company_tables.CompanyUser.user_id == current_user.id
    ).first()
    is_admin = caller_membership and caller_membership.role and caller_membership.role.name == "admin"
    if not is_admin:
        return {"message": "Only admins can list the invitations", "data": []}

    # All invitations for this company (pending and accepted)
    invitations = (
        db.query(invitation_tables.Invitation, user_tables.Role)
        .join(user_tables.Role, invitation_tables.Invitation.role_id == user_tables.Role.id)
        .filter(invitation_tables.Invitation.company_id == company.id)
        .order_by(invitation_tables.Invitation.created_at.desc())
        .all()
    )

    response = []
    for inv, role in invitations:
        inviter_name = (inv.inviter.name if inv.inviter else None) or "Unknown"
        company_name = (inv.company.company_name if inv.company else None) or ""
        response.append({
            "id": str(inv.id),
            "email": inv.email,
            "role": role.name,
            "status": inv.status,
            "created_at": inv.created_at,
            "expires_at": inv.expires_at,
            "inviter_name": inviter_name,
            "company_name": company_name,
            "accepted_at": inv.accepted_at,
        })
    return {"message": None, "data": response}


@router.get("/invitations/pending", response_model=Dict[str, Any])
async def list_pending_invitations(
    company_uuid: str = Query(..., description="Company UUID to list pending invitations for"),
    user_payload: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
 ):
    """
    List all pending invitations for the given company. Admins see the list; non-admins get 200 with message and empty data.
    """
    firebase_uid = user_payload.get("uid")
    current_user = db.query(user_tables.User).filter(user_tables.User.firebase_uid == firebase_uid).first()
    if not current_user:
        raise error.NotFound(message="User not found")

    company = db.query(company_tables.Company).filter(company_tables.Company.uuid == company_uuid).first()
    if not company:
        raise error.NotFound(message="Company not found")

    caller_membership = db.query(company_tables.CompanyUser).join(user_tables.Role).filter(
        company_tables.CompanyUser.company_id == company.id,
        company_tables.CompanyUser.user_id == current_user.id
    ).first()
    is_admin = caller_membership and getattr(caller_membership.role, "name", "") == "admin"
    if not is_admin:
        return {"message": "Only admins can list the invitations", "data": []}

    invitations = (
        db.query(invitation_tables.Invitation, user_tables.Role)
        .join(user_tables.Role, invitation_tables.Invitation.role_id == user_tables.Role.id)
        .filter(invitation_tables.Invitation.company_id == company.id, invitation_tables.Invitation.status == "pending")
        .order_by(invitation_tables.Invitation.created_at.desc())
        .all()
    )

    result = []
    for inv, role in invitations:
        inviter_name = (inv.inviter.name if inv.inviter else None) or "Unknown"
        inv_dict = {
            "id": str(inv.id),
            "token": inv.token,
            "email": inv.email,
            "role":  role.name,
            "status": inv.status,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "inviter_name": inviter_name,
            "email_status": inv.email_status,
        }
        result.append(inv_dict)

    return {"message": None, "data": result}


@router.post("/invitations/{invite_id}/resend", status_code=status.HTTP_200_OK)
async def resend_invitation(
    invite_id: str,
    user_payload: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
 ):
    """
    Resend an invitation email. Admin of the invitation's company only.
    """
    firebase_uid = user_payload.get("uid")
    current_user = db.query(user_tables.User).filter(user_tables.User.firebase_uid == firebase_uid).first()
    if not current_user:
        raise error.NotFound(message="User not found")

    # Find invite by token or numeric ID
    invite = db.query(invitation_tables.Invitation).filter(invitation_tables.Invitation.token == invite_id).first()
    if not invite and invite_id.isdigit():
        invite = db.query(invitation_tables.Invitation).filter(invitation_tables.Invitation.id == int(invite_id)).first()
    if not invite:
        raise error.NotFound(message="Invitation not found")

    company = db.query(company_tables.Company).filter(company_tables.Company.id == invite.company_id).first()
    if not company:
        raise error.NotFound(message="Company not found")

    caller_membership = db.query(company_tables.CompanyUser).join(user_tables.Role).filter(
        company_tables.CompanyUser.company_id == company.id,
        company_tables.CompanyUser.user_id == current_user.id
    ).first()
    if not caller_membership or getattr(caller_membership.role, 'name', '') != "admin":
        raise error.Forbidden(message="Only admins can resend invitations")

    # Update
    invite.status = "pending"
    invite.email_status = "resending"
    invite.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    db.commit()

    # Send email
    invite_url = f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/accept-invite?token={invite.token}"
    logger.info(f"Resend invitation URL: {invite_url}")
    
    subject, html_content, text_content = get_invitation_email_template(
        inviter_name=current_user.name or "Admin",
        company_name=company.company_name,
        invite_url=invite_url,
        company_logo=company.logo_url,
    )

    try:
        await send_email(
            to_email=invite.email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            company_id=invite.company_id,
        )
        invite.email_status = "resent"
        invite.email_sent_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "success", "message": "Invitation resent successfully"}
    except Exception as e:
        logger.error(f"Error resending: {e}")
        invite.email_status = "failed"
        db.commit()
        try:
            
            error_handler.record_integration_error(
                db=db,
                company_id=invite.company_id,
                status="email_webhook",
                error_message=f"Resend invitation email failed to {invite.email}. Error: {str(e)}",
                status_code=500
            )
        except Exception as db_err:
            logger.error(f"Failed to record invitation email error to db: {db_err}")
        raise error.InternalServerError(message="Failed to resend email")


@router.post("/accept-invite", response_model=Dict[str, Any])
async def accept_invite(
    body: AcceptInviteRequest,
    user_payload: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
 ):
    """
    Accept an invitation to join a company. Adds the logged-in user to the
    company they were invited to, with the role from the invitation.
    """
    token = body.token
    firebase_uid = user_payload.get("uid")
    current_user = db.query(user_tables.User).filter(user_tables.User.firebase_uid == firebase_uid).first()
    if not current_user:
        raise error.NotFound(message="User not found in database")

    # 1) Get invitation
    invite = db.query(invitation_tables.Invitation).filter(invitation_tables.Invitation.token == token).first()
    if not invite:
        raise error.NotFound(message="Invitation not found")

    if invite.status == "accepted":
        raise error.BadRequest(message="Already accepted")

    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        raise error.BadRequest(message="Invitation expired")

    # Only the invited email can accept (same account)
    if current_user.email and current_user.email.lower() != invite.email.lower():
        raise error.Forbidden(message="This invitation was sent to a different email address. Please sign in with the invited account.")

    # 2) Find Company
    company = db.query(company_tables.Company).filter(company_tables.Company.id == invite.company_id).first()
    if not company:
        raise error.NotFound(message="Company referenced in invitation not found")

    user_id = current_user.id

    # Check if already member (e.g. re-accepting or duplicate)
    existing_member = db.query(company_tables.CompanyUser).filter(
        company_tables.CompanyUser.company_id == company.id,
        company_tables.CompanyUser.user_id == user_id
    ).first()

    target_role_id = invite.role_id
    role_obj = db.query(user_tables.Role).filter(user_tables.Role.id == target_role_id).first()
    if not role_obj:
        role_obj = db.query(user_tables.Role).filter(user_tables.Role.name == "member").first()
        if not role_obj:
            raise error.InternalServerError(message="Role configuration error")

    if not existing_member:
        # Add user to the company they were invited to, with the invited role
        new_membership = company_tables.CompanyUser(
            company_id=company.id,
            user_id=user_id,
            role_id=role_obj.id
        )
        db.add(new_membership)
    else:
        # Already a member: update role to the invited role
        existing_member.role_id = role_obj.id

    # 4) Mark invitation accepted
    invite.status = "accepted"
    invite.accepted_at = datetime.now(timezone.utc)
    invite.accepted_by_id = user_id

    db.flush()  # force UPDATE to be sent to DB (session has autoflush=False)
    db.commit()

    return {
        "status": "success",
        "message": "Successfully joined the company",
        "data": {
            "company_id": str(company.uuid),
            "company_name": company.company_name,
            "role": role_obj.name,
            "invitation_status": invite.status,
            "accepted_at": invite.accepted_at.isoformat() if invite.accepted_at else None,
        }
    }


@router.get("/me", response_model=Dict[str, Any])
async def get_current_user_info(user_payload: Dict[str, Any] = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user info with role."""
    firebase_uid = user_payload.get("uid")
    current_user = db.query(user_tables.User).filter(user_tables.User.firebase_uid == firebase_uid).first()
    if not current_user:
        raise error.NotFound(message="User not found")

    user_dict = {
        "uuid": str(current_user.uuid),
        "uid": firebase_uid,
        "email": current_user.email,
        "name": current_user.name,
        "profile_image": current_user.profile_image,
        "is_fully_approved": current_user.is_fully_approved,
        "has_created_company": current_user.has_created_company,
        "onboarding_pending": (
            current_user.has_created_company and not current_user.is_fully_approved
        ),
    }

    first_membership = db.query(company_tables.CompanyUser).filter(company_tables.CompanyUser.user_id == current_user.id).first()
    if first_membership:
        company = db.query(company_tables.Company).filter(company_tables.Company.id == first_membership.company_id).first()
        if company:
            user_dict["companyId"] = str(company.uuid)
            user_dict["companyRole"] = first_membership.role.name if first_membership.role else None
    
    return user_dict


@router.get("/users", response_model=List[Dict[str, Any]])
async def list_company_users(
    user_payload: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
 ):
    """List all users in the company (admin only)."""
    firebase_uid = user_payload.get("uid")
    current_user = db.query(user_tables.User).filter(user_tables.User.firebase_uid == firebase_uid).first()
    if not current_user:
        raise error.NotFound(message="User not found")

    first_membership = db.query(company_tables.CompanyUser).filter(company_tables.CompanyUser.user_id == current_user.id).first()
    if not first_membership:
        raise error.BadRequest(message="No company context")

    company = db.query(company_tables.Company).filter(company_tables.Company.id == first_membership.company_id).first()
    if not company:
        raise error.NotFound(message="Company not found")

    # Verify admin
    caller_role = get_user_role_in_company(current_user.id, str(company.uuid), db)
    if caller_role != "admin":
         raise error.Forbidden(message="Only admins can list users")

    # List users
    company_users = db.query(company_tables.CompanyUser).filter(company_tables.CompanyUser.company_id == company.id).all()
    
    result = []
    for cu in company_users:
        if cu.user: # user relationship valid
             u = cu.user
             result.append({
                 "uid": str(u.uuid),
                 "email": u.email,
                 "name": u.name,
                 "role": cu.role.name if cu.role else None,
                 "joined_at": cu.created_at.isoformat() if cu.created_at else None
             })
             
    return result


@router.get("/companies/users", response_model=List[Dict[str, Any]])
async def list_company_users_with_roles(
    company_id: str = Query(..., description="Company UUID"),
    user_id: str = Query(..., description="User ID (UUID or Firebase UID) of requester"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
 ):
    """
    List all users in a company with their roles. admin only.
    """
    if user.get("uid") != GUEST_USER_UID and user.get("uid") != STATIC_ADMIN_UID:
        user_record = db.query(user_tables.User).filter(user_tables.User.firebase_uid == user["uid"]).first()
        if not user_record:
            raise error.NotFound(message="User not found")
        if not user_record.is_admin:
            raise error.Forbidden(message="You are not authorized to access this resource")

        
    # 1) Resolve Company
    company = db.query(company_tables.Company).filter(company_tables.Company.uuid == company_id).first()
    if not company:
         raise error.NotFound(message="Company not found")

    # 2) Resolve Requester
    requester = db.query(user_tables.User).filter(user_tables.User.uuid == user_id).first()
    if not requester:
        requester = db.query(user_tables.User).filter(user_tables.User.firebase_uid == user_id).first()
    
    if not requester:
         raise error.NotFound(message="Requester user not found")

    # 3) Check Admin
    req_role = get_user_role_in_company(requester.id, str(company.uuid), db)
    if req_role != "admin":
        raise error.Forbidden(message="Only admins can view users")

    # 4) List users
    company_users = db.query(company_tables.CompanyUser).filter(company_tables.CompanyUser.company_id == company.id).all()
    
    result_users = []
    for cu in company_users:
        # Skip requester? User asked to "excluding the requesting admin"
        if cu.user_id == requester.id:
            continue
            
        u = cu.user
        if not u:
            continue
            
        result_users.append({
            "email": u.email,
            "name": u.name,
            "role": cu.role.name if cu.role else None,
            "status": "active" if u.is_active else "inactive",
            "joinedAt": cu.created_at.isoformat() if cu.created_at else None
        })
        
    return result_users
