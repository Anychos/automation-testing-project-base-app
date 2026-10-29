import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from threading import Event, Thread

from fastapi import Depends, FastAPI, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.domain import (
    OCCUPYING,
    clock,
    expire_due,
    expire_one,
    overlaps,
    validate_booking_time,
)
from app.errors import AppError, install_errors
from app.models import Booking, OutboxEvent, Room, User
from app.schemas import (
    BookingIn,
    BookingOut,
    ErrorResponse,
    HealthOut,
    LoginIn,
    PayIn,
    RegisterIn,
    ResetDataIn,
    RoomFields,
    RoomOut,
    RoomPatch,
    TokenOut,
    UserOut,
)
from app.security import (
    admin_user,
    current_user,
    hash_password,
    issue_token,
    verify_password,
)
from app.worker import payment_loop
from app.seed import reset_data

logger = logging.getLogger(__name__)
stop_worker = Event()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop_worker.clear()
    worker = Thread(target=payment_loop, args=(stop_worker,), daemon=True)
    worker.start()
    yield
    stop_worker.set()
    worker.join(timeout=3)

app = FastAPI(
    title="BookingLab API",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Авторизация"},
        {"name": "Пользователи"},
        {"name": "Комнаты"},
        {"name": "Бронирования"},
        {"name": "Состояние сервиса"},
        {"name": "Тестовые данные"},
    ],
)
install_errors(app)

@app.post(
    "/api/test-data/reset", status_code=204, tags=["Тестовые данные"],
    description="Полностью очищает данные и восстанавливает начальные комнаты и пользователей. Только ADMIN при TEST_MODE=true и APP_ENV=development или test. Все прежние токены перестают действовать.",
)
def reset_test_data(data: ResetDataIn, _admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    if settings.app_env not in ("development", "test") or not settings.test_mode:
        raise AppError(403, "FORBIDDEN", "Сброс доступен только в тестовом режиме")
    try:
        reset_data(db)
        db.commit()
    except Exception:
        db.rollback()
        raise

def field_error(field: str, message: str):
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "Неверные данные", "fields": [{"field": field, "message": message}]}}, status_code=422)

def visible_booking(db: Session, booking_id: uuid.UUID, user: User, lock: bool = False) -> Booking:
    query = select(Booking).where(Booking.id == booking_id)
    if user.role != "ADMIN":
        query = query.where(Booking.user_id == user.id)
    if lock:
        query = query.with_for_update()
    booking = db.scalar(query)
    if not booking:
        raise AppError(404, "BOOKING_NOT_FOUND", "Бронь не найдена")
    previous_status = booking.status
    expire_one(booking, clock.now())
    if previous_status != booking.status:
        db.commit()
    return booking

@app.post("/api/auth/register", response_model=UserOut, status_code=201, tags=["Авторизация"])
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = str(data.email).strip().lower()
    if len(email) > 254:
        return field_error("email", "Email слишком длинный")
    user = User(email=email, password_hash=hash_password(data.password), role="USER", created_at=clock.now())
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "EMAIL_ALREADY_EXISTS", "Email уже зарегистрирован")
    db.refresh(user)
    return user

@app.post("/api/auth/login", response_model=TokenOut, tags=["Авторизация"])
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).strip().lower()))
    if not user or not verify_password(user.password_hash, data.password):
        raise AppError(401, "UNAUTHORIZED", "Неверный email или пароль")
    return TokenOut(access_token=issue_token(user))

@app.get("/api/users/me", response_model=UserOut, tags=["Пользователи"])
def me(user: User = Depends(current_user)):
    return user

