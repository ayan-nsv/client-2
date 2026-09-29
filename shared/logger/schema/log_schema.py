from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional

class LogRequest(BaseModel):
    company_id: Optional[str] = None
    severity: str
    message: str
    status: str
    status_code: int
    timestamp: datetime = datetime.now(timezone.utc)

