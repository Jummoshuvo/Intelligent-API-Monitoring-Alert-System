from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean
from app.database import Base

class Alert(Base):
    """
    SQLAlchemy model representing an API anomaly alert stored in the database.
    """
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    api_name = Column(String(255), nullable=False, index=True)
    message = Column(Text, nullable=False)
    message_source = Column(String(50), nullable=False)  # "ai" or "fallback"
    anomaly_types = Column(JSON, nullable=False)        # List of anomaly strings
    severity = Column(String(20), nullable=False)        # "critical" or "warning"
    status = Column(String(20), nullable=False, default="active")  # "active" or "resolved"
    raw_data = Column(JSON, nullable=False)              # Original input dictionary
    occurrence_count = Column(Integer, nullable=False, default=1)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)


class CheckResult(Base):
    """
    SQLAlchemy model representing historical check executions for monitored APIs.
    """
    __tablename__ = "check_results"

    id = Column(Integer, primary_key=True, index=True)
    api_name = Column(String(255), nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Integer, nullable=False)
    records_returned = Column(Integer, nullable=True)
    is_success = Column(Boolean, nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
