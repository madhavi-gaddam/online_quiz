# Online Quiz Exam Backend

Phase 1 backend service for creating and taking MCQ quizzes.

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

- `POST /quizzes` - create a quiz
- `POST /quizzes/{quiz_id}/attempts` - start an attempt
- `PUT /attempts/{attempt_id}/answers/{question_position}` - submit or overwrite an answer using option number 1-4
- `POST /attempts/{attempt_id}/finish` - finish and score an attempt
- `GET /attempts/{attempt_id}/result` - get attempt result
- `GET /quizzes/{quiz_id}/attempts` - creator lists all attempts for a quiz

User identity is represented by headers for this phase:

- `X-User-Id`
- `X-User-Name` optional; send once when creating/updating the user name
