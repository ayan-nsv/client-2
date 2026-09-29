from sqlalchemy.orm import Session

class PublishRepository:
    def __init__(self, db: Session):
        self.db = db

    