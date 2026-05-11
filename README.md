# Online Quiz Exam Backend

Backend service for creating, browsing, and taking time-limited MCQ quizzes with JWT auth.

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

The API creates tables on startup for local development simplicity. Because Phase 3 changes the user table from header-based prototype users to JWT users, delete the old local SQLite file once if you are using the default database:

```powershell
Remove-Item .\online_quiz_exam.db
```

In production, use Alembic migrations instead of `create_all`.

## Main Endpoints

- `POST /auth/register` - create a teacher or student account
- `POST /auth/login` - get a bearer access token
- `GET /quizzes` - list available quizzes
- `POST /quizzes` - teacher creates a quiz
- `GET /quizzes/{quiz_id}` - get quiz details without correct answers
- `GET /quizzes/{quiz_id}/answers` - teacher gets correct answers for their own quiz
- `POST /quizzes/{quiz_id}/attempts` - student starts an attempt
- `GET /attempts/{attempt_id}` - student resumes their attempt and sees saved answers/progress
- `PUT /attempts/{attempt_id}/answers/{question_position}` - student submits or overwrites an answer using option number 1-4
- `POST /attempts/{attempt_id}/finish` - student finishes and scores an attempt
- `GET /attempts/{attempt_id}/result` - get attempt result
- `GET /quizzes/{quiz_id}/attempts` - teacher lists all attempts for their own quiz

Attempts are lazily expired when an active attempt is accessed after its quiz time limit. The API scores submitted answers, marks the attempt `expired`, sets `completed_at`, and returns `409` with `{"detail": "Attempt has expired"}` for the request that detected expiry.

## Auth Examples

Register:

```json
{
  "username": "teacher1",
  "email": "teacher1@example.com",
  "password": "secret123",
  "role": "TEACHER"
}
```

Login uses JSON at `POST /auth/login`:

```json
{
  "username": "teacher1",
  "password": "secret123"
}
```

Protected endpoints require:

```text
Authorization: Bearer <access_token>
```

Students can see selected options on active attempts, but scores, correctness, and correct answers are hidden until their attempt is `completed` or `expired`. Teachers can view correct answers and attempt analytics only for quizzes they created.
