import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import httpx

from app.database import SessionLocal
from app.models import Alert, CheckResult
from app.config import settings
from app.logger import logger
from app.detector import (
    detect_anomalies,
    detect_live_issues,
    check_schema,
    ANOMALY_CONNECTION_FAILURE,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
)
from app.ai_service import generate_batch_messages, build_fallback_message
from app.notifier import send_alert_email, format_alert_body, format_resolved_body

# Monitored API definitions
MONITORED_APIS = [
    {
        "name": "Users API",
        "url": "https://jsonplaceholder.typicode.com/users",
        "required_fields": ["id", "name", "username", "email"],
    },
    {
        "name": "Posts API",
        "url": "https://jsonplaceholder.typicode.com/posts",
        "required_fields": ["id", "title", "body", "userId"],
    },
    {
        "name": "Slow API",
        "url": "https://httpbin.org/delay/4",
    },
    {
        "name": "Failing API",
        "url": "https://httpbin.org/status/500",
    },
    {
        "name": "Flaky API",
        "url": "https://httpbin.org/status/200,500",
    },
]

TIMEOUT_SEC = 10.0


async def check_api(client: httpx.AsyncClient, api: dict) -> dict:
    """
    Calls one API endpoint and extracts latency, status code, record counts, and JSON body.
    Ensures safe handling of network drops, timeouts, and non-JSON payloads.
    """
    start = time.perf_counter()
    try:
        r = await client.get(api["url"])
        latency_ms = round((time.perf_counter() - start) * 1000)
        try:
            body = r.json()
        except Exception:
            body = None

        if isinstance(body, list):
            records_returned = len(body)
        elif isinstance(body, dict):
            records_returned = 1
        elif r.is_success:
            # 2xx status endpoints without JSON list (e.g. status/200) count as 1 response
            records_returned = 1
        else:
            records_returned = 0

        return {
            "api_name": api["name"],
            "status_code": r.status_code,
            "response_time_ms": latency_ms,
            "records_returned": records_returned,
            "body": body,
            "error": None,
        }
    except Exception as e:
        latency_ms = round((time.perf_counter() - start) * 1000)
        return {
            "api_name": api["name"],
            "status_code": 0,
            "response_time_ms": latency_ms,
            "records_returned": 0,
            "body": None,
            "error": str(e) or e.__class__.__name__,
        }


