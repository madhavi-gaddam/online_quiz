import os
from datetime import timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app import models


SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


def create_access_token(user: models.User) -> str:
    expires_at = models.utc_now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "user_id": user.id,
        "username": user.username,
        "role": user.role.value,
        "exp": expires_at,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc
    return payload
