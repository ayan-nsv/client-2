from fastapi import APIRouter, HTTPException
from products.market_planner.tables.content_tables import  Post
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import logging


from shared.cache.redis import redis
from shared.utils.error import error_handler, error
from shared.logger.schema import log_schema
from shared.logger.log import setup_logger

from core.repository.company_repo import CompanyRepository
from products.market_planner.social_media.meta.facebook.schemas import facebook_schema
from products.market_planner.social_media.meta.instagram.schema import instagram_schema
from products.market_planner.social_media.linkedin.services.linkedin_service import LinkedInService
from products.market_planner.social_media.meta.facebook.services.facebook_service import FacebookService
from products.market_planner.social_media.meta.instagram.services.instagram_service import InstagramService



#############################################  postgres database imports ###########################################

from sqlalchemy.orm import Session
#############################################  end of postgres database imports ##############################

router = APIRouter()



logger = setup_logger("marketing-app")


def _log_publish_failure(db: Session, company_id_int: int, channel: str, post_id, exc: Exception):
    try:
        cu = str(CompanyRepository(db).get_company_uuid_from_id(company_id_int))
    except Exception:
        cu = None
        error_handler.record_log(
            log_schema.LogRequest(
                company_id=cu,
                severity="error",
                message=f"process_posts {channel} post {post_id}: {str(exc)[:100]}",
                status="error",
                status_code=500,
                timestamp=datetime.now(timezone.utc),
            ),
            db,
        )


async def publish_instagram_post(company_id: int, ig_user_id: str, image_url: str, message: str, db: Session):
    try:
        company_id_str = str(CompanyRepository(db).get_company_uuid_from_id(company_id))
        payload = instagram_schema.PostRequest(
            company_id= company_id_str,
            ig_user_id= ig_user_id,
            image_url= image_url,
            caption= message
        )
        response = InstagramService(db).publish_post(payload.model_dump_json(), db)
        return response.model_dump()
    except Exception as e:
        logger.error(f"Unexpected error publishing Instagram post: {str(e)}")
        _log_publish_failure(db, company_id, "instagram_publish", "n/a", e)
        raise error.InternalServerError(message=f"Error publishing Instagram post: {str(e)}")

async def publish_facebook_post(company_id: int, page_id: str, image_url: str, message: str, db: Session):
    try:
        company_id_str = str(CompanyRepository(db).get_company_uuid_from_id(company_id))
        logger.info(f"Company ID: {company_id_str}")
        payload = facebook_schema.PublishPostRequest(
            company_id= company_id_str,
            id=page_id,
            image_url= image_url,
            message= message,
            target= "page"
        )
        response = FacebookService(db).publish_post(payload.model_dump_json(), db)
        return response.model_dump()
    except Exception as e:
        logger.error(f"Unexpected error publishing Facebook post: {str(e)}")
        _log_publish_failure(db, company_id, "facebook_publish", "n/a", e)
        raise error.InternalServerError(message=f"Error publishing Facebook post: {str(e)}")

async def process_posts(instagram_posts, facebook_posts,linkedin_posts, published_count, failed_count, errors, db):
    pulished_insta_posts_ids = []
    pulished_facebook_posts_ids = []
    pulished_linkedin_posts_ids = []
    published_posts_company_ids = []

    for row in linkedin_posts:
        # Post rows use image_url; media_urls exists on LinkedinPost (history), not on Post.
        media_urls = getattr(row, "media_urls", None)
        if not media_urls:
            img = (getattr(row, "image_url", None) or "").strip()
            if img:
                media_urls = [img]
        caption = str(row.caption) + " " + str(row.hashtags)
        company_id = row.company_id
        try:
            res = LinkedInService(db).publish_post(
                company_id,
                caption,
                media_urls,
            )
            if not isinstance(res, dict) or res.get("status") != "posted":
                raise RuntimeError(res.get("error", "LinkedIn publish did not return posted status"))
            pulished_linkedin_posts_ids.append(row.id)
            published_posts_company_ids.append(company_id)
            # Explicit UPDATE by primary key so DB is updated reliably (avoids session/tracking quirks)
            db.query(Post).filter(Post.id == row.id).update({"status": "published"}, synchronize_session=False)
            db.commit()
            published_count += 1

        except Exception as e:
            failed_count += 1
            _log_publish_failure(db, row.company_id, "linkedin", row.id, e)
            errors.append({
                "post_id": row.id,
                "channel": "linkedin",
                "error": str(e)
            })
           
       
            
    for row in instagram_posts:
        # Index first two columns: supports (Post, ig_user_id) and older queries with extra columns;
        # avoids unpacking Row/tuple length mismatches across SQLAlchemy versions and deploys.
        post, ig_user_id = row[0], row[1]
        try:
            await publish_instagram_post(
                post.company_id,
                ig_user_id,
                post.image_url,
                post.caption,
                db
            )
            pulished_insta_posts_ids.append(post.id)
            published_posts_company_ids.append(post.company_id)
            # Explicit UPDATE by primary key so DB is updated reliably (avoids session/tracking quirks)
            db.query(Post).filter(Post.id == post.id).update({"status": "published"}, synchronize_session=False)
            db.commit()
            published_count += 1
           
        except Exception as e:
            failed_count += 1
            _log_publish_failure(db, post.company_id, "instagram", post.id, e)
            errors.append({
                "post_id": post.id,
                "channel": "instagram",
                "error": str(e)
            })
           

    for row in facebook_posts:
        post, page_id = row[0], row[1]
        try:
            await publish_facebook_post(
                post.company_id,
                page_id,
                post.image_url,
                post.caption,
                db
            )
            pulished_facebook_posts_ids.append(post.id)
            published_posts_company_ids.append(post.company_id)
            # Explicit UPDATE by primary key so DB is updated reliably
            db.query(Post).filter(Post.id == post.id).update({"status": "published"}, synchronize_session=False)
            db.commit()
            published_count += 1
            
        except Exception as e:
            failed_count += 1
            _log_publish_failure(db, post.company_id, "facebook", post.id, e)
            errors.append({
                "post_id": post.id,
                "channel": "facebook",
                "error": str(e)
            })
           
    
    company_uuids = []
    for company_id in published_posts_company_ids:
        company_uuids.append(str(CompanyRepository(db).get_company_uuid_from_id(company_id)))

    for company_uuid in company_uuids:
        await redis.redis_delete(f"all_instagram_posts_{company_uuid}")
        await redis.redis_delete(f"all_facebook_posts_{company_uuid}")
        await redis.redis_delete(f"all_linkedin_posts_{company_uuid}")
    return published_count, failed_count, errors, pulished_insta_posts_ids, pulished_facebook_posts_ids, pulished_linkedin_posts_ids, company_uuids




