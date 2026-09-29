from fastapi import Depends, BackgroundTasks, Request,APIRouter, Query
from sqlalchemy.orm import Session
from typing import Optional




########################
from products.market_planner.services.content_service import ContentService
from shared.utils.auth import auth
from shared.database.postgres.database_config import get_db
from products.market_planner.schema import content_schema




router = APIRouter(dependencies=[Depends(auth.get_current_user)])


@router.post("/content/{company_id}/generate/instagram", tags=["Instagram content"])
async def generate_image_instagram(request: content_schema.ContentRequest, company_id: str, db: Session= Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.generate_social_image(company_id, request.model_dump_json(), "instagram", user)
    

## generate posts for facebook
@router.post("/content/{company_id}/generate/facebook", tags=["Facebook content"])
async def generate_image_facebook(request: content_schema.ContentRequest, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.generate_social_image(company_id, request.model_dump_json(), "facebook", user)
    
## generate posts for linkedin
@router.post("/content/{company_id}/generate/linkedin", tags=["LinkedIn content"])
async def generate_image_linkedin(request: content_schema.ContentRequest, company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.generate_social_image(company_id, request.model_dump_json(), "linkedin", user)

        


@router.post("/content/{company_id}/regenerate/image", tags=["Image regenerate"])
async def regenerate_image(
    request: Request,
    company_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user)
 ):
    service = ContentService(db)
    return await service.regenerate_image(company_id, request.model_dump_json(), user)
    


@router.post("/content/{company_id}/edit/image", tags=["Image edit"])
async def edit_image(
    payload: content_schema.EditImageRequest,
    company_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
 ):
    """
    Edit a not-yet-saved generated image using a free-form user instruction.

    The image is identified by the Firebase `image_url` returned from the
    /generate or /regenerate endpoints. The user's `edit_instruction` is
    applied as an override on top of that image (e.g. "only two people, one
    trainer and one trainee, snowy outside"). Style, lighting and composition
    from the original image are preserved unless the instruction explicitly
    changes them.

    The edited image is uploaded to Firebase and the new `image_url` is
    returned so the frontend can swap the preview. Nothing is persisted to
    the posts table — the caller saves the chosen image via the existing
    save flow.
    """
    service = ContentService(db)
    return await service.edit_image(company_id, payload.model_dump_json(), user)



###################################################### Get posts ###################################################



@router.get("/content/{company_id}/instagram/post/{post_id}", tags=["Instagram content"])
async def get_instagram_post(company_id: str, post_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.get_instagram_post(company_id, post_id, user)
    

@router.get("/content/{company_id}/facebook/post/{post_id}", tags=["Facebook content"])
async def get_facebook_post(company_id: str, post_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.get_facebook_post(company_id, post_id, user)
    

@router.get("/content/{company_id}/linkedin/post/{post_id}", tags=["LinkedIn content"])
async def get_linkedin_post(company_id: str, post_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.get_linkedin_post(company_id, post_id, user)
        
# #########################################################################################################################

###################################################### get posts with variation and theme index ##################################################
@router.get("/content/{company_id}/variation/{theme_index}", tags=["Post variation"])
def get_social_media_posts_with_theme_index(company_id: str, month_id: int, channel: str, theme_index: int, db: Session = Depends(get_db)):
    service = ContentService(db)
    return service.get_social_media_posts_with_theme_index(company_id, month_id, channel, theme_index)
    

###################################################################################################################################

@router.get("/content/{company_id}/instagram/posts", tags=["Instagram content"])
async def get_all_instagram_posts(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.get_all_instagram_posts(company_id, user)
    
@router.get("/content/{company_id}/facebook/posts", tags=["Facebook content"])
async def get_all_facebook_posts(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.get_all_facebook_posts(company_id, user)
    

@router.get("/content/{company_id}/linkedin/posts", tags=["LinkedIn content"])
async def get_all_linkedin_posts(company_id: str, db: Session = Depends(get_db), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.get_all_linkedin_posts(company_id, user)


#########################################################################################################

@router.post("/content/{company_id}/schedule/create", tags=["Scheduled posts"])
async def create_scheduled_posts(company_id: str, request: content_schema.SchedularRequest, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    # The service calls .model_dump() on this, so it needs the model rather than JSON.
    return await service.create_scheduled_posts(company_id, request, background_task, user)    
    

############################################### post save route ######################################################
@router.post("/content/{company_id}/instagram/save", tags=["Instagram content"])
async def save_instagram_post_to_db(company_id: str, content: content_schema.ContentSaveRequest, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.save_social_post_to_db(company_id, content.model_dump_json(), "instagram", background_task, user)


@router.post("/content/{company_id}/facebook/save", tags=["Facebook content"])
async def save_facebook_post_to_db(company_id: str, content: content_schema.ContentSaveRequest, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.save_social_post_to_db(company_id, content.model_dump_json(), "facebook", background_task, user)
    


@router.post("/content/{company_id}/linkedin/save", tags=["LinkedIn content"])
async def save_linkedin_post_to_db(company_id: str, content: content_schema.ContentSaveRequest, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.save_social_post_to_db(company_id, content.model_dump_json(), "linkedin", background_task, user)


############################################# update post ###########################################
@router.put("/content/{company_id}/instagram/posts/{post_id}", tags=["Instagram content"])
async def update_instagram_post(company_id: str, post_id: str, content: content_schema.ContentSaveRequest, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.update_social_post_to_db(company_id, post_id, content.model_dump_json(), "instagram", background_task, user)
    

@router.put("/content/{company_id}/facebook/posts/{post_id}", tags=["Facebook content"])
async def update_facebook_post(company_id: str, post_id: str, content: content_schema.ContentSaveRequest, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.update_social_post_to_db(company_id, post_id, content.model_dump_json(), "facebook", background_task, user)
    
@router.put("/content/{company_id}/linkedin/posts/{post_id}", tags=["LinkedIn content"])
async def update_linkedin_post(company_id: str, post_id: str, content: content_schema.ContentSaveRequest, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.update_social_post_to_db(company_id, post_id, content.model_dump_json(), "linkedin", background_task, user)
        


############################################# delete post ###########################################
@router.delete("/content/{company_id}/instagram/posts/{post_id}", tags=["Instagram content"])
async def delete_instagram_post(company_id: str, post_id: str, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.delete_social_post(company_id, post_id, "instagram", background_task, user)

@router.delete("/content/{company_id}/facebook/posts/{post_id}", tags=["Facebook content"])
async def delete_facebook_post(company_id: str, post_id: str, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
   service = ContentService(db)
   return await service.delete_social_post(company_id, post_id, "facebook", background_task, user)

@router.delete("/content/{company_id}/linkedin/posts/{post_id}", tags=["LinkedIn content"])
async def delete_linkedin_post(company_id: str, post_id: str, db: Session = Depends(get_db), background_task: BackgroundTasks = BackgroundTasks(), user: dict = Depends(auth.get_current_user)):
    service = ContentService(db)
    return await service.delete_social_post(company_id, post_id, "linkedin", background_task, user)
    

@router.post(
    "/content/{company_id}/generate/posts/products",
    tags=["Product posts"],
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "product_image_file": {"type": "string", "format": "binary", "description": "First product image file"},
                            "product_image_url": {"type": "string", "description": "URL of first product image (alternative to file)"},
                            "product_image_file_2": {"type": "string", "format": "binary", "description": "Optional second product image file"},
                            "product_image_url_2": {"type": "string", "description": "Optional URL of second product image"},
                        },
                    }
                }
            }
        }
    },
)


async def generate_posts_from_products(
    request: Request,
    company_id: str,
    channel: str = Query(..., description="Social channel (e.g. instagram)"),
    month_id: Optional[int] = Query(None),
    aspect_ratio: str = Query("square", description="Aspect ratio: square (1:1), landscape (16:9), or portrait (9:16)"),
    db: Session = Depends(get_db),
    user: dict = Depends(auth.get_current_user),
 ) -> content_schema.GeneratePostsFromProductsResponse:
    """
    Generate one social post image WITH the product image(s) embedded using Gemini.
    Accept one or two product images (file or URL per slot). If two reference images show
    different products, both should appear clearly in the generated post image.
    Returns caption, hashtags, and one Firebase image URL.
    """
    service = ContentService(db)
    return await service.generate_posts_from_products(company_id, channel,request.model_dump_json(), month_id, aspect_ratio, user)
    