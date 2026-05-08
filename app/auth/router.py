from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.auth import schemas
from app.auth.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.services import commit_or_rollback


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserPublic, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserRegister, db: Session = Depends(get_db)) -> models.User:
    existing_user = db.scalar(
        select(models.User).where(
            (models.User.username == payload.username) | (models.User.email == payload.email)
        )
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists.",
        )

    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    commit_or_rollback(db, "while registering user", username=payload.username)
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> schemas.Token:
    user = db.scalar(select(models.User).where(models.User.username == form_data.username))
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return schemas.Token(access_token=create_access_token(user))
