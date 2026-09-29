from pydantic import BaseModel, EmailStr, field_validator, Field
from typing import Optional
from datetime import datetime

# Constants
ROLES = ['admin', 'manager', 'member']


class RoleUserCreate(BaseModel):
    """Model for creating a user role entry"""
    company_id: str
    uid: str
    email: EmailStr
    name: str
    role: str


class UserStatusUpdate(BaseModel):
    """Model for updating user status"""
    company_id: str
    user_id: str
    status: str


class UserCreate(BaseModel):
    """Model for creating a new user"""
    email: EmailStr
    name: str
    role: str = 'member'
    profile_image: Optional[str] = None

    @field_validator('role')
    def validate_role(cls, v):
        if v not in ROLES:
            raise ValueError(f'Role must be one of: {", ".join(ROLES)}')
        return v


class InvitationCreate(BaseModel):
    """Model for creating an invitation"""
    email: EmailStr = Field(..., description="Email address of the invitee")
    role: str = Field(..., description="Role to assign (admin, manager, member)")
    company_uuid: str = Field(..., description="UUID of the company")
    inviter_uuid: str = Field(..., description="UUID of the inviter")
    
    @field_validator('role')
    def validate_role(cls, v):
        if v not in ROLES:
            raise ValueError(f'Role must be one of: {", ".join(ROLES)}')
        return v


class UpdateUserCompanyRoleRequest(BaseModel):
    """Platform admin: set a user's role for a company (updates company_users.role_id)."""
    company_id: str = Field(..., description="Company UUID")
    user_uuid: str = Field(..., description="Target user's UUID (users.uuid)")
    role: str = Field(..., description="Role name: admin, manager, or member")

    @field_validator("role")
    def validate_role(cls, v):
        if v not in ROLES:
            raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        return v


class AcceptInviteRequest(BaseModel):
    """Request body for accepting an invitation"""
    token: str = Field(..., description="Invitation token from the invite link")


class InvitationResponse(BaseModel):
    """Model for invitation response"""
    id: str
    email: str
    role: str
    status: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    inviter_name: str
    company_name: str
    accepted_at: Optional[datetime] = None
