from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import models, schemas


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def seconds_between(start: datetime, end: datetime) -> int:
    return max(0, int((aware_utc(end) - aware_utc(start)).total_seconds()))


def attempt_deadline(attempt: models.Attempt) -> datetime:
    return aware_utc(attempt.started_at) + timedelta(minutes=attempt.quiz.time_limit_minutes)


def attempt_time_limit_exceeded(attempt: models.Attempt, now: datetime | None = None) -> bool:
    checked_at = aware_utc(now or models.utc_now())
    return checked_at > attempt_deadline(attempt)


def create_quiz(db: Session, creator: models.User, payload: schemas.QuizCreate) -> models.Quiz:
    quiz = models.Quiz(
        creator_id=creator.id,
        title=payload.title,
        description=payload.description,
        time_limit_minutes=payload.time_limit_minutes,
    )
    for question_index, question_payload in enumerate(payload.questions, start=1):
        question = models.Question(text=question_payload.text, position=question_index)
        for option_index, option_payload in enumerate(question_payload.options, start=1):
            question.options.append(
                models.Option(
                    text=option_payload.text,
                    is_correct=option_index == question_payload.correct_option,
                    position=option_index,
                )
            )
        quiz.questions.append(question)

    db.add(quiz)
    db.commit()
    return get_quiz_public(db, quiz.id)


def get_quiz_public(db: Session, quiz_id: int) -> models.Quiz:
    quiz = db.scalar(
        select(models.Quiz)
        .where(models.Quiz.id == quiz_id)
        .options(selectinload(models.Quiz.questions).selectinload(models.Question.options))
    )
    if not quiz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found.")
    return quiz


def start_attempt(db: Session, quiz_id: int, user: models.User) -> models.Attempt:
    quiz = db.get(models.Quiz, quiz_id)
    if not quiz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found.")

    active_attempt = db.scalar(
        select(models.Attempt).where(
            models.Attempt.quiz_id == quiz_id,
            models.Attempt.user_id == user.id,
            models.Attempt.status == models.AttemptStatus.active,
        )
    )
    if active_attempt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already has an active attempt for this quiz.",
        )

    attempt = models.Attempt(quiz_id=quiz_id, user_id=user.id)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def submit_answer(
    db: Session,
    attempt_id: int,
    question_position: int,
    selected_option: int,
    user: models.User,
) -> schemas.AnswerPublic:
    attempt = db.scalar(
        select(models.Attempt)
        .where(models.Attempt.id == attempt_id, models.Attempt.user_id == user.id)
        .options(selectinload(models.Attempt.quiz))
    )
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    if attempt.status != models.AttemptStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finished attempts cannot be changed.",
        )
    if attempt_time_limit_exceeded(attempt):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Time limit exceeded. Finish the attempt to get the result.",
        )

    question = db.scalar(
        select(models.Question)
        .where(
            models.Question.quiz_id == attempt.quiz_id,
            models.Question.position == question_position,
        )
        .options(selectinload(models.Question.options))
    )
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question position not found for this attempt's quiz.",
        )

    option = next((candidate for candidate in question.options if candidate.position == selected_option), None)
    if not option:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected option must be a valid option number for this question.",
        )

    answer = db.scalar(
        select(models.Answer).where(
            models.Answer.attempt_id == attempt_id,
            models.Answer.question_id == question.id,
        )
    )
    if answer:
        answer.chosen_option_id = option.id
        answer.submitted_at = models.utc_now()
    else:
        answer = models.Answer(
            attempt_id=attempt_id,
            question_id=question.id,
            chosen_option_id=option.id,
        )
        db.add(answer)

    db.commit()
    db.refresh(answer)
    return schemas.AnswerPublic(
        attempt_id=attempt_id,
        question_position=question.position,
        selected_option=option.position,
        submitted_at=answer.submitted_at,
    )


