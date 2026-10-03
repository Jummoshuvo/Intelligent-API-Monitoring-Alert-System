import os
from pathlib import Path
from dotenv import load_dotenv

# Locate and load .env file from backend directory or parent directory
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()


# Application configuration settings
class Settings:
    """Holds environment settings and threshold constants."""
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    SLOW_THRESHOLD_MS: int = int(os.getenv("SLOW_THRESHOLD_MS", "3000"))

    # Supabase PostgreSQL connection string (required)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()

    # Scheduler: how often (seconds) the monitored APIs are checked
    CHECK_INTERVAL_SEC: int = int(os.getenv("CHECK_INTERVAL_SEC", "30"))

    # Email alert settings (Gmail SMTP with App Password)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "").strip()
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "").replace(" ", "").strip()
    ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "").strip()
    ALERT_COOLDOWN_MIN: int = int(os.getenv("ALERT_COOLDOWN_MIN", "15"))

    def __init__(self):
        if not self.DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Add your Supabase connection string to the .env file."
            )


settings = Settings()