from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, status
from sqlalchemy.orm import Session

from . import auth, models, schemas, services
from .database import Base, engine, get_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Online Quiz Exam API", version="0.1.0", lifespan=lifespan)
 

def current_user(
    user_headers: tuple[int, str | None] = Depends(auth.require_user_headers),
    db: Session = Depends(get_db),
) -> models.User:
    user_id, user_name = user_headers
    return auth.get_or_create_user(db, user_id, user_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/quizzes",
    response_model=schemas.QuizPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_quiz(
    payload: schemas.QuizCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
) -> models.Quiz:
    return services.create_quiz(db, user, payload)


@app.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=schemas.AttemptPublic,
    status_code=status.HTTP_201_CREATED,
)
def start_attempt(
    quiz_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
) -> models.Attempt:
    return services.start_attempt(db, quiz_id, user)


@app.put(
    "/attempts/{attempt_id}/answers/{question_id}",
    response_model=schemas.AnswerPublic,
)
def submit_answer(
    attempt_id: int,
    question_id: int,
    payload: schemas.AnswerSubmit,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
) -> models.Answer:
    return services.submit_answer(db, attempt_id, question_id, payload.option_id, user)


@app.post("/attempts/{attempt_id}/finish", response_model=schemas.AttemptResultPublic)
def finish_attempt(
    attempt_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
) -> schemas.AttemptResultPublic:
    services.finish_attempt(db, attempt_id, user)
    return services.get_attempt_result(db, attempt_id, user)


@app.get("/attempts/{attempt_id}/result", response_model=schemas.AttemptResultPublic)
def get_attempt_result(
    attempt_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
) -> schemas.AttemptResultPublic:
    return services.get_attempt_result(db, attempt_id, user)


@app.get("/quizzes/{quiz_id}/attempts", response_model=list[schemas.AttemptSummaryPublic])
def list_quiz_attempts(
    quiz_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
) -> list[schemas.AttemptSummaryPublic]:
    return services.list_quiz_attempts(db, quiz_id, user)
