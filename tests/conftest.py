import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET"] = "unit-tests-only-secret"
os.environ["TEST_MODE"] = "true"
os.environ["PAYMENT_MODE"] = "stub"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest
from app.db import Base, get_db
from app.main import app
from app.models import User
from app.security import hash_password
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def environment(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    def test_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = test_db
    with sessions.begin() as db:
        db.add(User(email="admin@example.com", password_hash=hash_password("password123"), role="ADMIN"))
    client = TestClient(app)
    yield client, sessions
    app.dependency_overrides.clear()
    engine.dispose()

@pytest.fixture
def auth(environment):
    client, sessions = environment
    registration = client.post("/api/auth/register", json={"email": "user@example.com", "password": "password123"})
    assert registration.status_code == 201, registration.text
    user_token = client.post("/api/auth/login", json={"email": "user@example.com", "password": "password123"}).json()["access_token"]
    admin_token = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "password123"}).json()["access_token"]
    return client, sessions, {"Authorization": f"Bearer {user_token}"}, {"Authorization": f"Bearer {admin_token}"}
