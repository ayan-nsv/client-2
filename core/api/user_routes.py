
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.logger.log import setup_logger
from shared.database.postgres.database_config import get_db
from shared.utils.auth import auth

from core.services.user_service import UserService
from core.schema import user_schema

logger = setup_logger("marketing-app")

router = APIRouter()
admin_router = APIRouter()

@router.get("/users", tags=["user"])
def get_users(user: dict = Depends(auth.get_admin_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.get_users()
    

@router.get("/users/{user_uuid}", tags=["user"])
async def get_user(user_uuid: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.get_user(user_uuid, user)
    

@router.post("/users/role", tags=["user"])
async def get_user_role(
    request: user_schema.RoleRequest,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
    
    service = UserService(db)
    return service.get_user_role(request.company_id, user)

@router.patch("/users/company-role", tags=["user"])
async def update_user_company_role(
    request: user_schema.UpdateUserCompanyRoleRequest,
    user: dict = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
 ):
    service = UserService(db)
    return service.update_user_company_role(request, user)
   

@router.post("/users/companies", tags=["user"])
async def get_user_companies(firebase_uid: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
   service = UserService(db)
   return service.get_user_companies(firebase_uid, user)

@router.post("/users", tags=["user"])
async def create_user(request: user_schema.UserRequest, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.create_user(request, user)
    

@router.post("/users/companies/add", tags=["user"])
async def add_company_users(request: user_schema.AddCompanyUserRequest, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.add_company_users(request, user)


@router.delete("/users/companies/remove", tags=["user"])
async def remove_company_users(request: user_schema.RemoveCompanyUserRequest, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.remove_company_users(request, user)
        

@router.get("/companies/users", tags=["user"])
async def get_company_users(company_uuid: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.get_company_users(company_uuid, user)


@router.put("/users", tags=["user"])
def update_user(request: user_schema.UpdateUserRequest, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.update_user(request, user)
    

@router.post("/user/signup/request", tags=["user"])
async def request_user_signup(request: user_schema.UserSignupRequest, db: Session = Depends(get_db)):
    service = UserService(db)
    return service.request_user_signup(request)
    

@admin_router.get("/pending-users", tags=["user"])
async def get_pending_users(user: dict = Depends(auth.get_admin_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.get_pending_users(user)


@admin_router.post("/pending-users/approve", tags=["user"])
async def approve_pending_users(user_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.approve_pending_users(user_id, user)


@admin_router.delete("/pending-users/reject", tags=["user"])
async def reject_pending_users(user_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = UserService(db)
    return service.reject_pending_users(user_id, user)
    


@admin_router.get("/pending-onboarding")
async def get_pending_onboarding_users(
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
 ):
    service = UserService(db)
    service._require_platform_admin(user)
    return service.get_pending_onboarding_users()



@admin_router.post("/pending-onboarding/approve")
async def approve_pending_onboarding_user(
    user_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
 ):
    
    service = UserService(db)
    service._require_platform_admin(user)
    return service.approve_pending_onboarding_user(user_id)


        