from pydantic import BaseModel, EmailStr, Field

from app.models import UserRole


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role: UserRole


class UserPublic(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: UserRole

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
