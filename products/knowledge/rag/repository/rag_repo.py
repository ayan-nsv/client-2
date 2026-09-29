from sqlalchemy.orm import Session

from products.knowledge.rag.tables.rag_tables import UploadMethod
from shared.utils.error import error


class RagRepository:
    """Data access for knowledge.* documents.

    ``get_upload_method_by_uuid`` used to live on core's UserRepository, which meant
    core imported ``knowledge`` models to serve a lookup that has nothing to do with
    users. Both callers were already inside this product.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_upload_method_by_uuid(self, document_uuid) -> UploadMethod:
        """Get UploadMethod by UUID."""
        upload = self.db.query(UploadMethod).filter(
            UploadMethod.uuid == document_uuid
        ).first()

        if not upload:
            raise error.NotFound(message="Document not found")

        return upload
