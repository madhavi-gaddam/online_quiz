import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from . import models, schemas


logger = logging.getLogger(__name__)


def commit_or_rollback(db: Session, message: str, **context: object) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        context_text = " ".join(f"{key}={value}" for key, value in context.items())
        logger.exception("Database exception %s %s", message, context_text)
        raise


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def seconds_between(start: datetime, end: datetime) -> int:
    return max(0, int((aware_utc(end) - aware_utc(start)).total_seconds()))


def attempt_deadline(attempt: models.Attempt) -> datetime:
    return aware_utc(attempt.started_at) + timedelta(minutes=attempt.quiz.time_limit_minutes)


def score_attempt(attempt: models.Attempt) -> None:
    answers_by_question = {answer.question_id: answer for answer in attempt.answers}
    results_by_question = {result.question_id: result for result in attempt.results}
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

        result = results_by_question.get(question.id)
        if result:
            result.chosen_option_id = chosen_option_id
            result.is_correct = is_correct
        else:
            attempt.results.append(
                models.AttemptQuestionResult(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    chosen_option_id=chosen_option_id,
                    is_correct=is_correct,
                )
            )

    total_questions = len(attempt.quiz.questions)
    attempt.score = round((correct_count / total_questions) * 100, 2) if total_questions else 0.0


def check_and_handle_attempt_expiry(attempt: models.Attempt, db: Session) -> None:
    if attempt.status != models.AttemptStatus.active:
        return

    deadline_at = attempt_deadline(attempt)
    if aware_utc(models.utc_now()) <= deadline_at:
        return

    score_attempt(attempt)
    attempt.status = models.AttemptStatus.expired
    attempt.completed_at = deadline_at
    commit_or_rollback(
        db,
        "while expiring attempt",
        user_id=attempt.user_id,
        quiz_id=attempt.quiz_id,
        attempt_id=attempt.id,
    )
    logger.info(
        "Attempt expired user_id=%s quiz_id=%s attempt_id=%s score=%s",
        attempt.user_id,
        attempt.quiz_id,
        attempt.id,
        attempt.score,
    )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Attempt has expired")


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
    commit_or_rollback(db, "while creating quiz", user_id=creator.id)
    logger.info("Quiz created user_id=%s quiz_id=%s question_count=%s", creator.id, quiz.id, len(quiz.questions))
    return get_quiz_public(db, quiz.id)


