from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, status
from sqlalchemy.orm import Session

from . import models, schemas, services
from .auth import get_current_user, require_student, require_teacher
from .auth.router import router as auth_router
from .database import Base, engine, get_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Online Quiz Exam API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)


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
    user: models.User = Depends(require_teacher),
) -> models.Quiz:
    return services.create_quiz(db, user, payload)


@app.get("/quizzes", response_model=list[schemas.QuizSummaryPublic])
def list_quizzes(db: Session = Depends(get_db)) -> list[schemas.QuizSummaryPublic]:
    return services.list_quizzes(db)


@app.get("/quizzes/{quiz_id}", response_model=schemas.QuizPublic)
def get_quiz(quiz_id: int, db: Session = Depends(get_db)) -> models.Quiz:
    return services.get_quiz_public(db, quiz_id)


@app.get("/quizzes/{quiz_id}/answers", response_model=schemas.QuizWithAnswersPublic)
def get_quiz_answers(
    quiz_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_teacher),
) -> models.Quiz:
    return services.get_quiz_with_answers(db, quiz_id, user)


@app.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=schemas.AttemptPublic,
    status_code=status.HTTP_201_CREATED,
)
def start_attempt(
    quiz_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_student),
) -> models.Attempt:
    return services.start_attempt(db, quiz_id, user)


@app.put(
    "/attempts/{attempt_id}/answers/{question_position}",
    response_model=schemas.AnswerPublic,
)
def submit_answer(
    attempt_id: int,
    question_position: int,
    payload: schemas.AnswerSubmit,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_student),
) -> schemas.AnswerPublic:
    return services.submit_answer(db, attempt_id, question_position, payload.selected_option, user)


@app.get("/attempts/{attempt_id}", response_model=schemas.AttemptProgressPublic)
def get_attempt_progress(
    attempt_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_student),
) -> schemas.AttemptProgressPublic:
    return services.get_attempt_progress(db, attempt_id, user)


@app.post("/attempts/{attempt_id}/finish", response_model=schemas.AttemptResultPublic)
def finish_attempt(
    attempt_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_student),
) -> schemas.AttemptResultPublic:
    services.finish_attempt(db, attempt_id, user)
    return services.get_attempt_result(db, attempt_id, user)


@app.get("/attempts/{attempt_id}/result", response_model=schemas.AttemptResultPublic)
def get_attempt_result(
    attempt_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> schemas.AttemptResultPublic:
    return services.get_attempt_result(db, attempt_id, user)


@app.get("/quizzes/{quiz_id}/attempts", response_model=list[schemas.AttemptSummaryPublic])
def list_quiz_attempts(
    quiz_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_teacher),
) -> list[schemas.AttemptSummaryPublic]:
    return services.list_quiz_attempts(db, quiz_id, user)
