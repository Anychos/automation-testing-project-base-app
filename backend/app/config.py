import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    payment_mode: str = os.getenv("PAYMENT_MODE", "stub")
    test_mode: bool = os.getenv("TEST_MODE", "false").lower() == "true"
    app_env: str = os.getenv("APP_ENV", "development")
    kafka_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

settings = Settings()
if not settings.database_url or not settings.jwt_secret:
    raise ValueError("DATABASE_URL and JWT_SECRET are required")
if settings.payment_mode not in {"stub", "kafka", "disabled"}:
    raise ValueError("PAYMENT_MODE must be stub, kafka or disabled")
