"""Run with python -m app.seed seed|reset-test-data inside the backend container."""
import os
import sys

from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.models import Booking, OutboxEvent, ProcessedPaymentEvent, Room, User
from app.security import hash_password

ROOMS = (("Small", 2, 30000), ("Medium", 4, 50000), ("Large", 8, 80000))

def guard():
    if settings.app_env not in ("development", "test") or os.getenv("CONFIRM_TEST_DATA_OPERATION") != "yes":
        raise SystemExit("Requires APP_ENV=development|test and CONFIRM_TEST_DATA_OPERATION=yes")

def seed_data(db):
    for name, capacity, price in ROOMS:
        if not db.scalar(select(Room).where(Room.name == name)):
            db.add(Room(name=name, capacity=capacity, price_per_30min_kopeks=price, is_active=True))
    for prefix, role in (("USER", "USER"), ("ADMIN", "ADMIN")):
        email = os.getenv(f"SEED_{prefix}_EMAIL")
        password = os.getenv(f"SEED_{prefix}_PASSWORD")
        if not email or not password or not 8 <= len(password) <= 64:
            raise ValueError(f"SEED_{prefix}_EMAIL/PASSWORD required")
        email = email.strip().lower()
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(email=email, password_hash=hash_password(password), role=role))

def seed():
    guard()
    with SessionLocal.begin() as db:
        seed_data(db)
    print("Seed complete")

def reset_data(db):
    db.execute(delete(ProcessedPaymentEvent))
    db.execute(delete(OutboxEvent))
    db.execute(delete(Booking))
    db.execute(delete(Room))
    db.execute(delete(User))
    seed_data(db)

def reset_test_data():
    guard()
    with SessionLocal.begin() as db:
        reset_data(db)
    print("Test data reset complete")

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("seed", "reset-test-data"):
        raise SystemExit("Usage: python -m app.seed seed|reset-test-data")
    {"seed": seed, "reset-test-data": reset_test_data}[sys.argv[1]]()
