from sqlalchemy.orm import Session

from core.repository.usage_repo import UsageRepository
from core.repository.company_repo import CompanyRepository
from core.repository.user_repo import UserRepository
from shared.utils.auth import auth
from shared.utils.error import error

from datetime import datetime, timezone


def get_user_id_for_usage_tracking(db, firebase_uid) -> int | None:
    """
    Get user ID for usage tracking. Returns None for guest user or if user not found.
    Use this when recording usage metrics - guest usage is tracked with user_id=None.

    Previously lived on market_planner's ThemeService, which meant core imported a
    product service to resolve one of its own users. ThemeService now delegates here,
    so its callers are unaffected.
    """
    if not firebase_uid or auth.is_guest_uid(firebase_uid):
        return None
    try:
        user = UserRepository(db).get_user_by_firebase_id(firebase_uid)
        return user.id
    except error.NotFound:
        return None


class UsageService:
    def __init__(self, db: Session):
        # Every increment_* method below uses self.db; without this they raise
        # AttributeError before recording anything.
        self.db = db
        self.repo = UsageRepository(db)

    def record_usage(
        self,
        company_id: int,
        feature: str,
        action: str,
        channel: str | None = None,
        user_id: int | None = None,
        count: int = 1
    ):
        return self.repo.record_usage(company_id, user_id, feature, action, channel, count)

    def increment_post_generation(
        self,
        company_uuid: str,
        firebase_uid: str,
        channel: str,
    ):
        company_id = CompanyRepository(self.db).get_company_id_from_uuid(company_uuid)
        user_id = get_user_id_for_usage_tracking(self.db, firebase_uid)

        if user_id is None:
            return

        self.repo.increment_usage(
            company_id=company_id,
            user_id=user_id,
            feature="post",
            channel=channel,
        )

    def increment_caption_regeneration(
        self,
        company_id: int,
        firebase_uid: str,
        channel: str,
    ):
        user_id = get_user_id_for_usage_tracking(self.db, firebase_uid)

        if user_id is None:
            return

        self.repo.increment_usage(
            company_id=company_id,
            user_id=user_id,
            feature="caption",
            action="regenerate",
            channel=channel,
        )

    def increment_image_generation(
    self,
    company_id: int,
    firebase_uid: str,
    channel: str,
     ):

        user_id = get_user_id_for_usage_tracking(self.db, firebase_uid)

        if user_id is None:
            return

        self.repo.increment_usage(
            company_id=company_id,
            user_id=user_id,
            feature="image",
            action="generate",
            channel=channel,
        )

    def increment_image_edit(
    self,
    company_id: int,
    firebase_uid: str,
    channel: str,
     ):

        user_id = get_user_id_for_usage_tracking(self.db, firebase_uid)

        if user_id is None:
            return

        self.repo.increment_usage(
            company_id=company_id,
            user_id=user_id,
            feature="image",
            action="edit",
            channel=channel,
        )

    def increment_blog_generation(
        self,
        company_id: int,
        firebase_uid: str,
    ):
        user_id = get_user_id_for_usage_tracking(self.db, firebase_uid)

        if user_id is None:
            return

        self.repo.increment_usage(
            company_id=company_id,
            user_id=user_id,
            feature="blog",
            action="generate",
            channel="blog",
        )



















