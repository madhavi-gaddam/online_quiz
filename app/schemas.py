from datetime import datetime

from pydantic import BaseModel, Field


class OptionCreate(BaseModel):
    text: str = Field(min_length=1)


class QuestionCreate(BaseModel):
    text: str = Field(min_length=1)
    options: list[OptionCreate] = Field(min_length=4, max_length=4)
    correct_option: int = Field(
        ge=1,
        le=4,
        description="Position of the correct option, from 1 to 4.",
    )


class QuizCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    time_limit_minutes: int = Field(gt=0)
    questions: list[QuestionCreate] = Field(min_length=1)


class OptionPublic(BaseModel):
    text: str
    position: int

    model_config = {"from_attributes": True}


class QuestionPublic(BaseModel):
    text: str
    position: int
    options: list[OptionPublic]

    model_config = {"from_attributes": True}


class QuizPublic(BaseModel):
    id: int
    creator_id: int
    title: str
    description: str
    time_limit_minutes: int
    questions: list[QuestionPublic]

    model_config = {"from_attributes": True}


class AttemptPublic(BaseModel):
    id: int
    quiz_id: int
    user_id: int
    status: str
    started_at: datetime

    model_config = {"from_attributes": True}


class AnswerSubmit(BaseModel):
    selected_option: int = Field(
        ge=1,
        le=4,
        description="Option number selected by the user, from 1 to 4.",
    )


class AnswerPublic(BaseModel):
    attempt_id: int
    question_position: int
    selected_option: int
    submitted_at: datetime


class QuestionResultPublic(BaseModel):
    question_position: int
    question_text: str
    selected_option: int | None
    selected_option_text: str | None
    is_correct: bool


class AttemptResultPublic(BaseModel):
    attempt_id: int
    quiz_id: int
    user_id: int
    score: float
    time_taken_seconds: int
    questions: list[QuestionResultPublic]


class AttemptSummaryPublic(BaseModel):
    attempt_id: int
    user_id: int
    user_name: str
    status: str
    score: float | None
    time_taken_seconds: int | None
