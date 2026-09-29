import json
import asyncio
from datetime import datetime, timezone
from celery import shared_task
from fastapi import HTTPException

from products.market_planner.tables import content_tables
from products.market_planner.tables import channel_tables
from products.market_planner.api import content_routes
from products.market_planner.schema import planner_schema
from products.market_planner.services.content_service import ContentService
from products.market_planner.services.planner_service import PlannerService
from products.market_planner.services.theme_service import ThemeService
from products.market_planner.services import publish_service

from products.market_planner.social_media.meta.instagram.tables import instagram_tables
from products.market_planner.social_media.meta.facebook.tables import facebook_tables
from products.market_planner.social_media.linkedin.tables import linkedin_tables
from products.market_planner.social_media.meta.whatsapp.tables import whatsapp_tables
from products.market_planner.social_media.meta.whatsapp.services import whatsapp_service

from core.repository.company_repo import CompanyRepository
from core.services.usage_service import UsageService

from shared.cache.redis import redis
from shared.database.postgres import serialization
from shared.database.postgres.database_config import get_db
from shared.logger.log import setup_logger
from shared.logger.schema import log_schema
from shared.utils.constants import constants
from shared.utils.error import error_handler

logger = setup_logger("marketing-app")


@shared_task(name="market_planner.publish_scheduled_posts", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def publish_scheduled_posts_task():
    """
    Celery task to publish scheduled posts.
    This task runs the async publish logic from api/publish.py
    """
    logger.info("Starting publish scheduled posts task")
    
    # Create a new database session for this task
    db = next(get_db())
    
    try:
        
        published_count = 0
        failed_count = 0
        errors = []
        
        # Query posts that are scheduled and past their scheduled time
        # Join with channel_tables.ChannelConfig to check if the channel is active for that company
        instagram_posts = db.query(content_tables.Post, instagram_tables.InstagramAccount.ig_user_id).join(
            instagram_tables.InstagramAccount, content_tables.Post.company_id == instagram_tables.InstagramAccount.company_id
        ).filter(
            content_tables.Post.channel == "instagram", 
            content_tables.Post.status == "scheduled",
            content_tables.Post.scheduled_datetime <= datetime.now(timezone.utc),
            instagram_tables.InstagramAccount.status == "ok"
        ).all()
        
        facebook_posts = db.query(content_tables.Post, facebook_tables.FacebookInstaPage.page_id).join(
            facebook_tables.FacebookInstaAccount, content_tables.Post.company_id == facebook_tables.FacebookInstaAccount.company_id
        ).join(
            facebook_tables.FacebookInstaPage,
            facebook_tables.FacebookInstaAccount.id == facebook_tables.FacebookInstaPage.facebook_insta_account_id
        ).filter(
            content_tables.Post.channel == "facebook", 
            content_tables.Post.status == "scheduled",
            content_tables.Post.scheduled_datetime <= datetime.now(timezone.utc),
            facebook_tables.FacebookInstaAccount.user_long_token.isnot(None),
            facebook_tables.FacebookInstaPage.is_selected == True
        ).distinct(content_tables.Post.id).all()

        linkedin_posts = (
            db.query(content_tables.Post)
            .join(linkedin_tables.LinkedinAccount, content_tables.Post.company_id == linkedin_tables.LinkedinAccount.company_id)
            .join(linkedin_tables.LinkedinPage, linkedin_tables.LinkedinAccount.id == linkedin_tables.LinkedinPage.linkedin_account_id)
            .filter(
                content_tables.Post.channel == "linkedin",
                content_tables.Post.status == "scheduled",
                content_tables.Post.scheduled_datetime <= datetime.now(timezone.utc),
                linkedin_tables.LinkedinAccount.status == "ok",
                linkedin_tables.LinkedinPage.is_selected.is_(True),
            )
            .distinct(content_tables.Post.id)
            .all()
        )

        logger.info(
            f"Found {len(instagram_posts)} Instagram, {len(facebook_posts)} Facebook, "
            f"{len(linkedin_posts)} LinkedIn posts to publish"
        )
        
        result = asyncio.run(publish_service.process_posts(instagram_posts, facebook_posts,linkedin_posts, published_count, failed_count, errors, db))
        
        return {
            "total_posts_published": result[0],
            "failed_posts_count": result[1],
            "errors": result[2],
            "pulished_insta_posts_ids": result[3],
            "pulished_facebook_posts_ids": result[4],
            "pulished_linkedin_posts_ids": result[5],
            "status": "completed"
        }
        
    except Exception as e:
        logger.error(f"Error in publish_scheduled_posts_task: {str(e)}")
        ## record the log in the database
        error_handler.record_log(log_schema.LogRequest(severity="critical", message=f"Error in publish_scheduled_posts_task: {str(e)[:100]}", status="error", status_code=500, timestamp=datetime.now(timezone.utc)), db)
        raise
    finally:
        db.close()


@shared_task(name="market_planner.generate_draft_posts", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def generate_draft_posts_task(company_id: str, posts_data: dict, user: dict, company_id_int: int):
    """
    Celery task to generate draft posts.
    This task runs the async generate draft posts logic from api/content_routes.py
    """
    logger.info(f"Starting generate draft posts task for company {company_id}")
    
    # Create a new database session for this task
    db = next(get_db())
    
    try:
        channel_config_record = db.query(channel_tables.ChannelConfig).filter(channel_tables.ChannelConfig.company_id == CompanyRepository(db).get_company_id_from_uuid(company_id, db)).first()
        if not channel_config_record:
            raise HTTPException(status_code=404, detail=f"Channel config not found for company {company_id}")
        channel_config = serialization.sqlalchemy_to_dict(channel_config_record)

        facebook_post_count = channel_config.get('facebook_post_count', 1)
        instagram_post_count = channel_config.get('instagram_post_count', 1)
        linkedin_post_count = channel_config.get('linkedin_post_count', 1)
        newsletter_post_count = channel_config.get('email_campaign_count', 1)
        blog_post_count = channel_config.get('blog_post_count', 1)

        theme = posts_data.get('theme')
        theme_description = posts_data.get('theme_description')
        scheduled_month = posts_data.get('scheduled_month')
        month_id = posts_data.get('month_id')
        theme_index = posts_data.get('theme_index')
        image_type = posts_data.get('image_type')
        
        planner_request = planner_schema.PlannerRequest(
            theme_title=theme,
            theme_description=theme_description,
            image_type=image_type
        )   

        logger.info(
            f"Generating scheduled posts for company {company_id} | "
            f"Instagram: {instagram_post_count}, Facebook: {facebook_post_count}, LinkedIn: {linkedin_post_count}, "
            f"Newsletter: {newsletter_post_count}, Blog: {blog_post_count}"
        )
        logger.debug(
            f"Planner request payload for company {company_id}: "
            f"theme='{theme}', theme_description='{theme_description}', scheduled_month='{scheduled_month}'"
        )


        instagram_task = ContentService(db).generate_channel_posts(
            "instagram", instagram_post_count, company_id, planner_request,
            month_id, theme_index, scheduled_month, db, user,
            PlannerService(db).generate_instagram_planner, content_routes.generate_image_instagram, 
            company_id_int
        )
        
        
        facebook_task = ContentService(db).generate_channel_posts(
            "facebook", facebook_post_count, company_id, planner_request,
            month_id, theme_index, scheduled_month, db, user,
            PlannerService(db).generate_facebook_planner, content_routes.generate_image_facebook,
            company_id_int
        )

        linkedin_task = ContentService(db).generate_channel_posts(
            "linkedin", linkedin_post_count, company_id, planner_request,
            month_id, theme_index, scheduled_month, db, user,
            PlannerService(db).generate_linkedin_planner, content_routes.generate_image_linkedin,
            company_id_int
        )

        newsletter_task = ContentService(db).generate_channel_posts(
            "newsletter", newsletter_post_count, company_id, planner_request, month_id, theme_index, scheduled_month, db, user,
            None, None,
            company_id_int
        )   
        blog_task = ContentService(db).generate_channel_posts(
            "blog", blog_post_count, company_id, planner_request, month_id, theme_index, scheduled_month, db, user,
            None, None,
            company_id_int
        )

        # Run all tasks in parallel and wait for completion
        # Create a new event loop for this thread (required when using thread pool executor)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            insta_posts, fb_posts, linkedin_posts, newsletter_posts, blog_posts = loop.run_until_complete(asyncio.gather(
                instagram_task,
                facebook_task,
                linkedin_task,
                newsletter_task,
                blog_task
            ))

            # Spread posts over month
            loop.run_until_complete(asyncio.gather(
                ContentService(db).spread_posts_over_month(insta_posts, month_id, "instagram", company_id, db),
                ContentService(db).spread_posts_over_month(fb_posts, month_id, "facebook", company_id, db),
                ContentService(db).spread_posts_over_month(linkedin_posts, month_id, "linkedin", company_id, db),
                ContentService(db).spread_posts_over_month(newsletter_posts, month_id, "newsletter", company_id, db),
                ContentService(db).spread_posts_over_month(blog_posts, month_id, "blog", company_id, db),
            ))
        finally:
            loop.close()

        # Combine all post IDs
        all_posts = insta_posts + fb_posts + linkedin_posts + newsletter_posts + blog_posts

        logger.info(f"🎯 Successfully generated {len(all_posts)} total posts for company {company_id}")
        logger.debug(
            f"Post ID summary for company {company_id}: "
            f"instagram={insta_posts}, facebook={fb_posts}, linkedin={linkedin_posts}, newsletter={newsletter_posts}, blog={blog_posts}"
        )

        ## record usage
        company_id_int = CompanyRepository(db).CompanyRepository(db).get_company_id_from_uuid(company_id, db)
        user_id_int = ThemeService(db).get_user_id_for_usage_tracking(user["uid"])
        channel_counts = {
            "instagram": instagram_post_count,
            "facebook": facebook_post_count,
            "linkedin": linkedin_post_count,
            "newsletter": newsletter_post_count,
            "blog": blog_post_count,
        }
        for channel in ["instagram", "facebook", "linkedin", "newsletter", "blog"]:
            post_count = channel_counts[channel]
            if post_count == 0:
                continue
            # if user is guest, skip recording usage
            if user["uid"] == constants.GUEST_USER_UID:
                continue
            if user_id_int is not None:
                for feature in ["post", "image"]:
                    UsageService(db).record_usage(
                        company_id=company_id_int,
                        user_id=user_id_int,
                        feature=feature,
                        action="generate",
                        channel=channel,
                        count=post_count
                    )

        db.commit()
        return {
            "status": "success",
            "post_ids": all_posts,
            "counts": {
                "instagram": len(insta_posts),
                "facebook": len(fb_posts),
                "linkedin": len(linkedin_posts),
                "newsletter": len(newsletter_posts),
                "blog": len(blog_posts)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate scheduled posts: {str(e)}", exc_info=True)
        ## record the log in the database
        error_handler.record_log(log_schema.LogRequest(severity="critical", message=f"Failed to generate scheduled posts: {str(e)[:100]}", status="error", status_code=500, timestamp=datetime.now(timezone.utc)), db)
        raise HTTPException(status_code=500, detail=f"Failed to generate scheduled posts: {str(e)}")
    finally:
        db.close()


@shared_task(name="market_planner.save_post", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def save_post_task(company_id: int, company_uuid: str, post_data: dict, channel: str):
    """
    company_id: integer for DB operations
    company_uuid: UUID string for Redis keys (must match API route's company_id from URL)
    """
    db = next(get_db())
    payload = None
    try:
        # Strip id/uuid - they must be generated by Postgres, not from API (which may pass None from uncommitted objects)
        post_data_clean = {k: v for k, v in post_data.items() if k not in ('id', 'uuid')}
        post_data_clean['company_id'] = company_id
        payload = content_tables.Post(
            **post_data_clean
        )
        month_id = post_data_clean.get('month_id')
        theme_index = post_data_clean.get('theme_index')
        existing_posts = db.query(content_tables.Post).filter(content_tables.Post.company_id == company_id, content_tables.Post.month_id == month_id, content_tables.Post.theme_index == theme_index).all()
        variation_index = len(existing_posts)
        if variation_index > 0:
            variation_index = variation_index + 1
        else:
            variation_index = 1
        payload.variation_index = variation_index

        # Set the document data
        db.add(payload)
        db.commit()
        db.refresh(payload) 
        logger.info(f"✅ Post '{payload.uuid}' saved successfully")

        # Publishing is handled only by publish_scheduled_posts_task (beat, ~every 10 min).

        # Cache single post (for get_post by id)
        if asyncio.run(redis.redis_set(f"{channel}_post_{company_uuid}_{payload.uuid}", json.dumps(serialization.sqlalchemy_to_dict(payload)))):
            logger.info(f"✅ {channel} post saved to redis successfully for company {company_uuid} and post {payload.uuid}")
        else:
            logger.error(f"❌ Failed to save {channel} post to redis for company {company_uuid} and post {payload.uuid}")
         

        # CRITICAL: Invalidate list cache instead of redis_list_push.
        # Pushing would risk race conditions with get_all's redis_list_set_all and could serve posts
        # with null id/uuid if timing overlaps. Invalidation forces next get_all to fetch from DB.
        if asyncio.run(redis.redis.redis_set(f"all_{channel}_posts_{company_uuid}")):
            logger.info(f"✅ {channel} posts list cache invalidated for company {company_uuid}")
           
        else:
            logger.error(f"❌ Failed to invalidate {channel} posts list cache for company {company_uuid}")
          
        return {
            "status": "success",
            "message": "Post saved successfully",
            "data": serialization.sqlalchemy_to_dict(payload)
        }
    except Exception as e:
        db.rollback()
        error_msg = f"Error saving post"
        if payload and hasattr(payload, 'uuid'):
            error_msg = f"Error saving post '{payload.uuid}'"
        logger.error(f"{error_msg}: {str(e)}")
        ## record the log in the database
        error_handler.record_log(log_schema.LogRequest(company_id=company_uuid, severity="critical", message=f"Failed to save post: {str(e)[:100]}", status="error", status_code=500, timestamp=datetime.now(timezone.utc)), db)
        raise HTTPException(status_code=500, detail=f"Failed to save post: {str(e)}")
    finally:
        db.close()


@shared_task(name="market_planner.delete_post", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def delete_post_task(company_id: str, post_id: str):
    db = next(get_db())
    try:
        company_id_int = CompanyRepository(db).get_company_id_from_uuid(company_id, db)
        post_record = db.query(content_tables.Post).filter(content_tables.Post.company_id == company_id_int, content_tables.Post.uuid == post_id).first()
        if not post_record:
            raise HTTPException(status_code=404, detail=f"Post {post_id} not found for company {company_id}")
        if post_record.status == "published":
            raise HTTPException(status_code=400, detail=f"Post {post_id} is published and cannot be deleted")
        post_dict = serialization.sqlalchemy_to_dict(post_record)
        channel = post_record.channel
        db.delete(post_record)
        db.commit()
        logger.info(f"✅ Post '{post_id}' deleted successfully")

         #delete from redis
        if  asyncio.run(redis.redis.redis_set(f"{channel}_post_{company_id}_{post_id}")):
            logger.info(f"✅ {channel} post cache invalidated for company {company_id} and post {post_id}")
        
        else:
            logger.error(f"❌ Failed to invalidate {channel} post cache for company {company_id} and post {post_id}")
        
        
        if asyncio.run(redis.redis.redis_set(f"all_{channel}_posts_{company_id}")):
            logger.info(f"✅ {channel} posts list cache invalidated for company {company_id}")
            
        else:
            logger.error(f"❌ Failed to invalidate {channel} posts list cache for company {company_id}")
            
        
        return {
            "status": "success",
            "message": "Post deleted successfully",
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting post '{post_id}': {str(e)}")
        ## record the log in the database
        error_handler.record_log(log_schema.LogRequest(company_id=company_id, severity="error", message=f"Failed to delete post: {str(e)[:100]}", status="error", status_code=500, timestamp=datetime.now(timezone.utc)), db)
        raise HTTPException(status_code=500, detail=f"Failed to delete post: {str(e)}")
    finally:
        db.close()


@shared_task(name="market_planner.update_post", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def update_post_task(company_id: str, post_id: str, channel: str, post_data: dict):

    if channel not in ["instagram", "facebook", "linkedin", "newsletter", "blog"]:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {channel}")

    db = next(get_db())

    try:
        company_id_int = CompanyRepository(db).get_company_id_from_uuid(company_id)

        post_record = (
            db.query(content_tables.Post)
            .filter(content_tables.Post.company_id == company_id_int, content_tables.Post.uuid == post_id)
            .first()
        )

        if not post_record:
            raise HTTPException(status_code=404, detail="Post not found")

        if post_record.status == "published":
            raise HTTPException(status_code=400, detail="Published posts cannot be updated")

        # ✅ ONLY update provided fields (post_data is a dict with only set fields from route's exclude_unset=True)
        for field, value in post_data.items():
            if hasattr(post_record, field):
                setattr(post_record, field, value)

        db.commit()
        db.refresh(post_record)

        # STRATEGY 1: Invalidate cache (simpler and more reliable than list manipulation)
        if asyncio.run(redis.redis.redis_set(f"all_{channel}_posts_{company_id}")):
            logger.info(f"✅ {channel} posts list cache invalidated for company {company_id}")
            
        else:
            logger.error(f"❌ Failed to invalidate {channel} posts list cache for company {company_id}")
            
        
        if asyncio.run(redis.redis.redis_set(f"{channel}_post_{company_id}_{post_id}")):
            logger.info(f"✅ {channel} post cache invalidated for company {company_id} and post {post_id}")
            
        else:
            logger.error(f"❌ Failed to invalidate {channel} post cache for company {company_id} and post {post_id}")
            

        
        logger.info(f"✅ Post {post_id} for company {company_id} updated successfully")
        return {
            "status": "success",
            "message": f"Post {post_id} for company {company_id} updated successfully",
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating post '{post_id}': {str(e)}")
        ## record the log in the database
        error_handler.record_log(log_schema.LogRequest(company_id=company_id, severity="critical", message=f"Failed to update post: {str(e)[:100]}", status="error", status_code=500, timestamp=datetime.now(timezone.utc)), db)
        raise HTTPException(status_code=500, detail=f"Failed to update post: {str(e)}")

    finally:
        db.close()


@shared_task(name="market_planner.whatsapp_match_replies", acks_late=True, retry=True, retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 3})
def whatsapp_match_replies_task(window_minutes: int = 1440, limit: int = 100):
    """
    Celery task to match WhatsApp replies (theme/post) with outbound messages and update delivery status.
    Runs for all companies with a WhatsApp account. Scheduled every 3 hours via Beat.
    """

    logger.info("Starting WhatsApp match-replies task")
    db = next(get_db())
    try:
        accs = db.query(whatsapp_tables.WhatsAppAccount).all()
        uuids = [str(a.company.uuid) for a in accs if a.company]
        if not uuids:
            logger.info("No WhatsApp accounts found, skipping match-replies")
            return {"companies_processed": 0, "total_matched": 0, "total_updated": 0, "details": []}

        results = []
        total_matched = total_updated = 0
        for cid in uuids:
            try:
                res = whatsapp_service.match_replies_impl(db, None, cid, window_minutes, limit)
                total_matched += len(res.get("matched", []))
                total_updated += len(res.get("updated", []))
                results.append({"company_id": cid, "ok": True, "matched": len(res.get("matched", [])), "updated": len(res.get("updated", []))})
            except Exception as e:
                logger.warning(f"WhatsApp match-replies failed for company {cid}: {e}")
                try:
                    error_handler.record_log(log_schema.LogRequest(
                        log_schema.LogRequest(
                            company_id=cid,
                            severity="error",
                            message=f"WhatsApp match_replies: {str(e)[:100]}",
                            status="error", 
                            status_code=500,
                            timestamp=datetime.now(timezone.utc),
                        ),
                        db,
                    ))
                except Exception:
                    logger.error(f"Error recording log for WhatsApp match-replies failed for company {cid}: {e}")
                results.append({"company_id": cid, "ok": False, "error": str(e)})

        logger.info(f"WhatsApp match-replies done: {len(uuids)} companies, {total_matched} matched, {total_updated} updated")
        return {
            "companies_processed": len(uuids),
            "total_matched": total_matched,
            "total_updated": total_updated,
            "details": results,
            "window_minutes": window_minutes,
            "limit": limit,
        }
    finally:
        db.close()
