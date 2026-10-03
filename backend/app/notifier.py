import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage
import smtplib
from typing import List, Optional
from zoneinfo import ZoneInfo

from app.config import settings
from app.logger import logger

BD_TZ = ZoneInfo("Asia/Dhaka")


def _to_bst(dt: Optional[datetime]) -> str:
    """UTC বা Naive datetime-কে Bangladesh Standard Time (BST)-এ রূপান্তর করে স্ট্রিং দেয়।"""
    if dt is None:
        return "N/A"
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    bst_time = dt.astimezone(BD_TZ)
    return bst_time.strftime("%Y-%m-%d %I:%M:%S %p BST")


def send_email_sync(subject: str, body: str) -> bool:
    """
    Synchronously sends an email using smtplib with STARTTLS.
    If credentials are missing or an error occurs, logs a warning and returns False without crashing.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD or not settings.ALERT_EMAIL_TO:
        logger.warning(
            "Email alert skipped: SMTP_USER, SMTP_PASSWORD, or ALERT_EMAIL_TO is not configured in .env."
        )
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_USER
        msg["To"] = settings.ALERT_EMAIL_TO
        msg.set_content(body)

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email alert successfully sent to {settings.ALERT_EMAIL_TO} (Subject: '{subject}')")
        return True
    except Exception as exc:
        logger.error(f"Failed to send email alert: {exc}")
        return False


async def send_alert_email(subject: str, body: str) -> bool:
    """
    Asynchronously sends an email alert by delegating to a background thread.
    """
    return await asyncio.to_thread(send_email_sync, subject, body)


def format_alert_body(
    event_type: str,
    api_name: str,
    severity: str,
    anomaly_types: List[str],
    occurrence_count: int,
    created_at: datetime,
    last_seen_at: datetime,
    message: str,
    dashboard_url: str = "http://localhost:8000/",
) -> str:
    """
    Formats email notification body containing strictly metadata (privacy compliant).
    Displays timestamps in Bangladesh Standard Time (BST).
    """
    return (
        f"API MONITOR NOTIFICATION: {event_type.upper()}\n"
        f"=========================================\n\n"
        f"API Name:         {api_name}\n"
        f"Severity:         {severity.upper()}\n"
        f"Anomaly Types:    {', '.join(anomaly_types)}\n"
        f"Occurrence Count: {occurrence_count}\n"
        f"First Detected:   {_to_bst(created_at)}\n"
        f"Last Seen:        {_to_bst(last_seen_at)}\n\n"
        f"Alert Summary:\n"
        f"{message}\n\n"
        f"-----------------------------------------\n"
        f"Dashboard: {dashboard_url}\n"
    )


def format_resolved_body(
    api_name: str,
    resolved_count: int,
    resolved_at: datetime,
    dashboard_url: str = "http://localhost:8000/",
) -> str:
    """
    Formats auto-resolution email notification body with BST timestamp.
    """
    return (
        f"API MONITOR NOTIFICATION: RESOLVED\n"
        f"=========================================\n\n"
        f"API Name:       {api_name}\n"
        f"Status:         RECOVERED / HEALTHY\n"
        f"Alerts Cleared: {resolved_count}\n"
        f"Resolved At:    {_to_bst(resolved_at)}\n\n"
        f"The API has successfully passed 2 consecutive healthy health checks.\n"
        f"All active anomaly alerts for this service have been automatically resolved.\n\n"
        f"-----------------------------------------\n"
        f"Dashboard: {dashboard_url}\n"
    )