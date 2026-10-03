from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.database import init_db
from app.monitor import run_checks
from app.routes import router
from app.logger import logger

# Initialize database tables
init_db()

# Background scheduler that checks the monitored APIs periodically
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts the background checker when the app starts, stops it on shutdown."""
    scheduler.add_job(
        run_checks,
        "interval",
        seconds=settings.CHECK_INTERVAL_SEC,
        max_instances=1,
        next_run_time=datetime.now(),  # first check right at startup
    )
    scheduler.start()
    logger.info(f"Scheduler started: checking every {settings.CHECK_INTERVAL_SEC}s")
    yield
    scheduler.shutdown()


# Create FastAPI application instance
app = FastAPI(
    title="Intelligent API Monitoring & Alert System",
    description="Monitors API health, detects anomalies with rules, and generates readable alerts via AI.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for all origins so the frontend can be opened directly via file:// or another port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handlers returning {"error": "clear message"}
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handles standard HTTPExceptions."""
    logger.error(f"HTTP error {exc.status_code} on {request.url.path}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles request body or parameter validation errors."""
    logger.error(f"Validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"error": "Invalid request payload format."},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handles unexpected runtime exceptions."""
    logger.error(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": f"Internal server error: {str(exc)}"},
    )

# Include API endpoints under root /
app.include_router(router)

# Mount frontend directory to serve dashboard at http://localhost:8000/
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
else:
    logger.warning(f"Frontend directory not found at {frontend_dir}")