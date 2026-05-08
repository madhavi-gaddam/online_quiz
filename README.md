# Online Quiz Exam Backend

Backend service for creating, browsing, and taking MCQ quizzes.

## Stack

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set a PostgreSQL connection string:

```powershell
$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/online_quiz_exam"
```

Run the API:

```powershell
uvicorn app.main:app --reload
```

The API will create tables on startup for Phase 1 simplicity. In a production phase, replace this with Alembic migrations.

## Main Endpoints

- `GET /quizzes` - list available quizzes
- `POST /quizzes` - create a quiz
- `GET /quizzes/{quiz_id}` - get quiz details without correct answers
- `POST /quizzes/{quiz_id}/attempts` - start an attempt
- `GET /attempts/{attempt_id}` - resume an attempt and see saved answers/progress
- `PUT /attempts/{attempt_id}/answers/{question_position}` - submit or overwrite an answer using option number 1-4
- `POST /attempts/{attempt_id}/finish` - finish and score an attempt
- `GET /attempts/{attempt_id}/result` - get attempt result
- `GET /quizzes/{quiz_id}/attempts` - creator lists all attempts for a quiz

Attempts are lazily expired when an active attempt is accessed after its quiz time limit. The API scores submitted answers, marks the attempt `expired`, sets `completed_at`, and returns `409` with `{"detail": "Attempt has expired"}` for the request that detected expiry.

User identity is represented by headers for this phase:

- `X-User-Id`
- `X-User-Name` optional; send once when creating/updating the user name
