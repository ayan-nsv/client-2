from shared.database.postgres.database_config import get_db
from products.market_planner.tables import channel_tables
from shared.utils.error import error


class ChannelRepository:
    def __init__(self):
        self.db = get_db()

    def get_channel_config(self, company_id):
        return (
            self.db.query(channel_tables.ChannelConfig)
            .filter(
                channel_tables.ChannelConfig.company_id == company_id
            )
            .first()
        )
    def create_channel_config(self, company_id, data):
        try:
            config = channel_tables.ChannelConfig(
                company_id=company_id,
                instagram_post_count=data.instagram_post_count,
                facebook_post_count=data.facebook_post_count,
                linkedin_post_count=data.linkedin_post_count,
                email_campaign_count=data.email_campaign_count,
                blog_post_count=data.blog_post_count,
                tiktok_active=data.tiktok_active,
            )

            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)

            return config

        except Exception:
            self.db.rollback()
            raise


    def update_channel_config(self, company_id, update_data):
        try:
            config = self.get_channel_config(company_id)

            if config is None:
                raise error.NotFound("Channel configuration not found")

            for key, value in update_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            self.db.commit()
            self.db.refresh(config)

            return config

        except Exception:
            self.db.rollback()
            raise

    def get_channel_config(self, company_id):
        config = (
            self.db.query(channel_tables.ChannelConfig)
            .filter(channel_tables.ChannelConfig.company_id == company_id)
            .first()
        )

        if config is None:
            raise error.NotFound(
                "Channel configuration not found"
            )

        return config
    