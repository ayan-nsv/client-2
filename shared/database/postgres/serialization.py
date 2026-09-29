import uuid
from datetime import datetime

def sqlalchemy_to_dict(obj):
    """Convert SQLAlchemy model instance to dictionary."""
    if obj is None:
        return None
    
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        # Convert UUID to string
        if value is not None:
            if isinstance(value, uuid.UUID):
                value = str(value)
            # Convert datetime to ISO format string
            elif isinstance(value, datetime):
                value = value.isoformat()
        result[column.name] = value
    return result