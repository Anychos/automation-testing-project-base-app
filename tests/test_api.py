from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import jwt
import pytest
from app.config import settings
from app.db import get_db
from app.domain import clock
from app.main import app
from app.worker import process_outbox
from sqlalchemy.exc import SQLAlchemyError


def next_weekday(days=1):
    day = datetime.now(ZoneInfo("Europe/Moscow")).date() + timedelta(days=days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()

def room(client, admin):
    response = client.post("/api/rooms", headers=admin, json={"name": "Meeting", "capacity": 4, "price_per_30min_kopeks": 50000})
    assert response.status_code == 201, response.text
    return response.json()

def booking_payload(room_id, **changes):
    return {"room_id": room_id, "title": "Team meeting", "booking_date": next_weekday(), "start_time": "10:00", "duration_minutes": 60, "attendees": 4} | changes

def book(client, user, room_id, **changes):
    return client.post("/api/bookings", headers=user, json=booking_payload(room_id, **changes))

def test_openapi_exposes_single_bearer_authorization(auth):
    client, _, _, _ = auth
    schema = client.get("/openapi.json").json()
    bearer = schema["components"]["securitySchemes"]["BearerAuth"]

    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    assert bearer["bearerFormat"] == "JWT"
    assert schema["paths"]["/api/users/me"]["get"]["security"] == [{"BearerAuth": []}]
    assert "security" not in schema["paths"]["/api/auth/login"]["post"]

    room_list = schema["paths"]["/api/rooms"]["get"]
    assert [parameter["name"] for parameter in room_list["parameters"]] == [
        "include_inactive"
    ]
    assert "только активные" in room_list["parameters"][0]["description"]

    room_patch = schema["components"]["schemas"]["RoomPatch"]
    assert not room_patch.get("required")
    assert room_patch["properties"]["name"]["type"] == "string"
    assert room_patch["properties"]["capacity"]["type"] == "integer"
    assert room_patch["properties"]["is_active"]["type"] == "boolean"
    assert all(
        "default" not in field_schema
        for field_schema in room_patch["properties"].values()
    )

    live_response = schema["paths"]["/api/health/live"]["get"]["responses"]["200"]
    ready_responses = schema["paths"]["/api/health/ready"]["get"]["responses"]
    assert live_response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/HealthOut"
    )
    assert ready_responses["503"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")

def test_auth_registration_and_private_resources(auth):
    client, _, user, _admin = auth
    assert client.get("/api/users/me").status_code == 401
    assert client.get("/api/users/me", headers=user).json()["role"] == "USER"
    assert client.post("/api/auth/register", json={"email": "USER@example.com", "password": "password123"}).json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
    assert client.post("/api/auth/register", json={"email": "another@example.com", "password": "password123", "role": "ADMIN"}).status_code == 422
    assert client.post("/api/rooms", headers=user, json={"name": "Other", "capacity": 2, "price_per_30min_kopeks": 10000}).status_code == 403
    assert client.post("/api/auth/login", json={"email": "user@example.com", "password": "wrong"}).status_code == 401
    assert client.get("/api/users/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
    expired = jwt.encode({"sub": client.get("/api/users/me", headers=user).json()["id"], "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, settings.jwt_secret, algorithm="HS256")
    assert client.get("/api/users/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

@pytest.mark.parametrize("capacity,price,expected", [(1, 10000, 422), (2, 9999, 422), (10, 200000, 201), (11, 10000, 422)])
def test_room_boundaries(auth, capacity, price, expected):
    client, _, _, admin = auth
    response = client.post("/api/rooms", headers=admin, json={"name": "Boundary", "capacity": capacity, "price_per_30min_kopeks": price})
    assert response.status_code == expected

def test_room_visibility_and_rename_conflict(auth):
    client, _, user, admin = auth
    first = room(client, admin)
    second = client.post("/api/rooms", headers=admin, json={"name": "Second", "capacity": 2, "price_per_30min_kopeks": 10000}).json()
    assert client.patch(f"/api/rooms/{second['id']}", headers=admin, json={"name": "meeting"}).json()["error"]["code"] == "ROOM_NAME_ALREADY_EXISTS"
    assert client.patch(f"/api/rooms/{first['id']}", headers=admin, json={"is_active": False}).status_code == 200
    hidden = client.get(f"/api/rooms/{first['id']}", headers=user)
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "ROOM_NOT_FOUND"

    user_list = client.get("/api/rooms?include_inactive=true", headers=user)
    assert user_list.status_code == 200
    assert [item["id"] for item in user_list.json()] == [second["id"]]
    assert all(item["is_active"] for item in user_list.json())

    admin_list = client.get("/api/rooms?include_inactive=true", headers=admin)
    assert admin_list.status_code == 200
    assert [item["name"] for item in admin_list.json()] == ["Meeting", "Second"]
    assert {item["id"] for item in admin_list.json()} == {first["id"], second["id"]}


@pytest.mark.parametrize(
    "body",
    [
        {"name": None},
        {"capacity": None},
        {"price_per_30min_kopeks": None},
        {"is_active": None},
    ],
)
def test_room_patch_empty_is_noop_and_explicit_null_is_invalid(auth, body):
    client, _, _, admin = auth
    created = room(client, admin)

    empty_patch = client.patch(f"/api/rooms/{created['id']}", headers=admin, json={})
    assert empty_patch.status_code == 200
    assert empty_patch.json() == created

    null_patch = client.patch(
        f"/api/rooms/{created['id']}", headers=admin, json=body
    )
    assert null_patch.status_code == 422
    assert null_patch.json()["error"]["code"] == "VALIDATION_ERROR"


def test_health_contract_and_database_unavailable(environment):
    client, _ = environment

    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/health/live").json() == {"status": "ok"}
    assert client.get("/api/health/ready").status_code == 200
    assert client.get("/api/health/ready").json() == {"status": "ok"}

    class UnavailableDatabase:
        def execute(self, _statement):
            raise SQLAlchemyError("database unavailable")

    original_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = UnavailableDatabase
    try:
        unavailable = client.get("/api/health/ready")
    finally:
        app.dependency_overrides[get_db] = original_override

    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "error": {
            "code": "DATABASE_UNAVAILABLE",
            "message": "База данных недоступна",
        }
    }

def test_delete_room_deactivates_it_and_preserves_bookings(auth):
    client, _, user, admin = auth
    created_room = room(client, admin)
    existing_booking = book(client, user, created_room["id"])
    assert existing_booking.status_code == 201
    path = f"/api/rooms/{created_room['id']}"

    assert client.delete(path).status_code == 401
    assert client.delete(path, headers=user).status_code == 403
    assert client.get(path, headers=user).status_code == 200

    deleted = client.delete(path, headers=admin)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.delete(path, headers=admin).status_code == 204
    assert client.get(path, headers=user).status_code == 404
    assert client.get(path, headers=admin).json()["is_active"] is False
    assert client.get(f"/api/bookings/{existing_booking.json()['id']}", headers=user).status_code == 200
    new_booking = book(client, user, created_room["id"])
    assert new_booking.status_code == 409
    assert new_booking.json()["error"]["code"] == "ROOM_INACTIVE"
    missing_room = client.delete(f"/api/rooms/{uuid4()}", headers=admin)
    assert missing_room.status_code == 404
    assert missing_room.json()["error"]["code"] == "ROOM_NOT_FOUND"

@pytest.mark.parametrize("changes,field", [
    ({"title": "ab"}, "title"), ({"title": "x" * 61}, "title"),
    ({"attendees": 0}, "attendees"), ({"attendees": 5}, "attendees"),
    ({"duration_minutes": 45}, "duration_minutes"),
    ({"duration_minutes": 30.0}, "duration_minutes"),
    ({"duration_minutes": "30"}, "duration_minutes"),
    ({"attendees": 1.5}, "attendees"),
    ({"booking_date": "2026/10/27"}, "booking_date"),
    ({"start_time": "08:30"}, "start_time"), ({"start_time": "09:15"}, "start_time"),
    ({"start_time": "20:30", "duration_minutes": 60}, "duration_minutes"),
    ({"booking_date": datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()}, "booking_date"),
    ({"booking_date": (datetime.now(ZoneInfo("Europe/Moscow")).date() + timedelta(days=15)).isoformat()}, "booking_date"),
])
def test_booking_boundaries(auth, changes, field):
    client, _, user, admin = auth
    result = book(client, user, room(client, admin)["id"], **changes)
    assert result.status_code == 422
    assert field in str(result.json()["error"]["fields"])

@pytest.mark.parametrize("changes", [
    {"title": "abc", "attendees": 1},
    {"title": "x" * 60, "attendees": 4},
    {"start_time": "20:30", "duration_minutes": 30},
])
def test_valid_booking_boundaries(auth, changes):
    client, _, user, admin = auth
    assert book(client, user, room(client, admin)["id"], **changes).status_code == 201

def test_weekend_is_rejected(auth):
    client, _, user, admin = auth
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    assert book(client, user, room(client, admin)["id"], booking_date=saturday.isoformat()).status_code == 422

def test_overlap_adjacent_price_snapshot_and_ownership(auth):
    client, _, user, admin = auth
    meeting = room(client, admin)
    first = book(client, user, meeting["id"])
    assert first.status_code == 201, first.text
    assert first.json()["total_price_kopeks"] == 100000
    assert book(client, user, meeting["id"], start_time="10:30").json()["error"]["code"] == "TIME_SLOT_OCCUPIED"
    assert book(client, user, meeting["id"], start_time="11:00", duration_minutes=30).status_code == 201
    assert client.patch(f"/api/rooms/{meeting['id']}", headers=admin, json={"price_per_30min_kopeks": 60000}).status_code == 200
    assert client.get(f"/api/bookings/{first.json()['id']}", headers=user).json()["total_price_kopeks"] == 100000
    assert client.post("/api/auth/register", json={"email": "other@example.com", "password": "password123"}).status_code == 201
    other_token = client.post("/api/auth/login", json={"email": "other@example.com", "password": "password123"}).json()["access_token"]
    other = {"Authorization": f"Bearer {other_token}"}
    assert client.get(f"/api/bookings/{first.json()['id']}", headers=other).json()["error"]["code"] == "BOOKING_NOT_FOUND"
    assert client.post(f"/api/bookings/{first.json()['id']}/cancel", headers=other).status_code == 404


def test_booking_list_filters_by_owner_and_sorts_without_pagination(auth):
    client, _, user, admin = auth
    meeting = room(client, admin)
    first = book(
        client,
        user,
        meeting["id"],
        start_time="09:00",
        duration_minutes=30,
    ).json()
    second = book(
        client,
        user,
        meeting["id"],
        start_time="09:30",
        duration_minutes=30,
    ).json()

    assert client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "password123"},
    ).status_code == 201
    other_token = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "password123"},
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {other_token}"}
    third = book(
        client,
        other,
        meeting["id"],
        start_time="10:00",
        duration_minutes=30,
    ).json()

    user_items = client.get("/api/bookings", headers=user).json()
    admin_items = client.get("/api/bookings", headers=admin).json()

    assert [item["id"] for item in user_items] == [second["id"], first["id"]]
    assert [item["id"] for item in admin_items] == [
        third["id"],
        second["id"],
        first["id"],
    ]
    assert [item["created_at"] for item in admin_items] == sorted(
        (item["created_at"] for item in admin_items), reverse=True
    )

def test_create_booking_error_priority(auth):
    client, _, user, admin = auth
    meeting = room(client, admin)
    assert client.patch(f"/api/rooms/{meeting['id']}", headers=admin, json={"is_active": False}).status_code == 200
    inactive = book(client, user, meeting["id"], attendees=99)
    assert inactive.status_code == 409 and inactive.json()["error"]["code"] == "ROOM_INACTIVE"
    missing = book(client, user, "00000000-0000-0000-0000-000000000000", attendees=99)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "ROOM_NOT_FOUND"
    invalid_schema = book(client, user, meeting["id"], title="x")
    assert invalid_schema.status_code == 422

@pytest.mark.parametrize("scenario,status", [(None, "CONFIRMED"), ("failure", "PAYMENT_FAILED"), ("no_response", "PAYMENT_PENDING")])
def test_stub_payment(auth, monkeypatch, scenario, status):
    client, sessions, user, admin = auth
    booking = book(client, user, room(client, admin)["id"]).json()
    body = {} if scenario is None else {"test_scenario": scenario}
    response = client.post(f"/api/bookings/{booking['id']}/pay", headers=user, json=body)
    assert response.status_code == 202
    assert response.json()["status"] == "PAYMENT_PENDING"
    monkeypatch.setattr("app.worker.SessionLocal", sessions)
    process_outbox()
    assert client.get(f"/api/bookings/{booking['id']}", headers=user).json()["status"] == status

def test_cancel_and_expiration(auth, monkeypatch):
    client, _, user, admin = auth
    meeting = room(client, admin)
    booking = book(client, user, meeting["id"]).json()
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=user).json()["status"] == "CANCELLED"
    assert client.post(f"/api/bookings/{booking['id']}/pay", headers=user).status_code == 409
    assert book(client, user, meeting["id"]).status_code == 201
    latest = client.get("/api/bookings", headers=user).json()[0]
    expiry = datetime.fromisoformat(latest["expires_at"]).replace(tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "now", lambda: expiry)
    assert client.get(f"/api/bookings/{latest['id']}", headers=user).json()["status"] == "EXPIRED"
    assert client.post(f"/api/bookings/{latest['id']}/pay", headers=user).status_code == 409
