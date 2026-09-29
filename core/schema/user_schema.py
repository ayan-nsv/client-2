import re
from pydantic import BaseModel, Field, field_validator, EmailStr
from typing import Optional, List
from datetime import datetime

ROLES = ['admin', 'manager', 'member']

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


class UserSignupRequest(BaseModel):
    email: EmailStr
    password: str
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")

        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=/\\[\];'`~]", v):
            raise ValueError("Password must contain at least one special character")

        return v 

class UserRequest(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    is_admin: Optional[bool] = False
    is_active: Optional[bool] = True
    profile_image: Optional[str] = None
    joined_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    firebase_uid: Optional[str] = None

class UpdateUserRequest(BaseModel):
    user_id: str
    name: Optional[str] = None
    is_admin: Optional[bool] = False
    is_active: Optional[bool] = True
    profile_image: Optional[str] = None

class RoleRequest(BaseModel):
    company_id: str

class CompanyUserPayload(BaseModel):
    user_id: str
    role_id: Optional[int] = 1

class AddCompanyUserRequest(BaseModel):
    company_id: str
    company_user_payload: List[CompanyUserPayload]
    
class RemoveCompanyUserRequest(BaseModel):
    company_id: str
    users: List[str]
   