def get_quiz_public(db: Session, quiz_id: int) -> models.Quiz:
    quiz = db.scalar(
        select(models.Quiz)
        .where(models.Quiz.id == quiz_id)
        .options(selectinload(models.Quiz.questions).selectinload(models.Question.options))
    )
    if not quiz:
        logger.warning("Validation failure quiz_not_found quiz_id=%s", quiz_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found.")
    return quiz


def get_quiz_with_answers(db: Session, quiz_id: int, teacher: models.User) -> models.Quiz:
    quiz = get_quiz_public(db, quiz_id)
    if quiz.creator_id != teacher.id:
        logger.warning(
            "Validation failure forbidden_quiz_answers user_id=%s quiz_id=%s creator_id=%s",
            teacher.id,
            quiz_id,
            quiz.creator_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the quiz creator can view correct answers.",
        )
    return quiz


def list_quizzes(db: Session) -> list[schemas.QuizSummaryPublic]:
    quizzes = db.scalars(
        select(models.Quiz)
        .options(selectinload(models.Quiz.creator), selectinload(models.Quiz.questions))
        .order_by(models.Quiz.created_at.desc())
    ).all()

    return [
        schemas.QuizSummaryPublic(
            id=quiz.id,
            creator_id=quiz.creator_id,
            creator_name=quiz.creator.username,
            title=quiz.title,
            description=quiz.description,
            time_limit_minutes=quiz.time_limit_minutes,
            question_count=len(quiz.questions),
            created_at=quiz.created_at,
        )
        for quiz in quizzes
    ]


def start_attempt(db: Session, quiz_id: int, user: models.User) -> models.Attempt:
    quiz = db.get(models.Quiz, quiz_id)
    if not quiz:
        logger.warning("Validation failure quiz_not_found user_id=%s quiz_id=%s", user.id, quiz_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found.")
    if quiz.creator_id == user.id:
        logger.warning("Validation failure creator_cannot_attempt user_id=%s quiz_id=%s", user.id, quiz_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quiz creators cannot take their own quizzes.",
        )

    active_attempt = db.scalar(
        select(models.Attempt)
        .where(
            models.Attempt.quiz_id == quiz_id,
            models.Attempt.user_id == user.id,
            models.Attempt.status == models.AttemptStatus.active,
        )
        .options(
            selectinload(models.Attempt.quiz)
            .selectinload(models.Quiz.questions)
            .selectinload(models.Question.options),
            selectinload(models.Attempt.answers),
            selectinload(models.Attempt.results),
        )
    )
    if active_attempt:
        check_and_handle_attempt_expiry(active_attempt, db)
        logger.warning(
            "Validation failure active_attempt_exists user_id=%s quiz_id=%s attempt_id=%s",
            user.id,
            quiz_id,
            active_attempt.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already has an active attempt for this quiz.",
        )

    attempt = models.Attempt(quiz_id=quiz_id, user_id=user.id)
    db.add(attempt)
    commit_or_rollback(db, "while starting attempt", user_id=user.id, quiz_id=quiz_id)
    db.refresh(attempt)
    logger.info("Attempt started user_id=%s quiz_id=%s attempt_id=%s", user.id, quiz_id, attempt.id)
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
        .options(
            selectinload(models.Attempt.quiz)
            .selectinload(models.Quiz.questions)
            .selectinload(models.Question.options),
            selectinload(models.Attempt.answers),
            selectinload(models.Attempt.results),
        )
    )
    if not attempt:
        logger.warning("Validation failure attempt_not_found user_id=%s attempt_id=%s", user.id, attempt_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    check_and_handle_attempt_expiry(attempt, db)
    if attempt.status != models.AttemptStatus.active:
        logger.warning(
            "Validation failure attempt_not_active user_id=%s quiz_id=%s attempt_id=%s status=%s",
            user.id,
            attempt.quiz_id,
            attempt_id,
            attempt.status.value,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Attempt has expired"
                if attempt.status == models.AttemptStatus.expired
                else "Completed attempts cannot be changed."
            ),
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
        logger.warning(
            "Validation failure question_not_found user_id=%s quiz_id=%s attempt_id=%s question_position=%s",
            user.id,
            attempt.quiz_id,
            attempt_id,
            question_position,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question position not found for this attempt's quiz.",
        )

    option = next((candidate for candidate in question.options if candidate.position == selected_option), None)
    if not option:
        logger.warning(
            "Validation failure invalid_option user_id=%s quiz_id=%s attempt_id=%s question_id=%s selected_option=%s",
            user.id,
            attempt.quiz_id,
            attempt_id,
            question.id,
            selected_option,
        )
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

    commit_or_rollback(
        db,
        "while submitting answer",
        user_id=user.id,
        quiz_id=attempt.quiz_id,
        attempt_id=attempt_id,
        question_id=question.id,
    )
    db.refresh(answer)
    logger.info(
        "Answer submitted user_id=%s quiz_id=%s attempt_id=%s question_id=%s selected_option=%s",
        user.id,
        attempt.quiz_id,
        attempt_id,
        question.id,
        option.position,
    )
    return schemas.AnswerPublic(
        attempt_id=attempt_id,
        question_position=question.position,
        selected_option=option.position,
        submitted_at=answer.submitted_at,
    )


def get_attempt_progress(db: Session, attempt_id: int, user: models.User) -> schemas.AttemptProgressPublic:
    attempt = db.scalar(
        select(models.Attempt)
        .where(models.Attempt.id == attempt_id, models.Attempt.user_id == user.id)
        .options(
            selectinload(models.Attempt.quiz)
            .selectinload(models.Quiz.questions)
            .selectinload(models.Question.options),
            selectinload(models.Attempt.answers).selectinload(models.Answer.chosen_option),
            selectinload(models.Attempt.results),
        )
    )
    if not attempt:
        logger.warning("Validation failure attempt_not_found user_id=%s attempt_id=%s", user.id, attempt_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    check_and_handle_attempt_expiry(attempt, db)

    answers_by_question = {answer.question_id: answer for answer in attempt.answers}
    deadline_at = attempt_deadline(attempt)
    remaining_seconds = (
        max(0, seconds_between(models.utc_now(), deadline_at))
        if attempt.status == models.AttemptStatus.active
        else 0
    )

    return schemas.AttemptProgressPublic(
        attempt_id=attempt.id,
        quiz_id=attempt.quiz_id,
        quiz_title=attempt.quiz.title,
        status=attempt.status.value,
        started_at=attempt.started_at,
        deadline_at=deadline_at,
        remaining_seconds=remaining_seconds,
        answered_questions=len(answers_by_question),
        total_questions=len(attempt.quiz.questions),
        questions=[
            schemas.AttemptQuestionProgressPublic(
                question_position=question.position,
                question_text=question.text,
                options=[
                    schemas.OptionPublic(text=option.text, position=option.position)
                    for option in question.options
                ],
                selected_option=(
                    answers_by_question[question.id].chosen_option.position
                    if question.id in answers_by_question
                    else None
                ),
            )
            for question in attempt.quiz.questions
        ],
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
            selectinload(models.Attempt.results),
        )
    )
    if not attempt:
        logger.warning("Validation failure attempt_not_found user_id=%s attempt_id=%s", user.id, attempt_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    check_and_handle_attempt_expiry(attempt, db)
    if attempt.status != models.AttemptStatus.active:
        logger.warning(
            "Validation failure attempt_not_active user_id=%s quiz_id=%s attempt_id=%s status=%s",
            user.id,
            attempt.quiz_id,
            attempt_id,
            attempt.status.value,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Attempt has expired"
                if attempt.status == models.AttemptStatus.expired
                else "Attempt is already completed."
            ),
        )

    score_attempt(attempt)
    attempt.status = models.AttemptStatus.completed
    attempt.completed_at = models.utc_now()
    commit_or_rollback(
        db,
        "while finishing attempt",
        user_id=user.id,
        quiz_id=attempt.quiz_id,
        attempt_id=attempt_id,
    )
    db.refresh(attempt)
    logger.info(
        "Attempt completed user_id=%s quiz_id=%s attempt_id=%s score=%s",
        user.id,
        attempt.quiz_id,
        attempt_id,
        attempt.score,
    )
    return attempt


def get_attempt_for_user(db: Session, attempt_id: int, user_id: int) -> models.Attempt:
    attempt = db.scalar(
        select(models.Attempt).where(
            models.Attempt.id == attempt_id,
            models.Attempt.user_id == user_id,
        )
    )
    if not attempt:
        logger.warning("Validation failure attempt_not_found user_id=%s attempt_id=%s", user_id, attempt_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    return attempt


def get_attempt_result(db: Session, attempt_id: int, user: models.User) -> schemas.AttemptResultPublic:
    attempt = db.scalar(
        select(models.Attempt)
        .where(models.Attempt.id == attempt_id)
        .options(
            selectinload(models.Attempt.quiz)
            .selectinload(models.Quiz.questions)
            .selectinload(models.Question.options),
            selectinload(models.Attempt.answers),
            selectinload(models.Attempt.results).selectinload(models.AttemptQuestionResult.chosen_option),
        )
    )
    if not attempt:
        logger.warning("Validation failure attempt_not_found user_id=%s attempt_id=%s", user.id, attempt_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    is_student_owner = user.role == models.UserRole.student and attempt.user_id == user.id
    is_teacher_owner = user.role == models.UserRole.teacher and attempt.quiz.creator_id == user.id
    if not (is_student_owner or is_teacher_owner):
        logger.warning(
            "Validation failure forbidden_attempt_result user_id=%s attempt_id=%s quiz_id=%s",
            user.id,
            attempt_id,
            attempt.quiz_id,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to view this attempt.")

    check_and_handle_attempt_expiry(attempt, db)

    results_by_question = {result.question_id: result for result in attempt.results}
    answers_by_question = {answer.question_id: answer for answer in attempt.answers}
    reveal_answers = is_teacher_owner or attempt.status in {
        models.AttemptStatus.completed,
        models.AttemptStatus.expired,
    }
    return schemas.AttemptResultPublic(
        attempt_id=attempt.id,
        quiz_id=attempt.quiz_id,
        user_id=attempt.user_id,
        status=attempt.status.value,
        score=attempt.score if reveal_answers else None,
        time_taken_seconds=(
            seconds_between(attempt.started_at, attempt.completed_at)
            if attempt.completed_at
            else None
        ),
        questions=[
            schemas.QuestionResultPublic(
                question_position=question.position,
                question_text=question.text,
                selected_option=(
                    results_by_question[question.id].chosen_option.position
                    if question.id in results_by_question and results_by_question[question.id].chosen_option
                    else answers_by_question[question.id].chosen_option.position
                    if question.id in answers_by_question
                    else None
                ),
                selected_option_text=(
                    results_by_question[question.id].chosen_option.text
                    if question.id in results_by_question and results_by_question[question.id].chosen_option
                    else answers_by_question[question.id].chosen_option.text
                    if question.id in answers_by_question
                    else None
                ),
                correct_option=(
                    next(option.position for option in question.options if option.is_correct)
                    if reveal_answers
                    else None
                ),
                correct_option_text=(
                    next(option.text for option in question.options if option.is_correct)
                    if reveal_answers
                    else None
                ),
                is_correct=(
                    results_by_question[question.id].is_correct
                    if reveal_answers and question.id in results_by_question
                    else None
                ),
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
        logger.warning("Validation failure quiz_not_found user_id=%s quiz_id=%s", creator.id, quiz_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found.")
    if quiz.creator_id != creator.id:
        logger.warning(
            "Validation failure forbidden_attempt_listing user_id=%s quiz_id=%s creator_id=%s",
            creator.id,
            quiz_id,
            quiz.creator_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the quiz creator can list attempts.",
        )

    attempts = db.scalars(
        select(models.Attempt)
        .where(models.Attempt.quiz_id == quiz_id)
        .options(
            selectinload(models.Attempt.user),
            selectinload(models.Attempt.quiz)
            .selectinload(models.Quiz.questions)
            .selectinload(models.Question.options),
            selectinload(models.Attempt.answers),
            selectinload(models.Attempt.results),
        )
        .order_by(models.Attempt.started_at.desc())
    ).all()
    for attempt in attempts:
        check_and_handle_attempt_expiry(attempt, db)

    return [
        schemas.AttemptSummaryPublic(
            attempt_id=attempt.id,
            user_id=attempt.user_id,
            user_name=attempt.user.username,
            status=attempt.status.value,
            score=attempt.score,
            time_taken_seconds=(
                seconds_between(attempt.started_at, attempt.completed_at)
                if attempt.completed_at
                else None
            ),
        )
        for attempt in attempts
    ]
