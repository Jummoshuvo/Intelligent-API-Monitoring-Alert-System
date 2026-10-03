from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# Supabase (PostgreSQL) database engine
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # Automatically replaces dead connections
    pool_recycle=300,     # Refresh connections every 5 minutes
    pool_size=5,
    max_overflow=5,
)

# Session factory for database operations
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for SQLAlchemy models
Base = declarative_base()


def get_db():
    """Dependency that provides a database session and closes it after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Creates all database tables if they do not exist."""
    Base.metadata.create_all(bind=engine)