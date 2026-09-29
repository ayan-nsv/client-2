from sqlalchemy.orm import Session
from datetime import datetime

from products.market_planner.tables import content_tables

class ImageTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_image_config(self, company_id: int):
        return (
            self.db.query(content_tables.ImageConfig)
            .filter(content_tables.ImageConfig.company_id == company_id)
            .first()
        )

    def create_image_config(self, company_id: int, image_type: int):
        image_config = content_tables.ImageConfig(
            company_id=company_id,
            image_type=image_type,
        )

        self.db.add(image_config)
        self.db.commit()
        self.db.refresh(image_config)

        return image_config

    def update_image_config(self, company_id, image_type):
        image_config = self.get_image_config(company_id)

        if not image_config:
            return None

        image_config.image_type = image_type
        image_config.updated_at = datetime.now()

        self.db.commit()
        self.db.refresh(image_config)

        return image_config