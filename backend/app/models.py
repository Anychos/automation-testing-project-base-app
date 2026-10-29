import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('USER', 'ADMIN')", name="ck_users_role"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(5), nullable=False, default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    bookings = relationship("Booking", back_populates="user")

Index("uq_users_lower_email", func.lower(User.email), unique=True)

class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("capacity BETWEEN 2 AND 10", name="ck_rooms_capacity"),
        CheckConstraint("price_per_30min_kopeks BETWEEN 10000 AND 200000", name="ck_rooms_price"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_per_30min_kopeks: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bookings = relationship("Booking", back_populates="room")

Index("uq_rooms_lower_name", func.lower(Room.name), unique=True)

class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("status IN ('CREATED','PAYMENT_PENDING','CONFIRMED','PAYMENT_FAILED','CANCELLED','EXPIRED')", name="ck_bookings_status"),
        CheckConstraint("duration_minutes IN (30,60,90,120)", name="ck_bookings_duration"),
        CheckConstraint("attendees >= 1", name="ck_bookings_attendees"),
        CheckConstraint("total_price_kopeks > 0", name="ck_bookings_price"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("rooms.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(60), nullable=False)
    booking_date = mapped_column(Date, nullable=False)
    start_time = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    attendees: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price_kopeks: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payment_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    user = relationship("User", back_populates="bookings")
    room = relationship("Room", back_populates="bookings")

    @property
    def end_time(self):
        return (datetime.combine(self.booking_date, self.start_time) + timedelta(minutes=self.duration_minutes)).time()

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bookings.id"), nullable=False)
    payload: Mapped[str] = mapped_column(String(2000), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

class ProcessedPaymentEvent(Base):
    __tablename__ = "processed_payment_events"
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
