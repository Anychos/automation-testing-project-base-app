import logging
from datetime import timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.domain import apply_payment_result, clock
from app.models import Booking, ProcessedPaymentEvent
from sqlalchemy import select
from test_api import book, room


def prepared(auth):
    client, sessions, user, admin = auth
    booking = book(client, user, room(client, admin)["id"]).json()
    assert client.post(f"/api/bookings/{booking['id']}/pay", headers=user).status_code == 202
    with sessions() as db:
        request_id = db.get(Booking, UUID(booking["id"])).payment_request_id
    return client, sessions, user, booking["id"], request_id

def result(booking_id, request_id, kind="PaymentSucceeded", event_id=None):
    return {"event_id": str(event_id or uuid4()), "event_type": kind, "version": 1,
            "occurred_at": clock.now().isoformat(), "correlation_id": str(request_id), "booking_id": booking_id}


def has_ignored_event(caplog, reason):
    return any(
        getattr(record, "event", None) == "payment_result_ignored"
        and getattr(record, "reason", None) == reason
        for record in caplog.records
    )

def test_duplicate_result_has_single_effect(auth, caplog):
    client, sessions, user, booking_id, request_id = prepared(auth)
    event = result(booking_id, request_id)
    with caplog.at_level(logging.INFO, logger="app.domain"), sessions() as db:
        apply_payment_result(db, event, clock.now())
        apply_payment_result(db, event, clock.now())
        assert len(db.scalars(select(ProcessedPaymentEvent)).all()) == 1
    assert client.get(f"/api/bookings/{booking_id}", headers=user).json()["status"] == "CONFIRMED"
    assert client.post(f"/api/bookings/{booking_id}/pay", headers=user).json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert has_ignored_event(caplog, "duplicate")

def test_failure_then_late_success_is_ignored(auth, caplog):
    client, sessions, user, booking_id, request_id = prepared(auth)
    with caplog.at_level(logging.INFO, logger="app.domain"), sessions() as db:
        apply_payment_result(db, result(booking_id, request_id, "PaymentFailed"), clock.now())
        apply_payment_result(db, result(booking_id, request_id), clock.now())
    assert client.get(f"/api/bookings/{booking_id}", headers=user).json()["status"] == "PAYMENT_FAILED"
    assert has_ignored_event(caplog, "terminal_status")

def test_cancel_then_success_is_ignored(auth):
    client, sessions, user, booking_id, request_id = prepared(auth)
    assert client.post(f"/api/bookings/{booking_id}/cancel", headers=user).json()["status"] == "CANCELLED"
    with sessions() as db:
        apply_payment_result(db, result(booking_id, request_id), clock.now())
    assert client.get(f"/api/bookings/{booking_id}", headers=user).json()["status"] == "CANCELLED"

def test_wrong_correlation_cannot_change_booking(auth, caplog):
    client, sessions, user, booking_id, _request_id = prepared(auth)
    with caplog.at_level(logging.WARNING, logger="app.domain"), sessions() as db:
        apply_payment_result(db, result(booking_id, uuid4()), clock.now())
    assert client.get(f"/api/bookings/{booking_id}", headers=user).json()["status"] == "PAYMENT_PENDING"
    assert has_ignored_event(caplog, "booking_or_correlation_mismatch")


def test_invalid_payment_event_cannot_change_booking(auth, caplog):
    client, sessions, user, booking_id, request_id = prepared(auth)
    invalid_event = result(booking_id, request_id)
    invalid_event["version"] = 2

    with caplog.at_level(logging.WARNING, logger="app.domain"), sessions() as db:
        apply_payment_result(db, invalid_event, clock.now())

    assert client.get(f"/api/bookings/{booking_id}", headers=user).json()["status"] == "PAYMENT_PENDING"
    assert has_ignored_event(caplog, "invalid_contract")

def test_pay_repeated_while_pending_creates_one_request(auth):
    client, sessions, user, booking_id, _ = prepared(auth)
    second = client.post(f"/api/bookings/{booking_id}/pay", headers=user)
    assert second.status_code == 409
    with sessions() as db:
        from app.models import OutboxEvent
        assert len(db.scalars(select(OutboxEvent)).all()) == 1

def test_disabled_mode_only_blocks_pay(auth, monkeypatch):
    client, _, user, admin = auth
    booking = book(client, user, room(client, admin)["id"]).json()
    monkeypatch.setattr("app.main.settings", SimpleNamespace(payment_mode="disabled", test_mode=True))
    pay = client.post(f"/api/bookings/{booking['id']}/pay", headers=user)
    assert pay.status_code == 503
    assert pay.json()["error"]["code"] == "PAYMENTS_UNAVAILABLE"
    assert client.get(f"/api/bookings/{booking['id']}", headers=user).status_code == 200
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=user).status_code == 200

def test_scenario_field_is_rejected_outside_test_mode(auth, monkeypatch):
    client, _, user, admin = auth
    booking = book(client, user, room(client, admin)["id"]).json()
    monkeypatch.setattr("app.main.settings", SimpleNamespace(payment_mode="stub", test_mode=False))
    response = client.post(f"/api/bookings/{booking['id']}/pay", headers=user, json={"test_scenario": "failure"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get(f"/api/bookings/{booking['id']}", headers=user).json()["status"] == "CREATED"

def test_expired_payment_success_is_ignored(auth):
    client, sessions, user, booking_id, request_id = prepared(auth)
    with sessions() as db:
        booking = db.get(Booking, UUID(booking_id))
        expiry = booking.expires_at.replace(tzinfo=timezone.utc)
        apply_payment_result(db, result(booking_id, request_id), expiry)
    assert client.get(f"/api/bookings/{booking_id}", headers=user).json()["status"] == "EXPIRED"