@app.get(
    "/api/rooms",
    response_model=list[RoomOut],
    tags=["Комнаты"],
    description=(
        "Возвращает доступные комнаты без пагинации. USER всегда видит только активные "
        "комнаты; include_inactive=true расширяет результат только для ADMIN. "
        "Сортировка: name ASC без учёта регистра, затем id ASC."
    ),
)
def rooms(
    include_inactive: bool = Query(
        default=False,
        description=(
            "Для ADMIN включает неактивные комнаты. Для USER параметр принимается, "
            "но результат по-прежнему содержит только активные комнаты."
        ),
    ),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(Room).order_by(func.lower(Room.name), Room.id)
    if user.role != "ADMIN" or not include_inactive:
        query = query.where(Room.is_active.is_(True))
    return db.scalars(query).all()

@app.get(
    "/api/rooms/{room_id}",
    response_model=RoomOut,
    responses={
        404: {
            "model": ErrorResponse,
            "description": (
                "ROOM_NOT_FOUND: комната отсутствует либо неактивна и запрошена USER."
            ),
        }
    },
    tags=["Комнаты"],
)
def room_detail(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if not room or (not room.is_active and user.role != "ADMIN"):
        raise AppError(404, "ROOM_NOT_FOUND", "Комната не найдена")
    return room

@app.post("/api/rooms", response_model=RoomOut, status_code=201, tags=["Комнаты"])
def create_room(data: RoomFields, _admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    room = Room(**data.model_dump())
    db.add(room)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "ROOM_NAME_ALREADY_EXISTS", "Имя комнаты уже занято")
    db.refresh(room)
    return room

@app.patch(
    "/api/rooms/{room_id}",
    response_model=RoomOut,
    responses={
        404: {"model": ErrorResponse, "description": "ROOM_NOT_FOUND"},
        422: {
            "model": ErrorResponse,
            "description": "VALIDATION_ERROR, в том числе для явного null.",
        },
    },
    tags=["Комнаты"],
    description=(
        "Частично обновляет переданные поля. Пустой JSON-объект {} является no-op и "
        "возвращает текущее состояние комнаты; явный null для любого поля запрещён."
    ),
)
def patch_room(room_id: uuid.UUID, data: RoomPatch, _admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    room = db.scalar(select(Room).where(Room.id == room_id).with_for_update())
    if not room:
        raise AppError(404, "ROOM_NOT_FOUND", "Комната не найдена")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(room, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "ROOM_NAME_ALREADY_EXISTS", "Имя комнаты уже занято")
    return room

@app.delete("/api/rooms/{room_id}", status_code=204, tags=["Комнаты"])
def delete_room(room_id: uuid.UUID, _admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    room = db.scalar(select(Room).where(Room.id == room_id).with_for_update())
    if not room:
        raise AppError(404, "ROOM_NOT_FOUND", "Комната не найдена")
    room.is_active = False
    db.commit()

@app.post("/api/bookings", response_model=BookingOut, status_code=201, tags=["Бронирования"])
def create_booking(data: BookingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    room = db.scalar(select(Room).where(Room.id == data.room_id).with_for_update())
    if not room:
        raise AppError(404, "ROOM_NOT_FOUND", "Комната не найдена")
    if not room.is_active:
        raise AppError(409, "ROOM_INACTIVE", "Комната недоступна")
    now = clock.now()
    errors = validate_booking_time(data, now)
    if data.attendees > room.capacity:
        errors["attendees"] = "Число участников превышает вместимость"
    if errors:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "Неверные данные", "fields": [{"field": key, "message": value} for key, value in errors.items()]}}, status_code=422)
    expire_due(db, now)
    existing = db.scalars(select(Booking).where(Booking.room_id == room.id, Booking.booking_date == data.booking_date, Booking.status.in_(OCCUPYING))).all()
    if any(overlaps(data, other) for other in existing):
        db.rollback()
        raise AppError(409, "TIME_SLOT_OCCUPIED", "Выбранный слот занят")
    booking = Booking(user_id=user.id, room_id=room.id, title=data.title, booking_date=data.booking_date,
                      start_time=data.start_time, duration_minutes=data.duration_minutes, attendees=data.attendees,
                      total_price_kopeks=room.price_per_30min_kopeks * (data.duration_minutes // 30),
                      status="CREATED", created_at=now, updated_at=now, expires_at=now + timedelta(minutes=15))
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking

@app.get(
    "/api/bookings",
    response_model=list[BookingOut],
    tags=["Бронирования"],
    description=(
        "Возвращает все доступные вызывающему брони без пагинации: USER — только свои, "
        "ADMIN — все. Сортировка: created_at DESC, затем id DESC."
    ),
)
def bookings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    expire_due(db, clock.now())
    db.commit()
    query = select(Booking).order_by(Booking.created_at.desc(), Booking.id.desc())
    if user.role != "ADMIN":
        query = query.where(Booking.user_id == user.id)
    return db.scalars(query).all()

@app.get("/api/bookings/{booking_id}", response_model=BookingOut, tags=["Бронирования"])
def booking_detail(booking_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = visible_booking(db, booking_id, user)
    db.commit()
    return booking

@app.post("/api/bookings/{booking_id}/cancel", response_model=BookingOut, tags=["Бронирования"])
def cancel_booking(booking_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = visible_booking(db, booking_id, user, lock=True)
    if booking.status not in ("CREATED", "PAYMENT_PENDING"):
        raise AppError(409, "INVALID_STATUS_TRANSITION", "Бронь нельзя отменить")
    booking.status = "CANCELLED"
    booking.updated_at = clock.now()
    db.commit()
    return booking

@app.post("/api/bookings/{booking_id}/pay", response_model=BookingOut, status_code=202, tags=["Бронирования"])
def pay_booking(booking_id: uuid.UUID, data: PayIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = visible_booking(db, booking_id, user, lock=True)
    if data and "test_scenario" in data.model_fields_set and not settings.test_mode:
        return field_error("test_scenario", "Поле доступно только в TEST_MODE")
    if settings.payment_mode == "disabled":
        raise AppError(503, "PAYMENTS_UNAVAILABLE", "Оплата временно недоступна")
    if booking.status != "CREATED":
        raise AppError(409, "INVALID_STATUS_TRANSITION", "Бронь нельзя оплатить")
    now = clock.now()
    request_id = uuid.uuid4()
    booking.payment_request_id = request_id
    booking.status = "PAYMENT_PENDING"
    booking.updated_at = now
    payload = {"event_id": str(request_id), "event_type": "PaymentRequested", "version": 1,
               "occurred_at": now.isoformat().replace("+00:00", "Z"), "booking_id": str(booking.id),
               "amount_kopeks": booking.total_price_kopeks, "currency": "RUB"}
    if data and data.test_scenario:
        payload["test_scenario"] = data.test_scenario
    db.add(OutboxEvent(event_id=request_id, booking_id=booking.id, payload=json.dumps(payload), created_at=now))
    db.commit()
    return booking

@app.get(
    "/api/health/live",
    response_model=HealthOut,
    tags=["Состояние сервиса"],
)
def live():
    return HealthOut(status="ok")

@app.get(
    "/api/health/ready",
    response_model=HealthOut,
    responses={
        503: {
            "model": ErrorResponse,
            "description": "DATABASE_UNAVAILABLE: основная БД недоступна.",
        }
    },
    tags=["Состояние сервиса"],
    description=(
        "Готовность зависит только от основной БД. Недоступность Kafka или "
        "payment-service не переводит endpoint в 503."
    ),
)
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise AppError(503, "DATABASE_UNAVAILABLE", "База данных недоступна")
    return {"status": "ok"}
