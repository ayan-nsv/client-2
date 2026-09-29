from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from shared.database.postgres.database_config import Base

class LogRecord(Base):
    __tablename__ = "log_records"
    __table_args__ = {"schema": "core"}
    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True)
    company_id = Column(Integer, index=True)
    
    severity = Column(String(255))
    message = Column(Text)
    status = Column(String(255))
    status_code = Column(Integer)
    timestamp = Column(DateTime(timezone=True), index=True)

    def __repr__(self):
        return f"<LogRecord(id={self.id}, company_id={self.company_id}, severity={self.severity}, message={self.message}, status={self.status}, status_code={self.status_code}, timestamp={self.timestamp})>"


class ToolExecutionLog(Base):
    __tablename__ = "tool_execution_logs"
    __table_args__ = {"schema": "core"}
    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True)
    company_id = Column(Integer, index=True)
    tool_name = Column(String(255), index=True)
    success = Column(Boolean, default=True)
    duration_ms = Column(Integer)
    error_message = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<ToolExecutionLog(id={self.id}, tool_name={self.tool_name}, success={self.success}, duration_ms={self.duration_ms})>"