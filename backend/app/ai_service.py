import asyncio
from typing import Dict, Any, List, Tuple
from google import genai
from app.config import settings
from app.logger import logger

# Prompt template for Gemini alert generation
PROMPT_TEMPLATE = """You are an API monitoring assistant. Write a short, human-readable alert message for an API incident.

FACTS:
- API Name: {api_name}
- Status Code: {status_code}
- Response Time: {response_time_ms} ms
- Records Returned: {records_returned}
- Detected Anomalies: {anomaly_types}
- Severity: {severity}

RULES:
1. Write exactly 1-2 sentences in plain English.
2. Name the API and mention the real numbers (status code, response time, records returned).
3. Suggest a likely cause or next step (e.g., check server logs, latency, database issue).
4. Do NOT use markdown (no asterisks, no quotes, no bold, no bullet points).
5. Do NOT invent facts beyond the provided data.
"""


def build_fallback_message(facts: Dict[str, Any]) -> str:
    """
    Builds a reliable, readable fallback message when AI is unavailable or fails.
    """
    api_name = facts.get("api_name", "Unknown API")
    status_code = facts.get("status_code", "N/A")
    response_time_ms = facts.get("response_time_ms", "N/A")
    records_returned = facts.get("records_returned", "N/A")
    anomaly_types = facts.get("anomaly_types", [])
    anomalies_str = ", ".join(anomaly_types)

    # Contextual template messages based on dominant anomaly
    if "CONNECTION_FAILURE" in anomaly_types:
        return f"{api_name} connection failed (status {status_code}). Endpoint is unreachable or timed out."
    if "INTERMITTENT_FAILURE" in anomaly_types:
        return f"{api_name} is experiencing intermittent failures with repeated error responses over recent checks."
    if "SERVER_ERROR" in anomaly_types:
        return f"{api_name} failed with status {status_code} and returned {records_returned} records. Possible outage or data issue."
    if "HIGH_RESPONSE_TIME" in anomaly_types:
        return f"{api_name} responded with status {status_code}, taking {response_time_ms} ms. Watch for degradation."
    if "SCHEMA_MISMATCH" in anomaly_types:
        return f"{api_name} response schema mismatch: missing required fields or invalid formatting detected."
    if "RECORD_COUNT_DROP" in anomaly_types:
        return f"{api_name} record count dropped significantly ({records_returned} records returned). Investigate potential data loss."
    if "CLIENT_ERROR" in anomaly_types:
        return f"{api_name} returned client error status {status_code} with {records_returned} records. Check request parameters."
    if "ZERO_RECORDS" in anomaly_types:
        return f"{api_name} returned status {status_code} but returned 0 records. Check data source availability."
    if "INVALID_DATA" in anomaly_types:
        return f"{api_name} reported invalid or malformed metric data. Verify logging format."

    return f"{api_name} reported {anomalies_str} (status {status_code}, {response_time_ms} ms, {records_returned} records)."



async def generate_alert_message(
    facts: Dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> Tuple[str, str]:
    """
    Generates an alert message using Gemini.
    Falls back to a template message if the API key is missing or an error occurs.
    Returns (message_text, message_source: 'ai' | 'fallback').
    """
    api_name = facts.get("api_name", "API")

    # If no API key is provided, use fallback immediately
    if not settings.GEMINI_API_KEY:
        logger.info(f"No GEMINI_API_KEY provided; using fallback template for {api_name}.")
        return build_fallback_message(facts), "fallback"

    async with semaphore:
        try:
            # Format the prompt with detected facts
            prompt = PROMPT_TEMPLATE.format(
                api_name=facts.get("api_name"),
                status_code=facts.get("status_code", "N/A"),
                response_time_ms=facts.get("response_time_ms", "N/A"),
                records_returned=facts.get("records_returned", "N/A"),
                anomaly_types=", ".join(facts.get("anomaly_types", [])),
                severity=facts.get("severity", "warning"),
            )

            # Define blocking Gemini call
            def call_gemini():
                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                response = client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                )
                return response.text.strip() if response.text else ""

            # Execute with a 10 second timeout
            message = await asyncio.wait_for(
                asyncio.to_thread(call_gemini),
                timeout=10.0,
            )

            if not message:
                raise ValueError("Received empty response from Gemini.")

            # Clean any accidental quotes or formatting
            cleaned_message = message.replace('"', '').replace('**', '').strip()
            logger.info(f"AI alert successfully generated for {api_name}.")
            return cleaned_message, "ai"

        except asyncio.TimeoutError:
            logger.error(f"Gemini call timed out (10s) for {api_name}. Using fallback.")
            return build_fallback_message(facts), "fallback"
        except Exception as exc:
            logger.error(f"Gemini call failed for {api_name}: {exc}. Using fallback.")
            return build_fallback_message(facts), "fallback"


async def generate_batch_messages(
    anomalies: List[Dict[str, Any]]
) -> List[Tuple[str, str]]:
    """
    Processes all detected anomalies concurrently using asyncio.gather with Semaphore(5).
    """
    if not anomalies:
        return []

    semaphore = asyncio.Semaphore(5)
    tasks = [generate_alert_message(item, semaphore) for item in anomalies]
    return await asyncio.gather(*tasks)