def _record_and_evaluate_check(
    api: dict, check_data: dict
) -> Dict[str, Any]:
    """
    Synchronous database operation executed in a worker thread.
    Saves the check result, inspects recent history, detects anomalies,
    and performs deduplication or auto-resolution.
    """
    db = SessionLocal()
    try:
        api_name = check_data["api_name"]
        status_code = check_data["status_code"]
        latency_ms = check_data["response_time_ms"]
        records_returned = check_data["records_returned"]
        error = check_data["error"]
        body = check_data["body"]

        # Failure condition: status_code == 0 or status_code >= 500
        is_success = not (status_code == 0 or status_code >= 500)

        # 1. Save CheckResult to database
        check_row = CheckResult(
            api_name=api_name,
            status_code=status_code,
            response_time_ms=latency_ms,
            records_returned=records_returned,
            is_success=is_success,
            checked_at=datetime.utcnow(),
        )
        db.add(check_row)
        db.commit()

        # 2. Fetch last 10 historical checks for this API
        history = (
            db.query(CheckResult)
            .filter(CheckResult.api_name == api_name)
            .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
            .limit(10)
            .all()
        )

        # Determine previous records count (history[0] is current, history[1] is previous)
        prev_records = history[1].records_returned if len(history) > 1 else None

        # 3. Anomaly Evaluation
        detected_anomalies: List[str] = []
        severities: List[str] = []

        # Schema check
        schema_problem = check_schema(body, api.get("required_fields"))

        # Live / historical issue detection
        live_issues = detect_live_issues(history, records_returned, prev_records, schema_problem)
        if live_issues:
            detected_anomalies.extend(live_issues["anomaly_types"])
            severities.append(live_issues["severity"])

        # Metric anomaly detection
        if status_code == 0:
            # Rule: status_code 0 must produce CONNECTION_FAILURE (critical), not INVALID_DATA
            detected_anomalies.append(ANOMALY_CONNECTION_FAILURE)
            severities.append(SEVERITY_CRITICAL)
        else:
            metric_record = {
                "api_name": api_name,
                "status_code": status_code,
                "response_time_ms": latency_ms,
                "records_returned": records_returned,
            }
            metric_res = detect_anomalies(metric_record)
            if metric_res:
                detected_anomalies.extend(metric_res["anomaly_types"])
                severities.append(metric_res["severity"])

        # De-duplicate anomaly types maintaining order
        merged_anomalies = list(dict.fromkeys(detected_anomalies))
        highest_severity = (
            SEVERITY_CRITICAL if SEVERITY_CRITICAL in severities else SEVERITY_WARNING
        )

        # 4. Handle Healthy Case vs Anomaly Case
        if not merged_anomalies:
            # Check is healthy: evaluate auto-resolve (2 consecutive healthy checks)
            # history[0] is current (healthy), history[1] is previous
            if len(history) >= 2 and history[0].is_success and history[1].is_success:
                active_alerts = (
                    db.query(Alert)
                    .filter(Alert.api_name == api_name, Alert.status == "active")
                    .all()
                )
                if active_alerts:
                    resolved_count = len(active_alerts)
                    now = datetime.utcnow()
                    for alert in active_alerts:
                        alert.status = "resolved"
                        alert.resolved_at = now
                    db.commit()
                    logger.info(
                        f"Auto-resolved {resolved_count} active alert(s) for '{api_name}' after 2 consecutive clean checks."
                    )
                    return {
                        "action": "auto_resolved",
                        "api_name": api_name,
                        "is_healthy": True,
                        "resolved_count": resolved_count,
                        "resolved_at": now,
                    }

            return {
                "action": "healthy",
                "api_name": api_name,
                "is_healthy": True,
            }

        # Anomaly Case:
        # Prepare privacy-safe raw_data (never includes body or patient/user values)
        safe_raw_data = {
            "api_name": api_name,
            "status_code": status_code,
            "response_time_ms": latency_ms,
            "records_returned": records_returned,
        }
        if error:
            safe_raw_data["error"] = str(error)
        if schema_problem:
            safe_raw_data["schema_problem"] = schema_problem

        # Deduplication check: active alert with exact same anomaly types set
        active_alerts = (
            db.query(Alert)
            .filter(Alert.api_name == api_name, Alert.status == "active")
            .all()
        )

        matching_alert: Optional[Alert] = None
        for a in active_alerts:
            if set(a.anomaly_types or []) == set(merged_anomalies):
                matching_alert = a
                break

        now = datetime.utcnow()

        if matching_alert:
            matching_alert.occurrence_count += 1
            matching_alert.last_seen_at = now
            matching_alert.severity = highest_severity
            matching_alert.raw_data = safe_raw_data

            # Check if reminder email cooldown has passed
            send_reminder = False
            if (
                matching_alert.last_notified_at is None
                or (now - matching_alert.last_notified_at).total_seconds()
                >= settings.ALERT_COOLDOWN_MIN * 60
            ):
                send_reminder = True
                matching_alert.last_notified_at = now

            db.commit()
            db.refresh(matching_alert)
            logger.info(
                f"Updated existing alert id={matching_alert.id} for '{api_name}' (occurrence_count={matching_alert.occurrence_count})."
            )

            return {
                "action": "deduped",
                "api_name": api_name,
                "is_healthy": False,
                "send_reminder": send_reminder,
                "alert": {
                    "id": matching_alert.id,
                    "api_name": matching_alert.api_name,
                    "severity": matching_alert.severity,
                    "anomaly_types": matching_alert.anomaly_types,
                    "occurrence_count": matching_alert.occurrence_count,
                    "created_at": matching_alert.created_at,
                    "last_seen_at": matching_alert.last_seen_at,
                    "message": matching_alert.message,
                },
            }

        # New alert needed
        return {
            "action": "new_alert_needed",
            "api_name": api_name,
            "is_healthy": False,
            "severity": highest_severity,
            "anomaly_types": merged_anomalies,
            "raw_data": safe_raw_data,
            "facts": {
                "api_name": api_name,
                "status_code": status_code,
                "response_time_ms": latency_ms,
                "records_returned": records_returned,
                "anomaly_types": merged_anomalies,
                "severity": highest_severity,
            },
        }

    except Exception as exc:
        db.rollback()
        logger.error(f"Database error evaluating check for {api.get('name')}: {exc}")
        raise
    finally:
        db.close()


