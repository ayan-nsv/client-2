from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.database.postgres.database_config import get_db
from shared.utils.auth import auth
from products.market_planner.schema import blog_schema
from products.market_planner.services.blog_service import BlogService



# logger = setup_logger("marketing-app")

router = APIRouter()

@router.post("/blog/{company_id}/generate", tags=["blog"])
async def create_blog(request: blog_schema.BlogRequest, company_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = BlogService(db)
    return service.create_blog(request.model_dump_json(), company_id, user)
    

@router.post("/blog/{company_id}/save", tags=["blog"])
async def save_blog(request: blog_schema.BlogSaveRequest, company_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    service = BlogService(db)
    return service.save_blog(request.model_dump_json(), company_id, user)
    
    

@router.get("/blogs/{company_id}", tags=["blog"])
async def get_blogs_by_company_id(
    company_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)
    ):
    """
    Return all blogs generated for a given company_id.
    """
    service = BlogService(db)
    return service.get_blogs_by_company_id(company_id, user)
    
   


@router.get("/blogs/{company_id}/{blog_id}", tags=["blog"])
def get_blog_by_id(
    company_id: str, blog_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)
    ):
    
    service = BlogService(db)
    return service.get_blog_by_id(company_id, blog_id, user)
    



@router.put("/blogs/{company_id}/{blog_id}/schedule", tags=["blog"])
async def update_blog(
    company_id: str,
    blog_id: str,
    payload: blog_schema.BlogSaveRequest,
    user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)
    ):
    
    service = BlogService(db)
    return service.update_blog(company_id, blog_id, payload.model_dump_json(), user)
    

@router.delete("/blogs/{company_id}/{blog_id}", tags=["blog"])
async def delete_blog(
    company_id: str, blog_id: str, user: dict = Depends(auth.get_current_user), db: Session = Depends(get_db)
    ):
    
    service = BlogService(db)
    return service.delete_blog(company_id, blog_id, user)
    