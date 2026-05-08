import logging

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from . import models


logger = logging.getLogger(__name__)


def get_or_create_user(db: Session, user_id: int, user_name: str | None = None) -> models.User:
    user = db.get(models.User, user_id)
    if user:
        if user_name and user.name != user_name:
            user.name = user_name
            db.commit()
            db.refresh(user)
        return user

    user = models.User(id=user_id, name=user_name or f"User {user_id}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def require_user_headers(
    x_user_id: int | None = Header(
        default=None,
        alias="X-User-Id",
        description="Required user identifier. Send this on every request.",
    ),
    x_user_name: str | None = Header(
        default=None,
        alias="X-User-Name",
        description="Optional display name. Send once when creating/updating the user.",
    ),
) -> tuple[int, str | None]:
    if x_user_id is None:
        logger.warning("Validation failure missing_header=X-User-Id")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-Id header is required.",
        )
    return x_user_id, x_user_name
