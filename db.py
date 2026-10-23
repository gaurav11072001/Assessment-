"""Database layer for ExamPortal.

Works with PostgreSQL (Render production) and SQLite (local development).
All SQL is written once using `?` placeholders and translated per driver.

Connection strategy:
  - PostgreSQL: a ThreadedConnectionPool shared across the process so we never
    exceed the connection limit of the Render free tier (5).
  - SQLite: one thread-local connection with WAL enabled for concurrent reads.
"""

import logging
import os
import sqlite3
import threading
import time
import uuid

# psycopg emits an INFO line on every connection reset ("rolling back
# returned connection"). At exam scale that is thousands of log lines, so
# quiet it down and keep the Render logs readable.
logging.getLogger("psycopg").setLevel(logging.WARNING)
logging.getLogger("psycopg.pool").setLevel(logging.WARNING)

logger = logging.getLogger("examportal.db")
logger.setLevel(logging.INFO)

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
PG_CONNECT_TIMEOUT = int(os.environ.get("PG_CONNECT_TIMEOUT", "5"))
PG_POOL_WAIT = float(os.environ.get("PG_POOL_WAIT", "5"))
# While the database is down, fail fast instead of paying the connect
# timeout on every single query.
CONNECT_RETRY_DELAY = int(os.environ.get("PG_CONNECT_RETRY_DELAY", "10"))

_local = threading.local()
_pool = None
_pool_error_at = 0.0
_pool_lock = threading.Lock()


# --------------------------------------------------------------------------
# connections
# --------------------------------------------------------------------------

def _pg_dsn():
    """Return the connection string.

    Do not force an sslmode here. The driver default (prefer) negotiates SSL
    when the server supports it and falls back cleanly when it does not.
    Forcing sslmode=require breaks against servers that do not advertise
    SSL support at all.
    """
    return DATABASE_URL


def _create_pool():
    """Build a connection pool for whichever driver is installed.

    psycopg 3 (psycopg_pool.ConnectionPool) is preferred because it ships
    binary wheels for every current Python release. psycopg2's
    ThreadedConnectionPool is kept as a fallback.

    NOTE: psycopg_pool 3.x renamed ThreadedConnectionPool to ConnectionPool
    and changed minconn/maxconn to min_size/max_size.
    """
    try:
        import psycopg_pool
        pool_cls = getattr(psycopg_pool, "ConnectionPool", None)
        if pool_cls is not None:
            return pool_cls(
                _pg_dsn(),
                min_size=PG_POOL_MIN,
                max_size=PG_POOL_SIZE,
                kwargs={"connect_timeout": PG_CONNECT_TIMEOUT},
                timeout=PG_POOL_WAIT,
            )
    except Exception:
        pass

    import psycopg2.pool
    return psycopg2.pool.ThreadedConnectionPool(
        PG_POOL_MIN, PG_POOL_SIZE, _pg_dsn(),
        connect_timeout=PG_CONNECT_TIMEOUT,
    )


def _verify_pool(pool):
    """Prove the pool can actually reach the database.

    psycopg_pool opens connections in a background task, so constructing the
    pool succeeds even when the database is unreachable. Without this check
    every query would block until the pool timeout instead of failing fast.
    """
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
    finally:
        pool.putconn(conn)


def _close_pool(pool):
    for method in ("closeall", "close"):
        fn = getattr(pool, method, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            return


def _get_pool():
    global _pool, _pool_error_at
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        # The database is down or still provisioning - do not pay the
        # connect timeout again for every query.
        if time.time() - _pool_error_at < CONNECT_RETRY_DELAY:
            raise RuntimeError("database temporarily unreachable")
        try:
            pool = _create_pool()
            _verify_pool(pool)
            _pool = pool
            _pool_error_at = 0.0
            return _pool
        except Exception:
            try:
                _close_pool(locals().get("pool"))
            except Exception:
                pass
            _pool_error_at = time.time()
            raise


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


def _is_connection_error(exc):
    """True when the failure was the connection, not the query.

    A dropped connection (DB restart, idle timeout) is recoverable: drop the
    pool, rebuild it and retry. A bad query is not.
    """
    name = type(exc).__name__
    if name in ("OperationalError", "InterfaceError", "PoolTimeout",
                "PoolClosed", "ConnectionDoesNotExist"):
        return True
    return "connection" in str(exc).lower() and "server closed" in str(exc).lower()


def execute(sql, params=()):
    """Run a statement and commit."""
    for attempt in range(2):
        try:
            return _execute_once(sql, params)
        except Exception as e:
            if attempt == 0 and _is_connection_error(e):
                logger.info("connection error, rebuilding pool and retrying")
                _invalidate_pool()
                time.sleep(0.3)
                continue
            raise


def _execute_once(sql, params=()):
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
    for attempt in range(2):
        try:
            return _query_all_once(sql, params)
        except Exception as e:
            if attempt == 0 and _is_connection_error(e):
                logger.info("connection error, rebuilding pool and retrying")
                _invalidate_pool()
                time.sleep(0.3)
                continue
            raise


def _query_all_once(sql, params=()):
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
            q_order TEXT NOT NULL DEFAULT '{{}}',
            seed TEXT NOT NULL DEFAULT '',
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

        # Migrations for databases created before per-student shuffling.
        "ALTER TABLE exam_sessions ADD COLUMN q_order TEXT NOT NULL DEFAULT '{{}}'",
        "ALTER TABLE exam_sessions ADD COLUMN seed TEXT NOT NULL DEFAULT ''",
    ]

    for stmt in statements:
        sql = stmt.format(ID_PK=id_pk)
        try:
            execute(sql)
        except Exception:
            # Concurrent CREATE ... IF NOT EXISTS can race across workers.
            pass


