from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
# DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,        # ← detects broken connections
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 10}
    )
except Exception as e:
    raise RuntimeError(f"Failed to create DB engine: {e}")
# engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()