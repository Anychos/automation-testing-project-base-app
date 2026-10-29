from datetime import timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.domain import clock
from app.errors import AppError
from app.models import User

hasher = PasswordHasher(type=__import__("argon2").Type.ID)
bearer_auth = HTTPBearer(
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description="JWT access token from POST /api/auth/login",
    auto_error=False,
)

def hash_password(password: str) -> str:
    return hasher.hash(password)

def verify_password(hash_value: str, password: str) -> bool:
    try:
        return hasher.verify(hash_value, password)
    except (VerifyMismatchError, VerificationError):
        return False

def issue_token(user: User) -> str:
    return jwt.encode({"sub": str(user.id), "exp": clock.now() + timedelta(minutes=30)}, settings.jwt_secret, algorithm="HS256")

def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise AppError(401, "UNAUTHORIZED", "Требуется авторизация")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user = db.get(User, UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if not user:
        raise AppError(401, "UNAUTHORIZED", "Неверный или просроченный токен")
    return user

def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "ADMIN":
        raise AppError(403, "FORBIDDEN", "Недостаточно прав")
    return user
