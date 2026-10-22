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
| Templates | Jinja2 |
| Database | SQLite (stdlib `sqlite3`) |
| Frontend | Vanilla HTML / CSS / JS |
| Design | White background, charcoal `#2c3e50`, blue `#2563eb`, orange `#ff9800` |

---

## Project Structure

```
.
├── app.py                  # Flask app, question bank, routes, SQLite layer
├── requirements.txt
├── .gitignore
├── README.md
├── static/
│   ├── style.css           # Global stylesheet
│   └── examportal-logo.svg
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
└── examportal.db           # SQLite database (auto-created on first run)
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

## Default Admin Credentials

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin123` |

Override with environment variables:

```bash
set ADMIN_USER=your_user
set ADMIN_PASSWORD=your_password
set EXAMPORTAL_SECRET=your_secret_key
```

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
| `GET/POST` | `/admin/login` | Admin sign-in |
| `GET` | `/admin` | Admin dashboard (admin only) |
| `GET` | `/admin/attempt/<id>` | Result detail (admin only) |
| `GET` | `/admin/logout` | Admin sign-out |

---

## Notes

- The SQLite database (`examportal.db`) is created automatically on first run and is excluded from git.
- Exam duration, warning limit, admin credentials and the secret key are all configurable via environment variables.
