import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Body, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, CheckResult
from app.schemas import (
    AlertResponse,
    MonitorResponse,
    AlertListResponse,
    SummaryResponse,
    HealthResponse,
    ApiStatusItem,
    ApiStatusListResponse,
)
from app.detector import detect_anomalies
from app.ai_service import generate_batch_messages
from app.logger import logger

router = APIRouter()

# Holds metrics from the most recent monitoring run
last_run_metrics = {
    "total": 0,
    "healthy": 0,
}


async def process_monitoring_batch(batch: Any, db: Session) -> Dict[str, Any]:
    """
    Core function that inspects a batch of API metrics, generates alerts
    via Gemini/Fallback, saves them to the database, and returns summary counts.
    """
    if isinstance(batch, dict):
        batch = [batch]

    if not isinstance(batch, list) or len(batch) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Input batch cannot be empty. Please provide at least one API record.",
        )

    logger.info(f"Received batch of {len(batch)} API records for monitoring.")

    total = len(batch)
    healthy = 0
    anomalies_to_process = []

    # 1. Rule-based anomaly detection per record
    for record in batch:
        anomaly_info = detect_anomalies(record)
        if anomaly_info is None:
            healthy += 1
            api_name = record.get("api_name", "Unknown API") if isinstance(record, dict) else "Unknown"
            logger.info(f"API '{api_name}' is healthy.")
        else:
            api_name = anomaly_info["api_name"]
            raw_data = anomaly_info["raw_data"]
            logger.info(
                f"API '{api_name}' anomaly detected: {anomaly_info['anomaly_types']} "
                f"(Severity: {anomaly_info['severity']})"
            )

            facts = {
                "api_name": api_name,
                "status_code": raw_data.get("status_code", "N/A"),
                "response_time_ms": raw_data.get("response_time_ms", "N/A"),
                "records_returned": raw_data.get("records_returned", "N/A"),
                "anomaly_types": anomaly_info["anomaly_types"],
                "severity": anomaly_info["severity"],
            }

            anomalies_to_process.append({
                "facts": facts,
                "anomaly_info": anomaly_info,
            })

    # 2. Asynchronous message generation (Gemini with Fallback)
    facts_list = [item["facts"] for item in anomalies_to_process]
    messages_with_sources = await generate_batch_messages(facts_list)

    # 3. Store new alerts in database
    created_alerts: List[Alert] = []
    now = datetime.utcnow()
    for item, (msg, source) in zip(anomalies_to_process, messages_with_sources):
        info = item["anomaly_info"]
        alert = Alert(
            api_name=info["api_name"],
            message=msg,
            message_source=source,
            anomaly_types=info["anomaly_types"],
            severity=info["severity"],
            status="active",
            raw_data=info["raw_data"],
            occurrence_count=1,
            last_seen_at=now,
            last_notified_at=now,
            created_at=now,
        )
        db.add(alert)
        created_alerts.append(alert)

    try:
        db.commit()
        for alert in created_alerts:
            db.refresh(alert)
            logger.info(f"Saved alert id={alert.id} for '{alert.api_name}' ({alert.severity}).")
    except Exception as exc:
        db.rollback()
        logger.error(f"Database write failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store alerts in the database.",
        )

    # Count alert severities
    critical_count = sum(1 for a in created_alerts if a.severity == "critical")
    warning_count = sum(1 for a in created_alerts if a.severity == "warning")

    # Update global metrics for top summary cards
    last_run_metrics["total"] = total
    last_run_metrics["healthy"] = healthy

    return {
        "total": total,
        "healthy": healthy,
        "anomalies": len(created_alerts),
        "critical": critical_count,
        "warning": warning_count,
        "alerts": created_alerts,
    }


@router.post("/monitor", response_model=MonitorResponse)
async def monitor_batch(
    batch: Any = Body(..., description="Array or single object of API response metrics"),
    db: Session = Depends(get_db),
):
    """Processes a custom list or single object of API records."""
    return await process_monitoring_batch(batch, db)


