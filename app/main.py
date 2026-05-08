from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Path, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from . import auth, models, schemas, services
from .core.logger import setup_logging
from .core.middleware import RequestLoggingMiddleware
from .database import Base, engine, get_db


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    logger.info("Application startup completed")
    yield
    logger.info("Application shutdown completed")


app = FastAPI(title="Online Quiz Exam API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning(
        "Request validation failure method=%s path=%s error_count=%s",
        request.method,
        request.url.path,
        len(exc.errors()),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


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
    "/attempts/{attempt_id}/answers/{question_position}",
    response_model=schemas.AnswerPublic,
)
def submit_answer(
    attempt_id: int,
    question_position: Annotated[
        int,
        Path(ge=1, description="Question number in the quiz, starting from 1."),
    ],
    payload: schemas.AnswerSubmit,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
) -> schemas.AnswerPublic:
    return services.submit_answer(db, attempt_id, question_position, payload.selected_option, user)


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
