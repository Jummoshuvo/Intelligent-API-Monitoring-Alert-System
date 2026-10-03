# Intelligent API Monitoring & Alert System

An automated, intelligent monitoring and alerting platform designed for operational and healthcare API architectures. It ingests batch API response metrics, detects anomalies using deterministic threshold rules, generates human-readable incident summaries using Google Gemini (with an automated template fallback), and persists alerts in a cloud-hosted **Supabase (PostgreSQL)** database while presenting active incidents on a modern, real-time web dashboard.

---

## 🏗️ Architecture Flow

```mermaid
flowchart LR
    A["API Telemetry Input<br>(POST /monitor)"] --> B["Rule-based Detector<br>(detector.py)"]
    B -- "Healthy" --> C["Update Health Metrics"]
    B -- "Anomalies Detected" --> D["AI Alert Generator<br>(Gemini + Fallback)"]
    D --> E[("Supabase Database<br>(PostgreSQL 'alerts' Table)")]
    E --> F["Live Web Dashboard<br>(HTML5 + Tailwind CSS + JS)"]
    C --> F
```

---

## 🗄️ Database Architecture

The system uses **Supabase (PostgreSQL)** for persistence, managed via SQLAlchemy ORM with connection pooling.

### Connection & Configuration
- **Engine**: SQLAlchemy with `psycopg2` driver.
- **Connection URL Format**: `postgresql+psycopg2://<USER>:<PASSWORD>@<HOST>:5432/<DATABASE>`
- **Pool Settings**:
  - `pool_pre_ping=True` (automatically recovers dropped or stale connections)
  - `pool_recycle=300` (recycles connections every 5 minutes)
  - `pool_size=5`, `max_overflow=5`

### Database Schema (`alerts` table)

| Column | Type | Constraints / Description |
| :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Auto-increment, Indexed |
| `api_name` | `String(255)` | Name of the monitored API service, Indexed |
| `message` | `Text` | Human-readable alert summary (AI-generated or fallback) |
| `message_source` | `String(50)` | `"ai"` (Google Gemini) or `"fallback"` (rule template) |
| `anomaly_types` | `JSON` | Array of detected anomaly codes (e.g. `["SERVER_ERROR", "ZERO_RECORDS"]`) |
| `severity` | `String(20)` | Alert severity: `"critical"` or `"warning"` |
| `status` | `String(20)` | Status: `"active"` (default) or `"resolved"` |
| `raw_data` | `JSON` | Complete original payload ingested for the incident |
| `created_at` | `DateTime` | UTC timestamp when alert was generated |
| `resolved_at` | `DateTime` | UTC timestamp when alert was marked resolved (nullable) |

---

## 🔍 Anomaly Detection Rules

All anomaly evaluation is performed deterministically in `backend/app/detector.py` before any AI processing:

| Anomaly Condition | Anomaly Flag | Severity | Description |
| :--- | :--- | :--- | :--- |
| `response_time_ms > 3000` | `HIGH_RESPONSE_TIME` | **Warning** | Response latency exceeds acceptable threshold (3s SLA) |
| `status_code >= 500` | `SERVER_ERROR` | **Critical** | Server-side error, outage, or 5xx crash |
| `status_code` in `400..499` | `CLIENT_ERROR` | **Warning** | Client error, authentication failure (401/403), or invalid parameter (400) |
| `records_returned == 0` | `ZERO_RECORDS` | **Critical** if status ≠ 2xx<br>**Warning** if status == 2xx | No data records returned by the endpoint |
| Missing/malformed fields or negative values | `INVALID_DATA` | **Warning** | Payload failed structural validation (e.g., negative latency) |

- **Severity Resolution**: The alert severity is determined by the highest severity among detected anomalies (`critical` > `warning`).
- **Batch Resiliency**: Each record in an ingested batch is evaluated independently; an invalid or errored record will not block other records.

---

## 🚀 Setup & Installation

### 1. Prerequisites
- Python 3.10+
- Active Supabase project (PostgreSQL database)
- Google Gemini API Key (optional, built-in fallback operates if omitted)

### 2. Create Virtual Environment & Install Dependencies

```bash
# Navigate to the backend directory
cd backend

# Create a virtual environment
python -m venv venv

# Activate virtual environment
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
.\venv\Scripts\activate.bat
# On macOS / Linux:
source venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the `backend/` directory (or copy from `.env.example`):

```bash
cp .env.example .env
```

Configure your `.env` file:

```env
# Google Gemini API Key (leave empty to use template fallback)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Latency threshold for HIGH_RESPONSE_TIME anomaly (in ms)
SLOW_THRESHOLD_MS=3000

# Supabase PostgreSQL connection string
DATABASE_URL=postgresql+psycopg2://postgres.your-project-ref:your-password@aws-0-region.pooler.supabase.com:5432/postgres
```

---

## ▶️ Running the Application

### 1. Start the FastAPI Server

From the `backend` folder (with virtual environment activated):

```bash
python -m uvicorn app.main:app --reload --port 8000
```

### 2. Access the Dashboard & API Docs

- **Web Dashboard**: Open [http://localhost:8000/](http://localhost:8000/) in your browser.
- **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📡 API Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/monitor` | Ingests custom batch/single API metric records and detects anomalies |
| `POST` | `/monitor/sample` | Ingests and evaluates pre-configured `backend/data/sample_input.json` |
| `GET` | `/alerts` | Fetches alerts list (Supports query params `status=active\|resolved\|all`, `severity=critical\|warning`) |
| `PATCH` | `/alerts/{id}/resolve` | Marks a specific alert as resolved (`status="resolved"`, `resolved_at=now`) |
| `GET` | `/alerts/summary` | Returns latest run metrics (total, healthy) and active counts (critical, warning) |
| `GET` | `/health` | Service health check returning `{"status": "ok"}` |

### Example Request: Batch Monitoring (`POST /monitor`)

```bash
curl -X POST "http://localhost:8000/monitor" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "api_name": "PatientRecordsAPI",
      "status_code": 200,
      "response_time_ms": 240,
      "records_returned": 45
    },
    {
      "api_name": "LabResultsAPI",
      "status_code": 200,
      "response_time_ms": 4200,
      "records_returned": 120
    },
    {
      "api_name": "AppointmentAPI",
      "status_code": 500,
      "response_time_ms": 5500,
      "records_returned": 0
    }
  ]'
```

---

## 🖥️ Dashboard Features

1. **Live Summary Cards**: Real-time counter cards showing total APIs evaluated, healthy count, active critical alerts, and active warning alerts.
2. **Interactive Severity Tabs**: Quick filters for **All**, **Critical**, and **Warning** incidents.
3. **Live Search**: Instant client-side search filtering by API name.
4. **Custom Input Modal**: Ingest any JSON payload or use pre-set templates (`+ Critical Anomaly`, `+ Warning Anomaly`, `+ Healthy API`) directly from the UI.
5. **One-Click Sample Run**: Execute tests using `sample_input.json` with a single click.
6. **Incident Resolution**: Resolve individual alerts or bulk resolve all visible alerts with live badge updates.
7. **Raw Payload Inspector**: Expandable JSON viewer for complete telemetry inspection per incident.