@router.post("/monitor/sample", response_model=MonitorResponse)
async def monitor_sample(db: Session = Depends(get_db)):
    """Reads sample_input.json and processes the records."""
    sample_path = Path(__file__).resolve().parent.parent / "data" / "sample_input.json"
    if not sample_path.exists():
        logger.error("sample_input.json not found in data directory.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="sample_input.json not found",
        )

    try:
        with open(sample_path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as exc:
        logger.error(f"Error reading sample_input.json: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read sample data file.",
        )

    return await process_monitoring_batch(records, db)


@router.get("/alerts", response_model=AlertListResponse)
def get_alerts(
    status: Optional[str] = Query("active", description="Filter by status ('active', 'resolved', or 'all')"),
    severity: Optional[str] = Query(None, description="Filter by severity ('critical', 'warning', or None)"),
    db: Session = Depends(get_db),
):
    """Returns alerts ordered newest first with optional status and severity filtering."""
    query = db.query(Alert)

    # Status filter
    if status and status.lower() != "all":
        query = query.filter(Alert.status == status.lower())

    # Severity filter
    if severity and severity.lower() != "all":
        query = query.filter(Alert.severity == severity.lower())

    # Order newest first (by last_seen_at desc, then id desc)
    alerts = query.order_by(Alert.last_seen_at.desc(), Alert.id.desc()).all()
    return {"items": alerts, "total": len(alerts)}


@router.patch("/alerts/{alert_id}/resolve", response_model=AlertResponse)
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    """Marks an existing alert as resolved."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        logger.error(f"Attempted to resolve non-existent alert id={alert_id}.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID {alert_id} not found",
        )

    alert.status = "resolved"
    alert.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)
    logger.info(f"Alert id={alert_id} for '{alert.api_name}' marked as resolved.")
    return alert


@router.get("/alerts/summary", response_model=SummaryResponse)
def get_summary(db: Session = Depends(get_db)):
    """
    Returns last run's total and healthy counts, plus current active critical and warning counts.
    """
    active_critical = db.query(Alert).filter(
        Alert.status == "active", Alert.severity == "critical"
    ).count()

    active_warning = db.query(Alert).filter(
        Alert.status == "active", Alert.severity == "warning"
    ).count()

    return {
        "total": last_run_metrics["total"],
        "healthy": last_run_metrics["healthy"],
        "critical": active_critical,
        "warning": active_warning,
    }


@router.get("/apis/status", response_model=ApiStatusListResponse)
def get_apis_status(db: Session = Depends(get_db)):
    """
    Returns the telemetry status, uptime %, and average latency over the last hour
    for all configured monitored APIs.
    """
    from app.monitor import MONITORED_APIS

    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    items = []

    for api in MONITORED_APIS:
        name = api["name"]
        url = api["url"]

        # Fetch all checks in the last 1 hour
        hour_checks = (
            db.query(CheckResult)
            .filter(CheckResult.api_name == name, CheckResult.checked_at >= one_hour_ago)
            .all()
        )

        # Fetch latest check
        latest_check = (
            db.query(CheckResult)
            .filter(CheckResult.api_name == name)
            .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
            .first()
        )

        if hour_checks:
            total_checks = len(hour_checks)
            healthy_checks = sum(1 for c in hour_checks if c.is_success)
            uptime = round((healthy_checks / total_checks) * 100, 1)
            avg_latency = round(sum(c.response_time_ms for c in hour_checks) / total_checks, 1)
        elif latest_check:
            uptime = 100.0 if latest_check.is_success else 0.0
            avg_latency = float(latest_check.response_time_ms)
        else:
            uptime = 100.0
            avg_latency = 0.0

        items.append(
            ApiStatusItem(
                api_name=name,
                url=url,
                status_code=latest_check.status_code if latest_check else 200,
                response_time_ms=latest_check.response_time_ms if latest_check else 0,
                is_healthy=latest_check.is_success if latest_check else True,
                uptime_percentage=uptime,
                avg_latency_ms=avg_latency,
                last_checked_at=latest_check.checked_at if latest_check else None,
            )
        )

    return {"items": items}


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

