from typing import Dict, Any, List, Optional, Tuple
from app.config import settings

# Anomaly type constants
ANOMALY_HIGH_RESPONSE_TIME = "HIGH_RESPONSE_TIME"
ANOMALY_SERVER_ERROR = "SERVER_ERROR"
ANOMALY_CLIENT_ERROR = "CLIENT_ERROR"
ANOMALY_ZERO_RECORDS = "ZERO_RECORDS"
ANOMALY_INVALID_DATA = "INVALID_DATA"

# Severity levels
SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"


def validate_api_record(record: Any) -> Tuple[bool, str, Optional[int], Optional[int], Optional[int]]:
    """
    Validates the structure and types of an incoming API record.
    Returns (is_valid, api_name, status_code, response_time_ms, records_returned).
    """
    if not isinstance(record, dict):
        return False, "UnknownAPI", None, None, None

    api_name = record.get("api_name")
    status_code = record.get("status_code")
    response_time_ms = record.get("response_time_ms")
    records_returned = record.get("records_returned")

    # Validate api_name
    if not isinstance(api_name, str) or not api_name.strip():
        return False, str(api_name or "UnknownAPI"), None, None, None

    # Validate status_code (must be integer, not boolean, within standard HTTP range)
    if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code < 100 or status_code > 599:
        return False, api_name, None, None, None

    # Validate response_time_ms (must be numeric, non-negative, not boolean)
    if isinstance(response_time_ms, bool) or not isinstance(response_time_ms, (int, float)) or response_time_ms < 0:
        return False, api_name, status_code, None, None

    # Validate records_returned (must be integer, non-negative, not boolean)
    if isinstance(records_returned, bool) or not isinstance(records_returned, int) or records_returned < 0:
        return False, api_name, status_code, int(response_time_ms), None

    return True, api_name, status_code, int(response_time_ms), records_returned


def detect_anomalies(record: Any) -> Optional[Dict[str, Any]]:
    """
    Evaluates an API metric record against rule-based anomaly conditions.
    Returns None if the record is healthy.
    Otherwise returns a dictionary containing:
      - api_name
      - anomaly_types (list of detected anomalies)
      - severity ("critical" or "warning")
      - raw_data (dict of input)
    """
    is_valid, api_name, status_code, response_time_ms, records_returned = validate_api_record(record)

    anomalies: List[str] = []
    severities: List[str] = []

    # If the payload fails structural or value validation
    if not is_valid:
        anomalies.append(ANOMALY_INVALID_DATA)
        severities.append(SEVERITY_WARNING)
        
        # Safe raw_data dict for storage
        raw_dict = record if isinstance(record, dict) else {"raw_input": str(record)}
        return {
            "api_name": api_name,
            "anomaly_types": anomalies,
            "severity": SEVERITY_WARNING,
            "raw_data": raw_dict,
        }

    # Rule 1: response_time_ms > SLOW_THRESHOLD_MS -> HIGH_RESPONSE_TIME (warning)
    if response_time_ms > settings.SLOW_THRESHOLD_MS:
        anomalies.append(ANOMALY_HIGH_RESPONSE_TIME)
        severities.append(SEVERITY_WARNING)

    # Rule 2: status_code >= 500 -> SERVER_ERROR (critical)
    if status_code >= 500:
        anomalies.append(ANOMALY_SERVER_ERROR)
        severities.append(SEVERITY_CRITICAL)

    # Rule 3: status_code 400-499 -> CLIENT_ERROR (warning)
    elif 400 <= status_code <= 499:
        anomalies.append(ANOMALY_CLIENT_ERROR)
        severities.append(SEVERITY_WARNING)

    # Rule 4: records_returned == 0 -> ZERO_RECORDS
    # (critical if the status code is not 2xx, otherwise warning)
    if records_returned == 0:
        anomalies.append(ANOMALY_ZERO_RECORDS)
        if not (200 <= status_code <= 299):
            severities.append(SEVERITY_CRITICAL)
        else:
            severities.append(SEVERITY_WARNING)

    # If no anomalies detected, record is healthy
    if not anomalies:
        return None

    # Alert severity = highest severity among the anomalies found
    highest_severity = SEVERITY_CRITICAL if SEVERITY_CRITICAL in severities else SEVERITY_WARNING

    return {
        "api_name": api_name,
        "anomaly_types": anomalies,
        "severity": highest_severity,
        "raw_data": record,
    }


