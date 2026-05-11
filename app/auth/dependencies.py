from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import models
from app.auth.security import decode_access_token
from app.database import get_db


bearer_scheme = HTTPBearer(auto_error=False)


def credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None:
        raise credentials_exception()

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["user_id"])
    except (KeyError, TypeError, ValueError):
        raise credentials_exception()

    user = db.get(models.User, user_id)
    if not user:
        raise credentials_exception()
    return user


def require_teacher(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != models.UserRole.teacher:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher role required.")
    return user


def require_student(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != models.UserRole.student:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student role required.")
    return user
