"""Database layer for ExamPortal.

Works with PostgreSQL (Render production) and SQLite (local development).
All SQL is written once using `?` placeholders and translated per driver.

Connection strategy:
  - PostgreSQL: a ThreadedConnectionPool shared across the process so we never
    exceed the connection limit of the Render free tier (5).
  - SQLite: one thread-local connection with WAL enabled for concurrent reads.
"""

import os
import sqlite3
import threading
import uuid

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith("postgres")

# Render wipes the local filesystem whenever a free instance spins down or
# redeploys. Falling back to SQLite there would silently destroy every exam
# result, so refuse to boot instead.
ON_RENDER = os.environ.get("RENDER", "").lower() in ("1", "true", "yes")
if ON_RENDER and not IS_PG:
    raise RuntimeError(
        "DATABASE_URL is not set on Render. The local filesystem is wiped on "
        "every spin-down/redeploy, so the SQLite fallback would lose all exam "
        "results. Attach a Postgres database (or set DATABASE_URL) and redeploy."
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "examportal.db")

PG_POOL_SIZE = int(os.environ.get("PG_POOL_SIZE", "4"))
PG_POOL_MIN = int(os.environ.get("PG_POOL_MIN", "1"))

_local = threading.local()
_pool = None
_pool_lock = threading.Lock()


# --------------------------------------------------------------------------
# connections
# --------------------------------------------------------------------------

def _pg_dsn():
    dsn = DATABASE_URL
    if "sslmode" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return dsn


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                import psycopg2
                import psycopg2.pool
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    PG_POOL_MIN, PG_POOL_SIZE, _pg_dsn(), connect_timeout=10
                )
    return _pool


def _sqlite_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _thread_conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _local.conn = _sqlite_conn()
    return conn


def close_thread_conn():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


# --------------------------------------------------------------------------
# query helpers
# --------------------------------------------------------------------------

def _translate(sql):
    return sql.replace("?", "%s") if IS_PG else sql


def execute(sql, params=()):
    """Run a statement and commit."""
    if IS_PG:
        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(_translate(sql), params)
            conn.commit()
            cur.close()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            pool.putconn(conn)
    else:
        conn = _thread_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()


def query_all(sql, params=()):
    """Return a list of dict rows."""
    if IS_PG:
        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(_translate(sql), params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close()
            conn.rollback()
            return rows
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            pool.putconn(conn)
    conn = _thread_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def query_one(sql, params=()):
    rows = query_all(sql, params)
    return rows[0] if rows else None


def insert_ignore(table, columns, values):
    """Insert a row, silently skipping it if a unique constraint conflicts."""
    cols = ", ".join(columns)
    marks = ", ".join(["?"] * len(columns))
    if IS_PG:
        sql = "INSERT INTO %s (%s) VALUES (%s) ON CONFLICT DO NOTHING" % (table, cols, marks)
    else:
        sql = "INSERT OR IGNORE INTO %s (%s) VALUES (%s)" % (table, cols, marks)
    execute(sql, values)


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------

def init_schema():
    id_pk = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"

    statements = [
        """
        CREATE TABLE IF NOT EXISTS registrations (
            id {ID_PK},
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_reg_email ON registrations (lower(email))",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_reg_name ON registrations (lower(full_name))",

        """
        CREATE TABLE IF NOT EXISTS attempts (
            id {ID_PK},
            email TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            correct INTEGER NOT NULL,
            total INTEGER NOT NULL,
            percentage INTEGER NOT NULL,
            breakdown TEXT NOT NULL,
            violations INTEGER NOT NULL DEFAULT 0,
            time_taken INTEGER NOT NULL DEFAULT 0,
            submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_attempt_email_role ON attempts (lower(email), role)",

        """
        CREATE TABLE IF NOT EXISTS exam_sessions (
            sid TEXT PRIMARY KEY,
            student_email TEXT NOT NULL,
            student_name TEXT NOT NULL,
            role TEXT NOT NULL,
            category_order TEXT NOT NULL,
            answers TEXT NOT NULL,
            cat_index INTEGER NOT NULL DEFAULT 0,
            q_index INTEGER NOT NULL DEFAULT 0,
            violations INTEGER NOT NULL DEFAULT 0,
            started_at DOUBLE PRECISION,
            deadline DOUBLE PRECISION,
            submitted_at DOUBLE PRECISION,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sessions_created ON exam_sessions (created_at)",
    ]

    for stmt in statements:
        sql = stmt.format(ID_PK=id_pk)
        try:
            execute(sql)
        except Exception:
            # Concurrent CREATE ... IF NOT EXISTS can race across workers.
            pass


def new_sid():
    return uuid.uuid4().hex


def db_healthy():
    try:
        query_one("SELECT 1 AS ok")
        return True
    except Exception:
        return False


def cleanup_expired_sessions(max_age_hours=24):
    """Delete exam session rows older than max_age_hours."""
    try:
        if IS_PG:
            execute("DELETE FROM exam_sessions WHERE created_at < CURRENT_TIMESTAMP - (? * INTERVAL '1 hour')",
                    (max_age_hours,))
        else:
            execute("DELETE FROM exam_sessions WHERE created_at < datetime('now', ?)",
                    ("-%d hours" % max_age_hours,))
    except Exception:
        pass


init_schema()
