import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Booking, ProcessedPaymentEvent

logger = logging.getLogger(__name__)
ACTIVE = ("CREATED", "PAYMENT_PENDING")
OCCUPYING = ("CREATED", "PAYMENT_PENDING", "CONFIRMED")

class Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

clock = Clock()

def expire_due(db: Session, now: datetime) -> None:
    db.execute(update(Booking).where(Booking.status.in_(ACTIVE), Booking.expires_at <= now)
               .values(status="EXPIRED", updated_at=now))

def expire_one(booking: Booking, now: datetime) -> None:
    expires_at = booking.expires_at.replace(tzinfo=timezone.utc) if booking.expires_at.tzinfo is None else booking.expires_at
    if booking.status in ACTIVE and now >= expires_at:
        booking.status = "EXPIRED"
        booking.updated_at = now

def validate_booking_time(data, now: datetime) -> dict[str, str]:
    errors = {}
    today = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    if data.booking_date <= today or data.booking_date > today + timedelta(days=14) or data.booking_date.weekday() >= 5:
        errors["booking_date"] = "Нужен будний день с завтра по следующие 14 дней"
    start = data.start_time.hour * 60 + data.start_time.minute
    if data.start_time.second or data.start_time.microsecond or data.start_time.minute not in (0, 30) or start < 540 or start > 1230:
        errors["start_time"] = "Начало: с 09:00 до 20:30, шаг 30 минут"
    if start + data.duration_minutes > 1260:
        errors["duration_minutes"] = "Бронь должна закончиться до 21:00"
    return errors

def overlaps(a, b) -> bool:
    a_start = a.start_time.hour * 60 + a.start_time.minute
    b_start = b.start_time.hour * 60 + b.start_time.minute
    return a_start < b_start + b.duration_minutes and b_start < a_start + a.duration_minutes


def log_ignored_payment_result(reason: str, *, level: int = logging.WARNING) -> None:
    """Emit stable machine-readable fields without making log text a contract."""
    logger.log(
        level,
        "Payment result ignored",
        extra={"event": "payment_result_ignored", "reason": reason},
    )


def apply_payment_result(db: Session, event: dict, now: datetime) -> None:
    try:
        event_id = event["event_id"]
        event_type = event["event_type"]
        correlation_id = event["correlation_id"]
        booking_id = event["booking_id"]
        if event.get("version") != 1 or event_type not in ("PaymentSucceeded", "PaymentFailed"):
            log_ignored_payment_result("invalid_contract")
            return
        from uuid import UUID
        event_id, correlation_id, booking_id = map(UUID, (event_id, correlation_id, booking_id))
    except (KeyError, ValueError, TypeError):
        log_ignored_payment_result("invalid_contract")
        return
    if db.get(ProcessedPaymentEvent, event_id):
        log_ignored_payment_result("duplicate", level=logging.INFO)
        return
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking or booking.payment_request_id != correlation_id:
        log_ignored_payment_result("booking_or_correlation_mismatch")
        db.add(ProcessedPaymentEvent(event_id=event_id, processed_at=now))
        db.commit()
        return
    expire_one(booking, now)
    if booking.status == "PAYMENT_PENDING":
        booking.status = "CONFIRMED" if event_type == "PaymentSucceeded" else "PAYMENT_FAILED"
        booking.updated_at = now
    else:
        log_ignored_payment_result("terminal_status", level=logging.INFO)
    db.add(ProcessedPaymentEvent(event_id=event_id, processed_at=now))
    db.commit()
