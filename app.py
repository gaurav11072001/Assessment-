"""ExamPortal - Aptitude + Reasoning assessment platform.

Student side : registration, 1-hour timed exam, tab-switch monitoring, exam lock.
Admin side   : password protected dashboard of all student results.
"""

import json
import os
import random
import re
import time
from datetime import datetime
from functools import wraps

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)

import db

app = Flask(__name__)
app.secret_key = os.environ.get("EXAMPORTAL_SECRET", "dev-secret-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 6
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

EXAM_DURATION = int(os.environ.get("EXAM_DURATION", "3600"))
MAX_VIOLATIONS = int(os.environ.get("MAX_VIOLATIONS", "3"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


# ==========================================================================
# Question bank
# ==========================================================================

QUESTIONS = {
    "aptitude": [
        {"q": "If 5x + 3 = 28, what is x?", "options": ["4", "5", "6", "7"], "answer": "5"},
        {"q": "A train covers 120 km in 2 hours. What is its speed?", "options": ["40 km/h", "50 km/h", "60 km/h", "70 km/h"], "answer": "60 km/h"},
        {"q": "15% of 240 is?", "options": ["30", "36", "40", "45"], "answer": "36"},
        {"q": "Average of 10, 20, 30, 40, 50?", "options": ["20", "30", "40", "50"], "answer": "30"},
        {"q": "3 pens cost Rs 45. Cost of 7 pens?", "options": ["95", "100", "105", "110"], "answer": "105"},
        {"q": "Square root of 144?", "options": ["10", "11", "12", "13"], "answer": "12"},
        {"q": "A man buys for Rs 80 and sells for Rs 100. Profit %?", "options": ["20%", "25%", "30%", "35%"], "answer": "25%"},
        {"q": "LCM of 12 and 18?", "options": ["36", "48", "54", "72"], "answer": "36"},
        {"q": "Work done by A in 1 day if A completes work in 10 days?", "options": ["1/5", "1/10", "1/8", "1/12"], "answer": "1/10"},
        {"q": "Sum of first 10 natural numbers?", "options": ["45", "50", "55", "60"], "answer": "55"},
        {"q": "20% discount on a Rs 1500 item =?", "options": ["1100", "1200", "1250", "1300"], "answer": "1200"},
        {"q": "Ratio of 45 minutes to 1.5 hours?", "options": ["1:1", "1:2", "1:3", "2:3"], "answer": "1:2"},
        {"q": "If x:y = 2:3, then (3x+4y):(x+y)?", "options": ["18:5", "18:7", "20:5", "20:7"], "answer": "18:5"},
        {"q": "Perimeter of square with side 14 cm?", "options": ["48", "56", "64", "72"], "answer": "56"},
        {"q": "Simple interest on Rs 1000 at 5% for 2 years?", "options": ["50", "100", "150", "200"], "answer": "100"},
        {"q": "Cube of 5?", "options": ["125", "100", "75", "150"], "answer": "125"},
        {"q": "Probability of getting head in a coin toss?", "options": ["1/2", "1/4", "1", "0"], "answer": "1/2"},
        {"q": "Area of circle radius 7 cm (pi = 22/7)?", "options": ["154", "144", "134", "124"], "answer": "154"},
        {"q": "1/4 + 1/2 =?", "options": ["3/4", "1/2", "1/4", "1"], "answer": "3/4"},
        {"q": "If 5 pens cost Rs 90, what is the cost of 8 pens?", "options": ["144", "136", "150", "160"], "answer": "144"},
    ],
    "reasoning": [
        {"q": "Find the odd one: Apple, Mango, Banana, Carrot", "options": ["Apple", "Mango", "Banana", "Carrot"], "answer": "Carrot"},
        {"q": "Complete: 2, 4, 8, 16, ?", "options": ["24", "30", "32", "36"], "answer": "32"},
        {"q": "If A=1, B=2, then C=?", "options": ["2", "3", "4", "1"], "answer": "3"},
        {"q": "Doctor is to Hospital as Teacher is to?", "options": ["School", "Home", "Office", "Park"], "answer": "School"},
        {"q": "Mirror image of 'M'?", "options": ["M", "W", "E", "3"], "answer": "M"},
        {"q": "Find missing: 5, 10, 20, 40, ?", "options": ["60", "80", "90", "100"], "answer": "80"},
        {"q": "'She is the daughter of my grandfather's only son.' Who is she?", "options": ["Sister", "Daughter", "Cousin", "Mother"], "answer": "Sister"},
        {"q": "Odd letter group: ACE, BDF, CEG, DFB", "options": ["ACE", "BDF", "CEG", "DFB"], "answer": "DFB"},
        {"q": "Today is Monday. After 61 days?", "options": ["Monday", "Tuesday", "Wednesday", "Thursday"], "answer": "Monday"},
        {"q": "Count triangles in a standard figure?", "options": ["3", "4", "5", "6"], "answer": "5"},
        {"q": "Book : Page :: ? : ?", "options": ["Tree : Leaf", "Car : Wheel", "House : Room", "All of these"], "answer": "All of these"},
        {"q": "If CAT is coded as DBU, then DOG =?", "options": ["EPH", "FPH", "DQH", "EPI"], "answer": "EPH"},
        {"q": "Find next: Z, Y, X, W, ?", "options": ["V", "U", "T", "S"], "answer": "V"},
        {"q": "Arrange: Seed, Plant, Tree, Fruit", "options": ["Seed Plant Tree Fruit", "Fruit Tree Plant Seed", "Plant Seed Tree Fruit", "Tree Fruit Seed Plant"], "answer": "Seed Plant Tree Fruit"},
        {"q": "P is Q's brother, R is Q's mother. P is R's?", "options": ["Son", "Daughter", "Father", "Brother"], "answer": "Son"},
        {"q": "Walk north 10m, turn right 10m. Now facing?", "options": ["North", "South", "East", "West"], "answer": "East"},
        {"q": "Day before yesterday was Sunday. Today?", "options": ["Monday", "Tuesday", "Wednesday", "Thursday"], "answer": "Tuesday"},
        {"q": "Missing number: 1, 4, 9, 16, ?", "options": ["20", "25", "30", "36"], "answer": "25"},
        {"q": "Strongest argument for 'Exercise is good'?", "options": ["It keeps fit", "It is costly", "It takes time", "It is boring"], "answer": "It keeps fit"},
        {"q": "Choose the word spelt correctly:", "options": ["Recommandation", "Recommendation", "Reccomendation", "Recommnedation"], "answer": "Recommendation"},
    ],
    "embedded": [
        {"q": "Which chip powers the NodeMCU 1.0 board and has Wi-Fi but no Bluetooth?", "options": ["ESP8266", "ESP32", "ATmega328P", "ATmega2560"], "answer": "ESP8266"},
        {"q": "On ESP32, which ADC unit becomes unreliable while Wi-Fi is active?", "options": ["ADC2", "ADC1", "DAC1", "DAC2"], "answer": "ADC2"},
        {"q": "Which ESP32 peripheral is used to generate PWM for dimming or motor speed?", "options": ["LEDC", "MCPWM only", "SysTick", "RTC"], "answer": "LEDC"},
        {"q": "In the Arduino IDE, which function must be called before digitalWrite() on a pin?", "options": ["pinMode()", "analogRead()", "attachInterrupt()", "delay()"], "answer": "pinMode()"},
        {"q": "On an Arduino Uno (ATmega328P), which pins support analogWrite() PWM?", "options": ["3, 5, 6, 9, 10, 11", "0, 1, 2, 3, 4, 5", "2, 4, 6, 8, 10, 12", "Every digital pin"], "answer": "3, 5, 6, 9, 10, 11"},
        {"q": "Embedded C: which qualifier tells the compiler a value can change outside normal program flow (ISR or hardware register)?", "options": ["volatile", "static", "register", "const"], "answer": "volatile"},
        {"q": "Embedded C on AVR: which intrinsic globally disables interrupts?", "options": ["cli()", "sei()", "reti()", "nop()"], "answer": "cli()"},
        {"q": "Arduino Uno ADC read returns 512 with a 5 V reference. What voltage is measured?", "options": ["2.5 V", "1.25 V", "5.0 V", "0.5 V"], "answer": "2.5 V"},
        {"q": "A TSOP1738 style IR receiver module idles at which logic level and pulses which way on a carrier burst?", "options": ["Idle HIGH, goes LOW", "Idle LOW, goes HIGH", "Idle HIGH, goes HIGH", "Floating, no change"], "answer": "Idle HIGH, goes LOW"},
        {"q": "An HC-SR501 PIR module triggers on what?", "options": ["Change in infrared emitted by a moving warm body", "Ultrasonic echo return time", "Reflected visible light", "Magnetic field variation"], "answer": "Change in infrared emitted by a moving warm body"},
        {"q": "For HC-SR04, which formula gives distance in cm using the echo pulse width?", "options": ["(echo_us x 0.0343) / 2", "echo_us x 0.0343", "echo_us / 0.0343", "(echo_us x 2) / 0.0343"], "answer": "(echo_us x 0.0343) / 2"},
        {"q": "HC-SR04 needs a trigger pulse of minimum width:", "options": ["10 microseconds", "10 milliseconds", "1 microsecond", "100 nanoseconds"], "answer": "10 microseconds"},
        {"q": "An SG90 servo at 1.5 ms pulse width points to:", "options": ["90 degrees (centre)", "0 degrees", "180 degrees", "It does not move"], "answer": "90 degrees (centre)"},
        {"q": "Which PWM frame rate is required for a standard hobby servo like SG90?", "options": ["50 Hz", "500 Hz", "1 kHz", "20 kHz"], "answer": "50 Hz"},
        {"q": "The L298N module contains how many full H-bridges, allowing bidirectional drive of how many DC motors?", "options": ["2 H-bridges, 2 motors", "1 H-bridge, 1 motor", "4 H-bridges, 4 motors", "2 H-bridges, 4 motors"], "answer": "2 H-bridges, 2 motors"},
        {"q": "On an L298N, what does the ENA pin control?", "options": ["Enable and PWM speed of motor A", "Direction of motor A", "Logic supply voltage", "Reset of the bridge"], "answer": "Enable and PWM speed of motor A"},
        {"q": "Why must the L298N ground be tied to the microcontroller ground?", "options": ["Logic levels need a shared voltage reference", "It increases motor torque", "It reduces heat in the bridge", "It steps up battery voltage"], "answer": "Logic levels need a shared voltage reference"},
        {"q": "In the Arduino IDE, which board target fits a bare ATmega328P with a 16 MHz crystal and no USB chip?", "options": ["Arduino Pro Mini", "Arduino Uno", "NodeMCU 1.0", "Arduino Due"], "answer": "Arduino Pro Mini"},
        {"q": "ESP32 is programmed by default over UART0 on which pins?", "options": ["GPIO1 (TX) and GPIO3 (RX)", "GPIO21 and GPIO22", "GPIO16 and GPIO17", "GPIO34 and GPIO35"], "answer": "GPIO1 (TX) and GPIO3 (RX)"},
        {"q": "In a simple transistor-driven DC motor circuit, which component clamps the back-EMF spike?", "options": ["Flyback diode across the motor", "Pull-up resistor on the base", "Series capacitor", "Zener across the supply only"], "answer": "Flyback diode across the motor"},
    ],
    "python": [
        {"q": "Which keyword is used to define a function in Python?", "options": ["def", "func", "define", "function"], "answer": "def"},
        {"q": "How many values does a Python function return by default?", "options": ["One", "Two", "All", "None"], "answer": "None"},
        {"q": "Output of def add(a, b=5): return a + b; print(add(3))?", "options": ["3", "8", "5", "Error"], "answer": "8"},
        {"q": "Which calls a function with keyword arguments?", "options": ["f(x=1)", "f(1)", "f::x", "call f 1"], "answer": "f(x=1)"},
        {"q": "A lambda function is a function without what?", "options": ["A name", "Body", "Arguments", "Return"], "answer": "A name"},
        {"q": "Output of i = 0 / while i < 3: / print(i) / i += 1?", "options": ["0 1 2", "1 2 3", "0 1 2 3", "1 2"], "answer": "0 1 2"},
        {"q": "Which loop is used when the number of iterations is unknown?", "options": ["while", "for", "if", "map"], "answer": "while"},
        {"q": "What breaks a while loop immediately?", "options": ["break", "stop", "exit", "return"], "answer": "break"},
        {"q": "To skip the rest of a loop body, use?", "options": ["continue", "break", "pass", "skip"], "answer": "continue"},
        {"q": "How do you import NumPy?", "options": ["import numpy as np", "include numpy", "require numpy", "load numpy"], "answer": "import numpy as np"},
        {"q": "How do you create a NumPy array from [1,2,3]?", "options": ["np.array([1,2,3])", "np.list([1,2,3])", "np.matrix([1,2,3])", "np.data([1,2,3])"], "answer": "np.array([1,2,3])"},
        {"q": "Shape of np.zeros((2,3))?", "options": ["(2, 3)", "(3, 2)", "(6,)", "(2, 2)"], "answer": "(2, 3)"},
        {"q": "Which NumPy function gives the sum of an array?", "options": ["np.sum(a)", "np.add(a)", "np.total(a)", "np.plus(a)"], "answer": "np.sum(a)"},
        {"q": "How do you import pandas?", "options": ["import pandas as pd", "import panda as pd", "include pandas", "require pandas"], "answer": "import pandas as pd"},
        {"q": "How do you create a pandas DataFrame?", "options": ["pd.DataFrame(data)", "pd.Frame(data)", "pd.Table(data)", "pd.Create(data)"], "answer": "pd.DataFrame(data)"},
        {"q": "Pandas: df.head() shows?", "options": ["First 5 rows", "Last 5 rows", "All rows", "Column names"], "answer": "First 5 rows"},
        {"q": "Pandas: df['col'] gives?", "options": ["That column as a Series", "A row", "A copy of DataFrame", "Nothing"], "answer": "That column as a Series"},
        {"q": "Pandas: df.dropna() does what?", "options": ["Removes rows with missing values", "Fills missing values", "Sorts data", "Renames columns"], "answer": "Removes rows with missing values"},
        {"q": "Output of x = 10 / if x > 5: / print('Big') / else: / print('Small')?", "options": ["Big", "Small", "10", "Error"], "answer": "Big"},
        {"q": "Which keyword marks the alternative branch of an if?", "options": ["else", "elif only", "otherwise", "case"], "answer": "else"},
    ],
}

ROLES = {
    "embedded": "Embedded Role",
    "python": "Python Developer Role",
}


# ==========================================================================
# Data access helpers
# ==========================================================================

def find_registration(full_name, email):
    return db.query_one(
        "SELECT full_name, email FROM registrations "
        "WHERE lower(full_name) = lower(?) OR lower(email) = lower(?)",
        (full_name, email)
    )


def create_registration(full_name, email):
    try:
        db.insert_ignore(
            "registrations",
            ["full_name", "email", "created_at"],
            [full_name, email, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        )
        return db.query_one(
            "SELECT id FROM registrations WHERE lower(email) = lower(?)", (email,)
        ) is not None
    except Exception:
        return False


def get_attempt(email, role):
    if not email or not role:
        return None
    return db.query_one(
        "SELECT * FROM attempts WHERE lower(email) = lower(?) AND role = ?",
        (email, role)
    )


def save_attempt(email, full_name, role, correct, total, percentage,
                 breakdown, violations, time_taken):
    try:
        db.insert_ignore(
            "attempts",
            ["email", "full_name", "role", "correct", "total", "percentage",
             "breakdown", "violations", "time_taken", "submitted_at"],
            [email, full_name, role, correct, total, percentage,
             json.dumps(breakdown), violations, time_taken,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        )
    except Exception:
        pass


def _row_get(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def load_exam(sid):
    if not sid:
        return None
    row = db.query_one("SELECT * FROM exam_sessions WHERE sid = ?", (sid,))
    if not row:
        return None
    return {
        "sid": row["sid"],
        "student_email": row["student_email"],
        "student_name": row["student_name"],
        "role": row["role"],
        "category_order": json.loads(row["category_order"]),
        "answers": json.loads(row["answers"]),
        "q_order": json.loads(_row_get(row, "q_order", "{}")),
        "seed": _row_get(row, "seed", ""),
        "cat_index": row["cat_index"],
        "q_index": row["q_index"],
        "violations": row["violations"],
        "started_at": row["started_at"],
        "deadline": row["deadline"],
        "submitted_at": row["submitted_at"],
    }


def save_exam(exam):
    db.execute(
        "UPDATE exam_sessions SET answers = ?, cat_index = ?, q_index = ?, "
        "violations = ?, submitted_at = ? WHERE sid = ?",
        (json.dumps(exam["answers"]), exam["cat_index"], exam["q_index"],
         exam["violations"], exam["submitted_at"], exam["sid"])
    )


def create_exam(email, name, role):
    sid = db.new_sid()
    now = time.time()
    seed = "%s-%s" % (sid, os.urandom(6).hex())
    db.execute(
        "INSERT INTO exam_sessions (sid, student_email, student_name, role, "
        "category_order, answers, q_order, seed, cat_index, q_index, violations, "
        "started_at, deadline, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)",
        (sid, email, name, role, json.dumps(["aptitude", "reasoning", role]),
         json.dumps({}), json.dumps(build_q_order(seed)), seed,
         now, now + EXAM_DURATION,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    return sid


def build_q_order(seed):
    """Per-student shuffled question order: category -> list of question indexes."""
    order = {}
    for category, questions in QUESTIONS.items():
        idxs = list(range(len(questions)))
        random.Random("%s|%s" % (seed, category)).shuffle(idxs)
        order[category] = idxs
    return order


def exam_q_order(exam):
    """Shuffled order for this exam, falling back to natural order if absent."""
    stored = exam.get("q_order") or {}
    if not isinstance(stored, dict):
        stored = {}
    order = {}
    for category in exam["category_order"]:
        n = len(QUESTIONS.get(category, []))
        idxs = stored.get(category)
        if not isinstance(idxs, list) or sorted(idxs) != list(range(n)):
            idxs = list(range(n))
        order[category] = idxs
    return order


def exam_options(exam, category, orig_index):
    """Deterministic per-student option order for one question."""
    options = list(QUESTIONS[category][orig_index]["options"])
    seed = exam.get("seed") or exam.get("sid") or ""
    random.Random("%s|%s|%d" % (seed, category, orig_index)).shuffle(options)
    return options


def compute_result(exam):
    total = 0
    correct = 0
    breakdown = {}
    order = exam_q_order(exam)
    for category in exam["category_order"]:
        questions = QUESTIONS.get(category, [])
        cat_correct = 0
        for orig_index in order[category]:
            total += 1
            key = "%s_%d" % (category, orig_index)
            if exam["answers"].get(key) == questions[orig_index]["answer"]:
                correct += 1
                cat_correct += 1
        breakdown[category] = {"correct": cat_correct, "total": len(questions)}
    percentage = round((correct / total) * 100) if total else 0
    return correct, total, percentage, breakdown


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


# ==========================================================================
# Public pages
# ==========================================================================

@app.route("/")
def index():
    return render_template("index.html", roles=ROLES)


@app.route("/role-select")
def index_role():
    return render_template("old_index.html", roles=ROLES)


@app.route("/ping")
def ping():
    """Cheap liveness probe for uptime monitors.

    Deliberately does NOT touch the database: a transient database blip
    must not make the uptime monitor report the site as down, and a monitor
    hit every few minutes must not hold a connection open.
    """
    return jsonify({"ok": True, "service": "examportal"}), 200


@app.route("/healthz")
def healthz():
    reachable = db.db_healthy()
    schema = db.schema_status()
    outage = db.db_outage_seconds()
    body = {
        "status": "ok" if reachable else "degraded",
        "schema": schema,
        "database": "postgresql" if db.IS_PG else "sqlite",
        "workers": os.environ.get("WEB_CONCURRENCY", "1"),
    }
    err = db.last_db_error()
    if err:
        body["error"] = err
        body["outage_seconds"] = int(outage)

    # Only report 503 once the database has been down for a while. A brief
    # blip must not fail Render's deploy health check or restart the app.
    degraded = (not reachable) and outage > 60
    return jsonify(body), (503 if degraded else 200)


@app.after_request
def set_cache_headers(response):
    """Cache static assets so 80 concurrent students share one download."""
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    elif request.path == "/healthz":
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


if ADMIN_PASSWORD == "admin123" or ADMIN_USER == "admin":
    app.logger.warning(
        "ADMIN CREDENTIALS ARE DEFAULTS (user=%r). Set ADMIN_USER and "
        "ADMIN_PASSWORD in the Render dashboard Environment tab before "
        "running a real exam.", ADMIN_USER)


# ==========================================================================
# Registration / resume
# ==========================================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    next_role = request.args.get("next", "") or request.form.get("next", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        name = request.form.get("name", "").strip()
        if not name:
            error = "Full name is required."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        else:
            same_session = session.get("student_email", "").lower() == email.lower()
            if same_session:
                session["student_name"] = name
                session.modified = True
            else:
                existing = find_registration(name, email)
                if existing:
                    if existing["email"].lower() == email.lower():
                        error = ("This email address is already registered. "
                                 "Each candidate can register only once.")
                    else:
                        error = ("The full name '%s' is already registered. "
                                 "Each candidate can register only once."
                                 % existing["full_name"])
                elif not create_registration(name, email):
                    error = ("This name or email is already registered. "
                             "Each candidate can register only once.")

            if not error:
                session["student_email"] = email
                session["student_name"] = name
                session.modified = True
                if next_role in QUESTIONS:
                    return redirect(url_for("start", role=next_role))
                return redirect(url_for("index_role"))
    return render_template("register.html", error=error, next_role=next_role,
                           student_name=session.get("student_name", ""),
                           student_email=session.get("student_email", ""))


@app.route("/resume", methods=["GET", "POST"])
def resume():
    error = None
    next_role = request.args.get("next", "") or request.form.get("next", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        name = request.form.get("name", "").strip()
        if not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        else:
            row = db.query_one(
                "SELECT full_name, email FROM registrations WHERE lower(email) = lower(?)",
                (email,)
            )
            if row is None:
                error = "No registration found for this email address. Please register first."
            elif name and row["full_name"].lower() != name.strip().lower():
                error = "Full name does not match the registered name for this email."
            else:
                session["student_email"] = row["email"]
                session["student_name"] = row["full_name"]
                session.modified = True
                latest = db.query_one(
                    "SELECT role FROM attempts WHERE lower(email) = lower(?) "
                    "ORDER BY submitted_at DESC LIMIT 1", (email,)
                )
                if latest:
                    session["role"] = latest["role"]
                if next_role in QUESTIONS:
                    return redirect(url_for("start", role=next_role))
                if latest:
                    return redirect(url_for("result"))
                return redirect(url_for("index_role"))
    return render_template("resume.html", error=error, next_role=next_role)


# ==========================================================================
# Exam flow
# ==========================================================================

@app.route("/start/<role>")
def start(role):
    if role not in QUESTIONS:
        return redirect(url_for("index"))
    email = session.get("student_email")
    if not email:
        return redirect(url_for("register", next=role))

    # A submitted exam can never be taken again.
    if get_attempt(email, role):
        session["role"] = role
        session.modified = True
        return redirect(url_for("result"))

    # Opportunistic cleanup of stale sessions.
    if random.random() < 0.02:
        db.cleanup_expired_sessions()

    sid = create_exam(email, session.get("student_name", ""), role)
    session["sid"] = sid
    session["role"] = role
    session.permanent = True
    session.modified = True
    return redirect(url_for("quiz"))


@app.route("/violation", methods=["POST"])
def violation():
    exam = load_exam(session.get("sid"))
    if not exam:
        return jsonify({"violations": MAX_VIOLATIONS, "max": MAX_VIOLATIONS,
                        "auto_submit": True})
    exam["violations"] += 1
    save_exam(exam)
    return jsonify({"violations": exam["violations"], "max": MAX_VIOLATIONS,
                    "auto_submit": exam["violations"] >= MAX_VIOLATIONS})


@app.route("/submit", methods=["GET", "POST"])
def submit():
    exam = load_exam(session.get("sid"))
    if not exam:
        role = session.get("role")
        if not role:
            return redirect(url_for("index"))
        email = session.get("student_email")
        attempt = get_attempt(email, role)
        if attempt:
            return redirect(url_for("result"))
        return redirect(url_for("index"))

    if exam["submitted_at"] is None:
        exam["submitted_at"] = time.time()
        correct, total, percentage, breakdown = compute_result(exam)
        time_taken = max(0, int(exam["submitted_at"] - (exam["started_at"] or exam["submitted_at"])))
        save_attempt(exam["student_email"], exam["student_name"], exam["role"],
                     correct, total, percentage, breakdown,
                     exam["violations"], time_taken)
        save_exam(exam)
    return redirect(url_for("result"))


@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    exam = load_exam(session.get("sid"))
    if not exam:
        return redirect(url_for("index"))

    role = exam["role"]

    # Locked: this exam was already submitted.
    if get_attempt(exam["student_email"], role):
        return redirect(url_for("result"))

    deadline = exam["deadline"]
    if deadline is not None and time.time() > deadline:
        return redirect(url_for("submit"))

    order = exam["category_order"]
    cat_index = exam["cat_index"]
    q_index = exam["q_index"]

    if cat_index >= len(order):
        return redirect(url_for("submit"))

    category = order[cat_index]
    questions = QUESTIONS[category]
    cat_order = exam_q_order(exam)[category]

    if request.method == "POST":
        ans = request.form.get("answer")
        if ans is not None and q_index < len(cat_order):
            exam["answers"]["%s_%d" % (category, cat_order[q_index])] = ans
        if q_index + 1 < len(questions):
            exam["q_index"] = q_index + 1
        else:
            exam["cat_index"] = cat_index + 1
            exam["q_index"] = 0
        save_exam(exam)
        return redirect(url_for("quiz"))

    if q_index >= len(questions):
        exam["cat_index"] = cat_index + 1
        exam["q_index"] = 0
        save_exam(exam)
        return redirect(url_for("quiz"))

    orig_index = cat_order[q_index] if q_index < len(cat_order) else q_index
    question = {
        "q": questions[orig_index]["q"],
        "options": exam_options(exam, category, orig_index),
    }
    progress = {
        "category": category,
        "cat_label": ROLES.get(category, category.title()),
        "q_num": q_index + 1,
        "q_total": len(questions),
        "cat_index": cat_index,
        "cat_total": len(order),
    }
    remaining = max(0, int(deadline - time.time())) if deadline else EXAM_DURATION
    return render_template("quiz.html", question=question, progress=progress,
                           remaining=remaining,
                           violations=exam["violations"],
                           max_violations=MAX_VIOLATIONS,
                           student_name=exam["student_name"])


@app.route("/result")
def result():
    email = session.get("student_email")
    role = session.get("role")
    exam = load_exam(session.get("sid"))

    if exam:
        email = email or exam["student_email"]
        role = role or exam["role"]

    attempt = get_attempt(email, role)
    if attempt:
        breakdown = json.loads(attempt["breakdown"])
        correct = attempt["correct"]
        total = attempt["total"]
        percentage = attempt["percentage"]
        violations = attempt["violations"]
        time_taken = attempt["time_taken"]
        student_name = attempt["full_name"]
        student_email = attempt["email"]
        already = True
    elif exam:
        correct, total, percentage, breakdown = compute_result(exam)
        violations = exam["violations"]
        time_taken = max(0, int(time.time() - (exam["started_at"] or time.time())))
        student_name = exam["student_name"]
        student_email = exam["student_email"]
        already = False
    else:
        return redirect(url_for("index"))

    return render_template("result.html", role=ROLES.get(role, role), ROLES=ROLES,
                           correct=correct, total=total, percentage=percentage,
                           breakdown=breakdown,
                           student_name=student_name,
                           student_email=student_email,
                           violations=violations,
                           time_taken=time_taken,
                           already_submitted=already)


@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))


# ==========================================================================
# Admin
# ==========================================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("username", "") == ADMIN_USER and \
           request.form.get("password", "") == ADMIN_PASSWORD:
            session["admin"] = True
            session.modified = True
            return redirect(url_for("admin_dashboard"))
        error = "Invalid admin credentials."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    session.modified = True
    return redirect(url_for("admin_login"))


@app.route("/admin")
@app.route("/admin/")
@admin_required
def admin_dashboard():
    attempts = db.query_all("SELECT * FROM attempts ORDER BY submitted_at DESC")
    registrations = db.query_all("SELECT * FROM registrations ORDER BY created_at DESC")

    total_students = len(registrations)
    submitted = len(attempts)
    avg = round(sum(a["percentage"] for a in attempts) / submitted) if submitted else 0
    pending = max(0, total_students - submitted)

    return render_template("admin_dashboard.html",
                           attempts=attempts,
                           registrations=registrations,
                           total_students=total_students,
                           submitted=submitted,
                           pending=pending,
                           avg_score=avg,
                           ROLES=ROLES)


@app.route("/admin/attempt/<int:attempt_id>")
@admin_required
def admin_attempt(attempt_id):
    attempt = db.query_one("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
    if not attempt:
        return redirect(url_for("admin_dashboard"))
    breakdown = json.loads(attempt["breakdown"])
    return render_template("admin_attempt.html", attempt=attempt,
                           breakdown=breakdown, ROLES=ROLES)


@app.route("/admin/reset", methods=["POST"])
@admin_required
def admin_reset():
    db.execute("DELETE FROM attempts")
    db.execute("DELETE FROM registrations")
    db.execute("DELETE FROM exam_sessions")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