def _schema_ready():
    """True when the tables we need actually exist."""
    try:
        if IS_PG:
            row = query_one(
                "SELECT count(*) AS n FROM information_schema.tables "
                "WHERE table_name IN ('registrations', 'attempts', 'exam_sessions')"
            )
            return row and row["n"] == 3
        row = query_one(
            "SELECT count(*) AS n FROM sqlite_master "
            "WHERE type='table' AND name IN ('registrations', 'attempts', 'exam_sessions')"
        )
        return row and row["n"] == 3
    except Exception:
        return False


def init_schema_robustly(sync_attempts=6, sync_delay=5, bg_attempts=60, bg_delay=5):
    """Create the schema, tolerating a database that is still provisioning.

    On Render the web service and its Postgres instance are created at the
    same time, so the database is often not reachable for the first few
    seconds. Failing the boot at that point would leave the service with no
    server at all, so we retry briefly in the foreground and then keep
    retrying in the background.
    """
    for attempt in range(sync_attempts):
        try:
            init_schema()
            if _schema_ready():
                SCHEMA_STATE["ready"] = True
                return True
        except Exception:
            pass
        if attempt < sync_attempts - 1:
            time.sleep(sync_delay)

    def _bg():
        for _ in range(bg_attempts):
            try:
                init_schema()
                if _schema_ready():
                    SCHEMA_STATE["ready"] = True
                    return
            except Exception:
                pass
            time.sleep(bg_delay)

    threading.Thread(target=_bg, daemon=True).start()
    return False


def new_sid():
    return uuid.uuid4().hex


def db_healthy():
    """True when a trivial query succeeds.

    Retried because a single dropped connection (idle timeout, DB restart)
    is transient. A failed attempt invalidates the pool so the next call
    rebuilds it instead of being stuck on dead connections.
    """
    for attempt in range(2):
        try:
            query_one("SELECT 1 AS ok")
            if LAST_DB_ERROR["error"] is not None:
                logger.info("database connection recovered")
            LAST_DB_ERROR["error"] = None
            LAST_DB_ERROR["since"] = None
            return True
        except Exception as e:
            message = "%s: %s" % (type(e).__name__, e)
            if LAST_DB_ERROR["error"] != message:
                logger.warning("database unreachable: %s", message)
            LAST_DB_ERROR["error"] = message
            if LAST_DB_ERROR["since"] is None:
                LAST_DB_ERROR["since"] = time.time()
            _invalidate_pool()
            if attempt == 0:
                time.sleep(0.5)
    return False


LAST_DB_ERROR = {"error": None, "since": None}


def last_db_error():
    return LAST_DB_ERROR["error"]


def db_outage_seconds():
    """How long the database has been continuously unreachable (0 = healthy)."""
    since = LAST_DB_ERROR.get("since")
    if not since or LAST_DB_ERROR.get("error") is None:
        return 0
    return time.time() - since


def _invalidate_pool():
    """Discard the cached pool so it is rebuilt on the next query."""
    global _pool, _pool_error_at
    with _pool_lock:
        if _pool is not None:
            _close_pool(_pool)
        _pool = None
        _pool_error_at = 0.0


SCHEMA_STATE = {"ready": False}


def schema_status():
    """'ready' once the tables exist, otherwise 'pending'."""
    return "ready" if SCHEMA_STATE["ready"] else "pending"


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


if IS_PG:
    logger.info("database: postgresql (pool min=%s max=%s workers=%s)",
                PG_POOL_MIN, PG_POOL_SIZE, os.environ.get("WEB_CONCURRENCY", "?"))
    if init_schema_robustly():
        logger.info("schema ready")
    else:
        logger.warning("schema not ready yet; retrying in the background")
else:
    init_schema()
    SCHEMA_STATE["ready"] = True
    logger.info("database: sqlite (local development)")
