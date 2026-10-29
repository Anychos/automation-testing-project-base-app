from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import uuid

import app.main as main
import pytest
from app.models import Booking, OutboxEvent, ProcessedPaymentEvent, Room, User
from sqlalchemy import func, select


def test_reset_restores_seed_and_invalidates_tokens(auth, monkeypatch):
    client, sessions, user_headers, admin_headers = auth
    for key, value in {
        "SEED_USER_EMAIL": "seed@example.com", "SEED_USER_PASSWORD": "password123",
        "SEED_ADMIN_EMAIL": "seedadmin@example.com", "SEED_ADMIN_PASSWORD": "password123",
    }.items():
        monkeypatch.setenv(key, value)
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "user@example.com"))
        room = Room(name="Temporary", capacity=2, price_per_30min_kopeks=30000)
        db.add(room)
        db.flush()
        now = datetime.now(timezone.utc)
        booking = Booking(user_id=user.id, room_id=room.id, title="Test", booking_date=date.today(),
                          start_time=time(10), duration_minutes=30, attendees=1, total_price_kopeks=30000,
                          status="CREATED", created_at=now, updated_at=now, expires_at=now + timedelta(minutes=15))
        db.add(booking)
        db.flush()
        db.add(OutboxEvent(event_id=uuid.uuid4(), booking_id=booking.id, payload="{}"))
        db.add(ProcessedPaymentEvent(event_id=uuid.uuid4()))
    assert client.post('/api/test-data/reset', headers=admin_headers, json={"confirm": "reset-test-data"}).status_code == 204
    with sessions() as db:
        assert set(db.scalars(select(User.email))) == {"seed@example.com", "seedadmin@example.com"}
        assert set(db.scalars(select(Room.name))) == {"Small", "Medium", "Large"}
        for model in (Booking, OutboxEvent, ProcessedPaymentEvent):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert client.get('/api/users/me', headers=user_headers).status_code == 401
    assert client.get('/api/users/me', headers=admin_headers).status_code == 401
    assert client.post('/api/auth/login', json={"email": "seedadmin@example.com", "password": "password123"}).status_code == 200


def test_reset_restrictions_and_rollback(auth, monkeypatch):
    client, sessions, user_headers, admin_headers = auth
    payload = {"confirm": "reset-test-data"}
    assert client.post('/api/test-data/reset', json=payload).status_code == 401
    assert client.post('/api/test-data/reset', headers=user_headers, json=payload).status_code == 403
    assert client.post('/api/test-data/reset', headers=admin_headers, json={"confirm": "yes"}).status_code == 422
    for settings in (replace(main.settings, test_mode=False), replace(main.settings, app_env="production")):
        monkeypatch.setattr(main, "settings", settings)
        assert client.post('/api/test-data/reset', headers=admin_headers, json=payload).status_code == 403
    monkeypatch.setattr(main, "settings", replace(main.settings, test_mode=True, app_env="test"))
    monkeypatch.delenv("SEED_USER_EMAIL", raising=False)
    with pytest.raises(ValueError, match="SEED_USER_EMAIL/PASSWORD required"):
        client.post('/api/test-data/reset', headers=admin_headers, json=payload)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2
