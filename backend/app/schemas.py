from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class RegisterIn(StrictModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

class LoginIn(StrictModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    role: str
    created_at: datetime

class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class ErrorDetails(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetails


class HealthOut(BaseModel):
    status: Literal["ok"]

class ResetDataIn(StrictModel):
    confirm: Literal["reset-test-data"]

class RoomFields(StrictModel):
    name: str = Field(min_length=3, max_length=50)
    capacity: int = Field(strict=True, ge=2, le=10)
    price_per_30min_kopeks: int = Field(strict=True, ge=10000, le=200000)
    is_active: bool = Field(default=True, strict=True)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

def omit_none_default(schema: dict) -> None:
    """Keep PATCH fields optional in OpenAPI without advertising null values."""
    schema.pop("default", None)


class RoomPatch(StrictModel):
    """An empty object is a no-op; fields that are present must not be null."""

    name: str = Field(
        default=None,
        min_length=3,
        max_length=50,
        json_schema_extra=omit_none_default,
    )
    capacity: int = Field(
        default=None,
        strict=True,
        ge=2,
        le=10,
        json_schema_extra=omit_none_default,
    )
    price_per_30min_kopeks: int = Field(
        default=None,
        strict=True,
        ge=10000,
        le=200000,
        json_schema_extra=omit_none_default,
    )
    is_active: bool = Field(
        default=None,
        strict=True,
        json_schema_extra=omit_none_default,
    )

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    capacity: int
    price_per_30min_kopeks: int
    is_active: bool

class BookingIn(StrictModel):
    room_id: UUID
    title: str = Field(min_length=3, max_length=60)
    booking_date: date
    start_time: time
    duration_minutes: Literal[30, 60, 90, 120]
    attendees: int = Field(strict=True, ge=1)

    @field_validator("booking_date", mode="before")
    @classmethod
    def exact_date(cls, value):
        if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-" or not (value[:4] + value[5:7] + value[8:]).isdigit():
            raise ValueError("Дата должна быть в формате YYYY-MM-DD")
        return value

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def exact_duration_type(cls, value):
        if type(value) is not int:
            raise ValueError("Длительность должна быть целым числом")
        return value

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("start_time", mode="before")
    @classmethod
    def exact_time(cls, value):
        if not isinstance(value, str) or len(value) != 5 or value[2] != ":" or not (value[:2] + value[3:]).isdigit():
            raise ValueError("Время должно быть в формате HH:mm")
        return value

class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    room_id: UUID
    title: str
    booking_date: date
    start_time: time
    end_time: time
    duration_minutes: int
    attendees: int
    total_price_kopeks: int
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

class PayIn(StrictModel):
    test_scenario: Literal["success", "failure", "no_response"] | None = None
