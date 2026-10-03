from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict

class AlertResponse(BaseModel):
    """Schema for returning alert details."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    api_name: str
    message: str
    message_source: str  # "ai" or "fallback"
    anomaly_types: List[str]
    severity: str        # "critical" or "warning"
    status: str          # "active" or "resolved"
    raw_data: Dict[str, Any]
    occurrence_count: int = 1
    last_seen_at: Optional[datetime] = None
    last_notified_at: Optional[datetime] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

class MonitorResponse(BaseModel):
    """Schema returned after monitoring a batch of API metrics."""
    total: int
    healthy: int
    anomalies: int
    critical: int
    warning: int
    alerts: List[AlertResponse]

class AlertListResponse(BaseModel):
    """Schema for listing paginated or filtered alerts."""
    items: List[AlertResponse]
    total: int

class SummaryResponse(BaseModel):
    """Schema for top metrics card summary."""
    total: int
    healthy: int
    critical: int
    warning: int

class HealthResponse(BaseModel):
    """Schema for service health check."""
    status: str

class ApiStatusItem(BaseModel):
    """Schema for individual monitored API telemetry status."""
    api_name: str
    url: str
    status_code: int
    response_time_ms: int
    is_healthy: bool
    uptime_percentage: float
    avg_latency_ms: float
    last_checked_at: Optional[datetime] = None

class ApiStatusListResponse(BaseModel):
    """Schema for list of monitored APIs telemetry status."""
    items: List[ApiStatusItem]

