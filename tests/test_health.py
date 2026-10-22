"""Reproduce the 'schema ready but status degraded' condition.

Simulates the deployed setup: multiple worker processes, each with its own
pool, hitting a real Postgres. Also simulates the DB becoming unreachable
mid-flight to prove the pool self-heals.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pgserver

pgdata = os.path.join(tempfile.mkdtemp(prefix="pgdiag"), "data")
srv = pgserver.get_server(pgdata, cleanup_mode="delete")
os.environ["DATABASE_URL"] = srv.get_uri()
os.environ["RENDER"] = "true"

import db
import app as appmod

c = appmod.app.test_client()

print("=== 1. healthz right after boot ===")
r = c.get("/healthz")
print(r.status_code, r.get_json())

print()
print("=== 2. after a burst of traffic ===")
for i in range(200):
    c.get("/")
    c.get("/role-select")
r = c.get("/healthz")
print(r.status_code, r.get_json())

print()
print("=== 3. after a full exam ===")
s = appmod.app.test_client()
s.post("/register", data={"name": "Diag", "email": "diag@example.com"})
db.execute("UPDATE registrations SET status = 'approved' "
           "WHERE lower(email) = lower(?)", ("diag@example.com",))
s.get("/start/python")
for _ in range(60):
    s.post("/quiz", data={"answer": "x"})
s.post("/submit")
r = c.get("/healthz")
print(r.status_code, r.get_json())

print()
print("=== 4. pool stats ===")
p = db._pool
print("pool class :", type(p).__name__)
print("min/max    :", getattr(p, "_minsize", "?"), "/", getattr(p, "_maxsize", "?"))
print("closed     :", getattr(p, "_closed", "?"))
print("pool size  :", len(getattr(p, "_pool", []) or []))

print()
print("=== 5. DB goes away -> healthz must report the real error ===")
srv.cleanup()
time.sleep(1.5)
r = c.get("/healthz")
print(r.status_code, r.get_json())

print()
print("=== 6. DB comes back -> pool must self-heal ===")
srv2 = pgserver.get_server(pgdata, cleanup_mode="delete")
os.environ["DATABASE_URL"] = srv2.get_uri()
db.DATABASE_URL = srv2.get_uri()
db._invalidate_pool()
time.sleep(0.5)
r = c.get("/healthz")
print(r.status_code, r.get_json())

srv2.cleanup()
