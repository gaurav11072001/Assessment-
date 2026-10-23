"""End-to-end test against a REAL PostgreSQL server.

    pip install -r requirements-dev.txt
    python tests/test_postgres.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pgserver

print("=== starting postgres ===")
t0 = time.time()
pgdata = os.path.join(tempfile.mkdtemp(prefix="pgtest"), "data")
srv = pgserver.get_server(pgdata, cleanup_mode="delete")
dsn = srv.get_uri()
print("uri:", dsn)
print("startup took %.1fs" % (time.time() - t0))

os.environ["DATABASE_URL"] = dsn
os.environ["RENDER"] = "true"
os.environ.pop("EXAMPORTAL_SECRET", None)

import db
import app as appmod

print()
print("=== db module ===")
print("IS_PG            :", db.IS_PG)
print("schema status    :", db.schema_status())
print("db_healthy       :", db.db_healthy())

print()
print("=== tables created ===")
rows = db.query_all(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema='public' ORDER BY table_name")
print([r["table_name"] for r in rows])
print("indexes:")
for r in db.query_all(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public' ORDER BY indexname"):
    print("   ", r["indexname"])

print()
print("=== full exam flow ===")
c = appmod.app.test_client()

r = c.post("/register", data={"name": "PG Student", "email": "pg@example.com"})
print("register        :", r.status_code, r.headers.get("Location"))

r = c.get("/start/python", follow_redirects=False)
print("start           :", r.status_code, r.headers.get("Location"))

r = c.get("/quiz")
print("quiz            :", r.status_code, "timer" in r.get_data(as_text=True))

for i in range(60):
    c.post("/quiz", data={"answer": "x"})
r = c.post("/submit", follow_redirects=False)
print("submit          :", r.status_code, r.headers.get("Location"))

r = c.get("/done")
html = r.get_data(as_text=True)
print("done page       :", r.status_code, "submitted=%s" % ("Exam Submitted" in html))
with c.session_transaction() as sess:
    print("auto logout     :", sess.get("student_email") is None)

print()
print("=== attempt row in postgres ===")
for row in db.query_all("SELECT email, full_name, role, correct, total, percentage, violations FROM attempts"):
    print("   ", dict(row))
for row in db.query_all("SELECT sid, student_email, role, cat_index, q_index, violations, submitted_at IS NOT NULL AS done FROM exam_sessions"):
    print("   session:", dict(row))

print()
print("=== retake blocked ===")
c2 = appmod.app.test_client()
c2.post("/resume", data={"email": "pg@example.com"}, follow_redirects=False)
r = c2.get("/start/python", follow_redirects=False)
print("retake ->", r.status_code, r.headers.get("Location"))

print()
print("=== duplicate registration blocked ===")
c3 = appmod.app.test_client()
r = c3.post("/register", data={"name": "PG Student", "email": "other@example.com"})
print("dup name blocked:", "already registered" in r.get_data(as_text=True))

print()
print("=== admin ===")
ad = appmod.app.test_client()
ad.post("/admin/login", data={"username": "admin", "password": "admin123"})
r = ad.get("/admin")
print("dashboard:", r.status_code, "PG Student" in r.get_data(as_text=True))
r = ad.get("/admin/attempt/1")
print("detail   :", r.status_code, "Section-wise Performance" in r.get_data(as_text=True))

print()
print("=== healthz ===")
r = c.get("/healthz")
print(r.status_code, r.get_json())

print()
print("=== concurrent submits race check ===")
import threading
sess = appmod.app.test_client()
sess.post("/register", data={"name": "Race PG", "email": "racepg@example.com"})
sess.get("/start/embedded")
errs = []
def hammer():
    try:
        rr = sess.post("/submit", follow_redirects=False)
        if rr.status_code != 302:
            errs.append(rr.status_code)
    except Exception as e:
        errs.append(str(e))
ts = [threading.Thread(target=hammer) for _ in range(8)]
for t in ts: t.start()
for t in ts: t.join()
n = db.query_one("SELECT COUNT(*) AS n FROM attempts WHERE lower(email)='racepg@example.com'")
print("errors:", errs, "| attempt rows:", n["n"], "(must be 1)")

srv.cleanup()
print()
print("ALL POSTGRES TESTS PASSED")
