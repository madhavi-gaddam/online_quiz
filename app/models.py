from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AttemptStatus(str, Enum):
    active = "active"
    finished = "finished"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    created_quizzes: Mapped[list["Quiz"]] = relationship(back_populates="creator")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="user")


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time_limit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    creator: Mapped[User] = relationship(back_populates="created_quizzes")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="Question.position",
    )
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="quiz")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    quiz: Mapped[Quiz] = relationship(back_populates="questions")
    options: Mapped[list["Option"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="Option.position",
    )
    answers: Mapped[list["Answer"]] = relationship(back_populates="question")
    results: Mapped[list["AttemptQuestionResult"]] = relationship(back_populates="question")


class Option(Base):
    __tablename__ = "options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    question: Mapped[Question] = relationship(back_populates="options")
    answers: Mapped[list["Answer"]] = relationship(back_populates="chosen_option")
    results: Mapped[list["AttemptQuestionResult"]] = relationship(back_populates="chosen_option")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[AttemptStatus] = mapped_column(
        SqlEnum(AttemptStatus),
        nullable=False,
        default=AttemptStatus.active,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    quiz: Mapped[Quiz] = relationship(back_populates="attempts")
    user: Mapped[User] = relationship(back_populates="attempts")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
    )
    results: Mapped[list["AttemptQuestionResult"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
    )


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (Index("uq_answer_per_attempt_question", "attempt_id", "question_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False, index=True)
    chosen_option_id: Mapped[int] = mapped_column(ForeignKey("options.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    attempt: Mapped[Attempt] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship(back_populates="answers")
    chosen_option: Mapped[Option] = relationship(back_populates="answers")


class AttemptQuestionResult(Base):
    __tablename__ = "attempt_question_results"
    __table_args__ = (Index("uq_result_per_attempt_question", "attempt_id", "question_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    chosen_option_id: Mapped[int | None] = mapped_column(ForeignKey("options.id"), nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)

    attempt: Mapped[Attempt] = relationship(back_populates="results")
    question: Mapped[Question] = relationship(back_populates="results")
    chosen_option: Mapped[Option | None] = relationship(back_populates="results")


Index(
    "uq_active_attempt_per_user_quiz",
    Attempt.quiz_id,
    Attempt.user_id,
    unique=True,
    postgresql_where=Attempt.status == AttemptStatus.active,
    sqlite_where=Attempt.status == AttemptStatus.active,
)
