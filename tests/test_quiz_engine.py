from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, services
from app.database import Base, get_db
from app.main import app


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


def register(client: TestClient, username: str, role: str) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "secret123",
            "role": role,
        },
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, username: str, password: str = "secret123") -> str:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def setup_users(client: TestClient) -> dict[str, str]:
    register(client, "teacher1", "TEACHER")
    register(client, "teacher2", "TEACHER")
    register(client, "student1", "STUDENT")
    register(client, "student2", "STUDENT")
    return {
        "teacher1": login(client, "teacher1"),
        "teacher2": login(client, "teacher2"),
        "student1": login(client, "student1"),
        "student2": login(client, "student2"),
    }


def quiz_payload(time_limit_minutes: int = 15) -> dict:
    return {
        "title": "Python Basics",
        "description": "A quick check of Python fundamentals.",
        "time_limit_minutes": time_limit_minutes,
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


def create_quiz(client: TestClient, teacher_token: str, time_limit_minutes: int = 15) -> dict:
    response = client.post(
        "/quizzes",
        json=quiz_payload(time_limit_minutes),
        headers=auth_header(teacher_token),
    )
    assert response.status_code == 201
    return response.json()


def start_attempt(client: TestClient, quiz_id: int, student_token: str) -> dict:
    response = client.post(f"/quizzes/{quiz_id}/attempts", headers=auth_header(student_token))
    assert response.status_code == 201
    return response.json()


def submit_answer(
    client: TestClient,
    attempt_id: int,
    question_position: int,
    selected_option: int,
    student_token: str,
) -> dict:
    response = client.put(
        f"/attempts/{attempt_id}/answers/{question_position}",
        json={"selected_option": selected_option},
        headers=auth_header(student_token),
    )
    assert response.status_code == 200
    return response.json()


def test_register_login_invalid_password_and_invalid_token(client: TestClient) -> None:
    user = register(client, "teacher1", "TEACHER")
    assert user["username"] == "teacher1"
    assert user["role"] == "TEACHER"

    token = login(client, "teacher1")
    assert token

    invalid_password = client.post(
        "/auth/login",
        json={"username": "teacher1", "password": "wrong"},
    )
    assert invalid_password.status_code == 401

    invalid_token = client.post(
        "/quizzes",
        json=quiz_payload(),
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert invalid_token.status_code == 401


def test_protected_endpoint_rejects_missing_token(client: TestClient) -> None:
    response = client.post("/quizzes", json=quiz_payload())

    assert response.status_code == 401


def test_student_cannot_create_quiz_and_teacher_can(client: TestClient) -> None:
    tokens = setup_users(client)

    forbidden = client.post("/quizzes", json=quiz_payload(), headers=auth_header(tokens["student1"]))
    assert forbidden.status_code == 403

    quiz = create_quiz(client, tokens["teacher1"])
    assert quiz["title"] == "Python Basics"
    assert "is_correct" not in quiz["questions"][0]["options"][0]


def test_teacher_cannot_take_own_quiz_and_students_can_attempt(client: TestClient) -> None:
    tokens = setup_users(client)
    quiz = create_quiz(client, tokens["teacher1"])

    teacher_attempt = client.post(f"/quizzes/{quiz['id']}/attempts", headers=auth_header(tokens["teacher1"]))
    assert teacher_attempt.status_code == 403

    student_attempt = client.post(f"/quizzes/{quiz['id']}/attempts", headers=auth_header(tokens["student1"]))
    assert student_attempt.status_code == 201


def test_student_cannot_access_other_student_attempt(client: TestClient) -> None:
    tokens = setup_users(client)
    quiz = create_quiz(client, tokens["teacher1"])
    attempt = start_attempt(client, quiz["id"], tokens["student1"])

    response = client.get(f"/attempts/{attempt['id']}/result", headers=auth_header(tokens["student2"]))

    assert response.status_code == 403


def test_teacher_cannot_access_another_teachers_quiz_answers_or_attempts(client: TestClient) -> None:
    tokens = setup_users(client)
    quiz = create_quiz(client, tokens["teacher1"])
    attempt = start_attempt(client, quiz["id"], tokens["student1"])

    answers = client.get(f"/quizzes/{quiz['id']}/answers", headers=auth_header(tokens["teacher2"]))
    assert answers.status_code == 403

    attempts = client.get(f"/quizzes/{quiz['id']}/attempts", headers=auth_header(tokens["teacher2"]))
    assert attempts.status_code == 403

    result = client.get(f"/attempts/{attempt['id']}/result", headers=auth_header(tokens["teacher2"]))
    assert result.status_code == 403


def test_teacher_can_view_own_quiz_answers_and_attempts(client: TestClient) -> None:
    tokens = setup_users(client)
    quiz = create_quiz(client, tokens["teacher1"])
    attempt = start_attempt(client, quiz["id"], tokens["student1"])
    submit_answer(client, attempt["id"], 1, 2, tokens["student1"])
    client.post(f"/attempts/{attempt['id']}/finish", headers=auth_header(tokens["student1"]))

    answers = client.get(f"/quizzes/{quiz['id']}/answers", headers=auth_header(tokens["teacher1"]))
    assert answers.status_code == 200
    assert answers.json()["questions"][0]["options"][1]["is_correct"] is True

    attempts = client.get(f"/quizzes/{quiz['id']}/attempts", headers=auth_header(tokens["teacher1"]))
    assert attempts.status_code == 200
    assert attempts.json()[0]["user_name"] == "student1"


def test_answer_visibility_before_and_after_completion(client: TestClient) -> None:
    tokens = setup_users(client)
    quiz = create_quiz(client, tokens["teacher1"])
    attempt = start_attempt(client, quiz["id"], tokens["student1"])
    submit_answer(client, attempt["id"], 1, 2, tokens["student1"])

    active_result = client.get(f"/attempts/{attempt['id']}/result", headers=auth_header(tokens["student1"]))
    assert active_result.status_code == 200
    active_body = active_result.json()
    assert active_body["status"] == "active"
    assert active_body["score"] is None
    assert active_body["questions"][0]["selected_option"] == 2
    assert active_body["questions"][0]["is_correct"] is None
    assert active_body["questions"][0]["correct_option"] is None

    finish = client.post(f"/attempts/{attempt['id']}/finish", headers=auth_header(tokens["student1"]))
    assert finish.status_code == 200
    completed_body = finish.json()
    assert completed_body["status"] == "completed"
    assert completed_body["score"] == 50.0
    assert completed_body["questions"][0]["is_correct"] is True
    assert completed_body["questions"][0]["correct_option"] == 2


def test_answer_visibility_after_expiry(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = setup_users(client)
    quiz = create_quiz(client, tokens["teacher1"], time_limit_minutes=1)
    attempt = start_attempt(client, quiz["id"], tokens["student1"])
    started_at = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)

    db_override = app.dependency_overrides[get_db]()
    db = next(db_override)
    try:
        db_attempt = db.get(models.Attempt, attempt["id"])
        assert db_attempt is not None
        db_attempt.started_at = started_at
        db.commit()
    finally:
        db_override.close()

    monkeypatch.setattr(models, "utc_now", lambda: started_at + timedelta(seconds=30))
    submit_answer(client, attempt["id"], 1, 2, tokens["student1"])

    monkeypatch.setattr(models, "utc_now", lambda: started_at + timedelta(minutes=1, seconds=1))
    expired_submit = client.put(
        f"/attempts/{attempt['id']}/answers/2",
        json={"selected_option": 2},
        headers=auth_header(tokens["student1"]),
    )
    assert expired_submit.status_code == 409
    assert expired_submit.json()["detail"] == "Attempt has expired"

    result = client.get(f"/attempts/{attempt['id']}/result", headers=auth_header(tokens["student1"]))
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "expired"
    assert body["score"] == 50.0
    assert body["questions"][0]["is_correct"] is True
    assert body["questions"][0]["correct_option"] == 2

    db_override = app.dependency_overrides[get_db]()
    db = next(db_override)
    try:
        db_attempt = db.get(models.Attempt, attempt["id"])
        assert db_attempt is not None
        assert db_attempt.status == models.AttemptStatus.expired
        assert services.aware_utc(db_attempt.completed_at) == started_at + timedelta(minutes=1)
    finally:
        db_override.close()
