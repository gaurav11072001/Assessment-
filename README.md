# Assessment-

A professional Flask web application for **Aptitude + Reasoning** assessments with role-based
question sets for **Embedded** and **Python Developer** roles.

---

## Features

### Student Side
- **Registration** — full name + email, with duplicate detection (a name or email can register only once)
- **Resume** — already-registered students can restore their session and continue
- **60-question test** — `20 Aptitude + 20 Reasoning + 20 Role-Specific` for the chosen role
- **1-hour timer** — enforced server-side, auto-submits when it expires
- **Tab-switch monitoring** — every window/tab switch raises a warning; **3 warnings auto-submits** the exam
- **Copy protection** — copy, cut, paste, print, drag, `Ctrl+C/X/A/S/P/U` and `F12` are blocked on question pages
- **Exam lock** — once submitted, that exam can never be taken again by the same candidate
- **Result page** — overall score, section-wise breakdown, time taken and warning count

### Admin Side
- Password-protected admin console (`/admin/login`)
- Dashboard with registered students, submitted attempts, average score and pending count
- Per-student result detail with section-wise performance bars
- "Reset All Data" action to clear the database

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3 / Flask |
| WSGI server | Gunicorn (`gthread` workers) |
| Templates | Jinja2 |
| Database | PostgreSQL on Render (SQLite for local dev) |
| Frontend | Vanilla HTML / CSS / JS |
| Design | White background, charcoal `#2c3e50`, blue `#2563eb`, orange `#ff9800` |

---

## Project Structure

```
.
├── app.py                  # Flask app, question bank, routes
├── db.py                   # DB layer (PostgreSQL + SQLite), pooling, schema
├── gunicorn.conf.py        # Production WSGI config
├── render.yaml             # Render blueprint (web service + postgres)
├── Procfile                # Render/Heroku start command
├── requirements.txt
├── runtime.txt
├── .gitignore
├── README.md
├── static/
│   ├── style.css           # Global stylesheet
│   ├── examportal-logo.svg
│   └── logo.png
├── templates/
│   ├── base.html           # Shell + global copy protection
│   ├── index.html          # Landing page
│   ├── old_index.html      # Role selection
│   ├── register.html       # Student registration
│   ├── resume.html         # Resume registered exam
│   ├── quiz.html           # Exam UI, timer, violation monitor
│   ├── result.html         # Student result
│   ├── admin_login.html    # Admin sign-in
│   ├── admin_dashboard.html
│   └── admin_attempt.html  # Admin result detail
└── examportal.db           # SQLite (local dev only, auto-created)
```

---

## Installation

```bash
git clone https://github.com/gaurav11072001/Assessment-.git
cd Assessment-
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open <http://127.0.0.1:5000> in your browser.

---

## Deploy on Render

### One-click via Blueprint

1. Push this repo to GitHub (done).
2. In Render, choose **New → Blueprint**, select the repo — `render.yaml` is picked up automatically.
3. Render creates:
   - `assessment` web service (Python 3.11, `standard` plan)
   - `assessment-db` PostgreSQL database (free tier)
4. Set the admin password when prompted (`ADMIN_USER` / `ADMIN_PASSWORD`).
5. The app is live on the generated URL.

### Manual setup

| Setting | Value |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --config gunicorn.conf.py` |
| Health Check Path | `/healthz` |
| Instance Type | `standard` (recommended for exam day) |

Environment variables:

| Key | Value | Notes |
|---|---|---|
| `DATABASE_URL` | auto | From the Render Postgres `connectionString` |
| `EXAMPORTAL_SECRET` | auto-generated | Signs the session cookie |
| `ADMIN_USER` / `ADMIN_PASSWORD` | set manually | Admin console login |
| `WEB_CONCURRENCY` | `4` | Gunicorn worker processes |
| `WEB_THREADS` | `8` | Threads per worker |
| `PG_POOL_SIZE` | `4` | Max pooled Postgres connections |
| `COOKIE_SECURE` | `1` | Secure flag (Render serves HTTPS) |
| `EXAM_DURATION` | `3600` | Exam seconds |
| `MAX_VIOLATIONS` | `3` | Tab-switch warnings before auto-submit |

---

## Capacity

Measured locally against the full exam flow (register → 60 questions → submit → result):

| Concurrent students | Total requests | Wall time | Throughput | Errors |
|---|---|---|---|---|
| 80 | 9,920 | 17.0s | 583 req/s | 0 |
| 200 | 24,800 | 32.5s | 764 req/s | 0 |
| 400 | 49,600 | 77.7s | 638 req/s | 0 |

Tested on a **single** process with SQLite. Production runs 4 Gunicorn workers
(4 × 8 = 32 concurrent handlers) on PostgreSQL, so headroom is significantly larger.

Realistic exam load is far below this: 80 students refreshing a question page
every ~30 seconds is only ~3 requests/second.

### Sizing guidance

| Candidates | Plan | Workers × Threads |
|---|---|---|
| up to ~100 | `starter` (512 MB, 0.5 CPU) | 2 × 8 |
| up to ~400 | `standard` (2 GB, 1 CPU) | 4 × 8 |

> **Important:** do not use the Render *free* web service for a live exam.
> Free instances spin down after 15 minutes of inactivity and would drop
> candidates mid-exam, and the free tier's 512 MB / 0.5 CPU is marginal.
> Use `starter` at minimum, `standard` for comfort. The free Postgres plan
> is fine (it allows 5 connections; the pool is capped at 4).

### Concurrency notes

- **All exam state lives in PostgreSQL**, not in the session cookie. The cookie
  carries only a session ID (~190 bytes), so the 4 KB browser cookie limit is
  never a risk.
- Postgres access goes through a **threaded connection pool** so the process
  never exceeds the database's connection limit.
- Every query is **indexed** (`lower(email)`, `lower(full_name)`, `(email, role)`).
- Attempts carry a **unique constraint** on `(email, role)`, so 10 concurrent
  submits for the same student still create exactly one result row.
- Stale `exam_sessions` rows are garbage-collected opportunistically.

---

## Default Admin Credentials

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin123` |

Override with environment variables (`ADMIN_USER` / `ADMIN_PASSWORD`).

---

## Routes

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Landing page |
| `GET` | `/role-select` | Choose role |
| `GET/POST` | `/register` | Student registration |
| `GET/POST` | `/resume` | Resume registered exam |
| `GET` | `/start/<role>` | Begin exam (locks if already submitted) |
| `GET/POST` | `/quiz` | Question page |
| `POST` | `/violation` | Record a tab-switch warning |
| `GET/POST` | `/submit` | Submit exam and record the attempt |
| `GET` | `/result` | Student result |
| `GET` | `/healthz` | Health / DB status probe |
| `GET/POST` | `/admin/login` | Admin sign-in |
| `GET` | `/admin` | Admin dashboard (admin only) |
| `GET` | `/admin/attempt/<id>` | Result detail (admin only) |
| `GET` | `/admin/logout` | Admin sign-out |

---

## Notes

- With `DATABASE_URL` unset the app falls back to SQLite (`examportal.db`) so
  local development needs no setup. It is excluded from git.
- The database schema is created automatically on startup — idempotent and
  safe to run from multiple workers.
- Exam duration, warning limit, admin credentials, session secret and pool
  sizing are all configurable via environment variables.