def finish_attempt(db: Session, attempt_id: int, user: models.User) -> models.Attempt:
    attempt = db.scalar(
        select(models.Attempt)
        .where(models.Attempt.id == attempt_id, models.Attempt.user_id == user.id)
        .options(
            selectinload(models.Attempt.quiz)
            .selectinload(models.Quiz.questions)
            .selectinload(models.Question.options),
            selectinload(models.Attempt.answers),
        )
    )
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    if attempt.status != models.AttemptStatus.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Attempt is already finished.")

    answers_by_question = {answer.question_id: answer for answer in attempt.answers}
    correct_count = 0

    for question in attempt.quiz.questions:
        answer = answers_by_question.get(question.id)
        chosen_option_id = answer.chosen_option_id if answer else None
        chosen_option = next(
            (option for option in question.options if option.id == chosen_option_id),
            None,
        )
        is_correct = bool(chosen_option and chosen_option.is_correct)
        correct_count += int(is_correct)
        db.add(
            models.AttemptQuestionResult(
                attempt_id=attempt.id,
                question_id=question.id,
                chosen_option_id=chosen_option_id,
                is_correct=is_correct,
            )
        )

    total_questions = len(attempt.quiz.questions)
    attempt.score = round((correct_count / total_questions) * 100, 2) if total_questions else 0.0
    attempt.status = models.AttemptStatus.finished
    attempt.finished_at = models.utc_now()
    db.commit()
    db.refresh(attempt)
    return attempt


def get_attempt_for_user(db: Session, attempt_id: int, user_id: int) -> models.Attempt:
    attempt = db.scalar(
        select(models.Attempt).where(
            models.Attempt.id == attempt_id,
            models.Attempt.user_id == user_id,
        )
    )
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    return attempt


def get_attempt_result(db: Session, attempt_id: int, user: models.User) -> schemas.AttemptResultPublic:
    attempt = db.scalar(
        select(models.Attempt)
        .where(models.Attempt.id == attempt_id, models.Attempt.user_id == user.id)
        .options(
            selectinload(models.Attempt.quiz)
            .selectinload(models.Quiz.questions)
            .selectinload(models.Question.options),
            selectinload(models.Attempt.results).selectinload(models.AttemptQuestionResult.chosen_option),
        )
    )
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    if attempt.status != models.AttemptStatus.finished or attempt.finished_at is None or attempt.score is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Attempt is not finished.")

    results_by_question = {result.question_id: result for result in attempt.results}
    return schemas.AttemptResultPublic(
        attempt_id=attempt.id,
        quiz_id=attempt.quiz_id,
        user_id=attempt.user_id,
        score=attempt.score,
        time_taken_seconds=seconds_between(attempt.started_at, attempt.finished_at),
        questions=[
            schemas.QuestionResultPublic(
                question_position=question.position,
                question_text=question.text,
                selected_option=(
                    results_by_question[question.id].chosen_option.position
                    if results_by_question[question.id].chosen_option
                    else None
                ),
                selected_option_text=(
                    results_by_question[question.id].chosen_option.text
                    if results_by_question[question.id].chosen_option
                    else None
                ),
                is_correct=results_by_question[question.id].is_correct,
            )
            for question in attempt.quiz.questions
        ],
    )


def list_quiz_attempts(
    db: Session,
    quiz_id: int,
    creator: models.User,
) -> list[schemas.AttemptSummaryPublic]:
    quiz = db.get(models.Quiz, quiz_id)
    if not quiz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found.")
    if quiz.creator_id != creator.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the quiz creator can list attempts.",
        )

    attempts = db.scalars(
        select(models.Attempt)
        .where(models.Attempt.quiz_id == quiz_id)
        .options(selectinload(models.Attempt.user))
        .order_by(models.Attempt.started_at.desc())
    ).all()

    return [
        schemas.AttemptSummaryPublic(
            attempt_id=attempt.id,
            user_id=attempt.user_id,
            user_name=attempt.user.name,
            status=attempt.status.value,
            score=attempt.score,
            time_taken_seconds=(
                seconds_between(attempt.started_at, attempt.finished_at)
                if attempt.finished_at
                else None
            ),
        )
        for attempt in attempts
    ]
