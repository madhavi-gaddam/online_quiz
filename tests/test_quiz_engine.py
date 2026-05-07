from collections.abc import Generator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def headers(user_id: int, name: str | None = None) -> dict[str, str]:
    values = {"X-User-Id": str(user_id)}
    if name:
        values["X-User-Name"] = name
    return values


def quiz_payload() -> dict:
    return {
        "title": "Python Basics",
        "description": "A quick check of Python fundamentals.",
        "time_limit_minutes": 15,
        "questions": [
            {
                "text": "Which keyword defines a function?",
                "options": [
                    {"text": "func"},
                    {"text": "def"},
                    {"text": "lambda"},
                    {"text": "method"},
                ],
                "correct_option": 2,
            },
            {
                "text": "What is the result of len([1, 2, 3])?",
                "options": [
                    {"text": "2"},
                    {"text": "3"},
                    {"text": "4"},
                    {"text": "None"},
                ],
                "correct_option": 2,
            },
        ],
    }


def create_quiz(client: TestClient) -> dict:
    response = client.post("/quizzes", json=quiz_payload(), headers=headers(1, "Creator"))
    assert response.status_code == 201
    return response.json()


def test_create_quiz_hides_correct_answers(client: TestClient) -> None:
    quiz = create_quiz(client)

    assert quiz["title"] == "Python Basics"
    assert len(quiz["questions"]) == 2
    assert "id" not in quiz["questions"][0]
    assert "id" not in quiz["questions"][0]["options"][0]
    assert "is_correct" not in quiz["questions"][0]["options"][0]


def test_create_quiz_requires_correct_option_position(client: TestClient) -> None:
    payload = quiz_payload()
    payload["questions"][0]["correct_option"] = 5

    response = client.post("/quizzes", json=payload, headers=headers(1))

    assert response.status_code == 422


def test_attempt_lifecycle_scores_and_locks_answers(client: TestClient) -> None:
    quiz = create_quiz(client)
    quiz_id = quiz["id"]
    q1 = quiz["questions"][0]
    q2 = quiz["questions"][1]

    start_response = client.post(f"/quizzes/{quiz_id}/attempts", headers=headers(2, "Student"))
    assert start_response.status_code == 201
    attempt_id = start_response.json()["id"]

    duplicate_start = client.post(f"/quizzes/{quiz_id}/attempts", headers=headers(2))
    assert duplicate_start.status_code == 409

    first_answer = client.put(
        f"/attempts/{attempt_id}/answers/{q1['position']}",
        json={"selected_option": 1},
        headers=headers(2),
    )
    assert first_answer.status_code == 200

    overwrite_answer = client.put(
        f"/attempts/{attempt_id}/answers/{q1['position']}",
        json={"selected_option": 2},
        headers=headers(2),
    )
    assert overwrite_answer.status_code == 200
    assert overwrite_answer.json()["question_position"] == 1
    assert overwrite_answer.json()["selected_option"] == 2

    second_answer = client.put(
        f"/attempts/{attempt_id}/answers/{q2['position']}",
        json={"selected_option": 2},
        headers=headers(2),
    )
    assert second_answer.status_code == 200

    finish = client.post(f"/attempts/{attempt_id}/finish", headers=headers(2))
    assert finish.status_code == 200
    result = finish.json()
    assert result["score"] == 100.0
    assert result["time_taken_seconds"] >= 0
    assert all(question["is_correct"] for question in result["questions"])

    locked_answer = client.put(
        f"/attempts/{attempt_id}/answers/{q1['position']}",
        json={"selected_option": 1},
        headers=headers(2),
    )
    assert locked_answer.status_code == 409

    result_response = client.get(f"/attempts/{attempt_id}/result", headers=headers(2))
    assert result_response.status_code == 200
    assert result_response.json()["score"] == 100.0

    retake_response = client.post(f"/quizzes/{quiz_id}/attempts", headers=headers(2))
    assert retake_response.status_code == 201
    assert retake_response.json()["id"] != attempt_id


def test_answer_after_time_limit_is_rejected(client: TestClient) -> None:
    quiz = create_quiz(client)
    quiz_id = quiz["id"]
    q1 = quiz["questions"][0]

    start_response = client.post(f"/quizzes/{quiz_id}/attempts", headers=headers(2, "Student"))
    assert start_response.status_code == 201
    attempt_id = start_response.json()["id"]

    db_override = app.dependency_overrides[get_db]()
    db = next(db_override)
    try:
        attempt = db.get(models.Attempt, attempt_id)
        assert attempt is not None
        attempt.started_at = models.utc_now() - timedelta(minutes=16)
        db.commit()
    finally:
        db_override.close()

    response = client.put(
        f"/attempts/{attempt_id}/answers/{q1['position']}",
        json={"selected_option": 2},
        headers=headers(2),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Time limit exceeded. Finish the attempt to get the result."


def test_creator_can_list_attempts_for_quiz(client: TestClient) -> None:
    quiz = create_quiz(client)
    quiz_id = quiz["id"]
    q1 = quiz["questions"][0]

    attempt_response = client.post(f"/quizzes/{quiz_id}/attempts", headers=headers(2, "Student"))
    attempt_id = attempt_response.json()["id"]
    client.put(
        f"/attempts/{attempt_id}/answers/{q1['position']}",
        json={"selected_option": 2},
        headers=headers(2),
    )
    client.post(f"/attempts/{attempt_id}/finish", headers=headers(2))

    unauthorized = client.get(f"/quizzes/{quiz_id}/attempts", headers=headers(2))
    assert unauthorized.status_code == 403

    response = client.get(f"/quizzes/{quiz_id}/attempts", headers=headers(1))
    assert response.status_code == 200
    attempts = response.json()
    assert len(attempts) == 1
    assert attempts[0]["user_name"] == "Student"
    assert attempts[0]["score"] == 50.0