def _save_new_alert_db(
    api_name: str,
    message: str,
    message_source: str,
    anomaly_types: List[str],
    severity: str,
    raw_data: dict,
) -> Dict[str, Any]:
    """
    Creates and commits a new Alert row in the database in a worker thread.
    """
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        alert = Alert(
            api_name=api_name,
            message=message,
            message_source=message_source,
            anomaly_types=anomaly_types,
            severity=severity,
            status="active",
            raw_data=raw_data,
            occurrence_count=1,
            last_seen_at=now,
            last_notified_at=now,
            created_at=now,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        logger.info(f"Created new alert id={alert.id} for '{api_name}' ({alert.severity}).")

        return {
            "id": alert.id,
            "api_name": alert.api_name,
            "severity": alert.severity,
            "anomaly_types": alert.anomaly_types,
            "occurrence_count": alert.occurrence_count,
            "created_at": alert.created_at,
            "last_seen_at": alert.last_seen_at,
            "message": alert.message,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to create new alert for {api_name}: {exc}")
        raise
    finally:
        db.close()


def _cleanup_old_checks_db() -> int:
    """
    Deletes check_results rows older than 2 days to maintain clean telemetry history.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=2)
        deleted = (
            db.query(CheckResult)
            .filter(CheckResult.checked_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted > 0:
            logger.info(f"Purged {deleted} check_results records older than 2 days.")
        return deleted
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to purge old check_results: {exc}")
        return 0
    finally:
        db.close()


async def process_single_api(client: httpx.AsyncClient, api: dict) -> bool:
    """
    Processes a single API end-to-end:
    1. HTTP check
    2. DB check save + evaluation
    3. AI message generation (if new alert)
    4. DB alert creation
    5. Email notifications
    Returns True if healthy, False if anomaly detected.
    """
    try:
        # Step 1: Call API
        check_res = await check_api(client, api)
        logger.info(
            f"Checked {check_res['api_name']}: status={check_res['status_code']} "
            f"time={check_res['response_time_ms']}ms records={check_res['records_returned']} error={check_res['error']}"
        )

        # Step 2: Database evaluation
        eval_result = await asyncio.to_thread(_record_and_evaluate_check, api, check_res)
        action = eval_result.get("action")
        api_name = eval_result["api_name"]
        is_healthy = eval_result.get("is_healthy", False)

        # Step 3: Handle notifications and new alerts
        if action == "auto_resolved":
            resolved_count = eval_result["resolved_count"]
            resolved_at = eval_result["resolved_at"]
            subject = f"[RESOLVED] {api_name} - {resolved_count} alert(s) resolved"
            body = format_resolved_body(api_name, resolved_count, resolved_at)
            await send_alert_email(subject, body)

        elif action == "deduped":
            if eval_result.get("send_reminder"):
                alert_info = eval_result["alert"]
                subject = f"[REMINDER] [{alert_info['severity'].upper()}] {api_name} - {', '.join(alert_info['anomaly_types'])} ({alert_info['occurrence_count']}x)"
                body = format_alert_body(
                    "Recurring Incident Reminder",
                    api_name,
                    alert_info["severity"],
                    alert_info["anomaly_types"],
                    alert_info["occurrence_count"],
                    alert_info["created_at"],
                    alert_info["last_seen_at"],
                    alert_info["message"],
                )
                await send_alert_email(subject, body)

        elif action == "new_alert_needed":
            facts = eval_result["facts"]
            severity = eval_result["severity"]
            anomaly_types = eval_result["anomaly_types"]
            raw_data = eval_result["raw_data"]

            # AI message generation with fallback guarantee
            try:
                ai_results = await generate_batch_messages([facts])
                if ai_results and len(ai_results) > 0:
                    message, source = ai_results[0]
                else:
                    message, source = build_fallback_message(facts), "fallback"
            except Exception as e:
                logger.error(f"Error generating AI message for {api_name}: {e}")
                message, source = build_fallback_message(facts), "fallback"

            # Save new alert in database
            created_alert = await asyncio.to_thread(
                _save_new_alert_db,
                api_name=api_name,
                message=message,
                message_source=source,
                anomaly_types=anomaly_types,
                severity=severity,
                raw_data=raw_data,
            )

            # Send email for new alert
            subject = f"[ALERT] [{severity.upper()}] {api_name} - {', '.join(anomaly_types)}"
            body = format_alert_body(
                "New Incident Detected",
                api_name,
                severity,
                anomaly_types,
                created_alert["occurrence_count"],
                created_alert["created_at"],
                created_alert["last_seen_at"],
                created_alert["message"],
            )
            await send_alert_email(subject, body)

        return is_healthy

    except Exception as exc:
        logger.error(f"Unhandled error while monitoring {api.get('name')}: {exc}")
        return False


async def run_checks():
    """
    Main scheduled monitoring entrypoint called by APScheduler.
    Iterates through all MONITORED_APIS concurrently or sequentially with httpx,
    evaluates anomalies, updates routes.last_run_metrics, and cleans old records.
    """
    logger.info("Running scheduled API health checks...")
    healthy_count = 0
    total_checked = len(MONITORED_APIS)

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        for api in MONITORED_APIS:
            try:
                is_healthy = await process_single_api(client, api)
                if is_healthy:
                    healthy_count += 1
            except Exception as e:
                logger.error(f"Failed processing API {api.get('name')}: {e}")

    # Update global metrics for top summary cards
    import app.routes as routes_module
    routes_module.last_run_metrics["total"] = total_checked
    routes_module.last_run_metrics["healthy"] = healthy_count
    logger.info(
        f"Scheduled check cycle completed: {healthy_count}/{total_checked} APIs healthy."
    )

    # Clean up records older than 2 days
    await asyncio.to_thread(_cleanup_old_checks_db)