# Live / Historical Anomaly type constants
ANOMALY_CONNECTION_FAILURE = "CONNECTION_FAILURE"
ANOMALY_INTERMITTENT_FAILURE = "INTERMITTENT_FAILURE"
ANOMALY_SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
ANOMALY_RECORD_COUNT_DROP = "RECORD_COUNT_DROP"


def check_schema(body: Any, required_fields: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    """
    Validates whether objects in body contain all required fields and valid formats (e.g. '@' in email).
    Returns ONLY field names and item counts (items_checked, non_object_items, problem_fields),
    NEVER real data values (strictly preserving privacy).
    Returns None if no schema issues are found or required_fields is empty.
    """
    if not required_fields:
        return None

    items: List[Any] = []
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        items = [body]
    else:
        return {
            "items_checked": 0,
            "non_object_items": 1,
            "problem_fields": ["root_not_object"],
        }

    items_checked = len(items)
    non_object_items = 0
    problem_fields_set = set()

    for item in items:
        if not isinstance(item, dict):
            non_object_items += 1
            continue
        for field in required_fields:
            val = item.get(field)
            if val is None:
                problem_fields_set.add(field)
            elif field == "email" and ("@" not in str(val)):
                problem_fields_set.add("email")

    if problem_fields_set or non_object_items > 0:
        return {
            "items_checked": items_checked,
            "non_object_items": non_object_items,
            "problem_fields": sorted(list(problem_fields_set)),
        }

    return None


def detect_live_issues(
    history: List[Any],
    records_returned: Optional[int],
    prev_records: Optional[int],
    schema_problem: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Evaluates live API execution context, recent check history, record counts, and schema issues.
    Returns None if no live issues are detected.
    Otherwise returns {"anomaly_types": [...], "severity": "critical" | "warning"}.
    """
    anomalies: List[str] = []
    severities: List[str] = []

    # 1. Intermittent failure: >= 30% but < 100% failure rate over the last 10 checks (requires >= 5 checks)
    # A check counts as failure when status_code == 0 or >= 500
    if history and len(history) >= 5:
        total_checks = len(history)
        failed_checks = 0
        for item in history:
            sc = getattr(item, "status_code", None) if not isinstance(item, dict) else item.get("status_code")
            if sc == 0 or (sc is not None and sc >= 500):
                failed_checks += 1
        
        failure_rate = failed_checks / total_checks
        curr_sc = getattr(history[0], "status_code", None) if not isinstance(history[0], dict) else history[0].get("status_code")
        curr_failed = (curr_sc == 0 or (curr_sc is not None and curr_sc >= 500))
        if curr_failed and 0.30 <= failure_rate < 1.00:
            anomalies.append(ANOMALY_INTERMITTENT_FAILURE)
            severities.append(SEVERITY_CRITICAL)

    # 2. Record count drop: record count fell below 50% of previous count when previous >= 4
    if prev_records is not None and prev_records >= 4 and records_returned is not None:
        if records_returned < 0.5 * prev_records:
            anomalies.append(ANOMALY_RECORD_COUNT_DROP)
            severities.append(SEVERITY_WARNING)

    # 3. Schema mismatch: required fields missing/None or malformed
    if schema_problem:
        anomalies.append(ANOMALY_SCHEMA_MISMATCH)
        severities.append(SEVERITY_WARNING)

    if not anomalies:
        return None

    highest_severity = SEVERITY_CRITICAL if SEVERITY_CRITICAL in severities else SEVERITY_WARNING
    return {
        "anomaly_types": anomalies,
        "severity": highest_severity,
    }

