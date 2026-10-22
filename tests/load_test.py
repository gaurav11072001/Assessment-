"""80-student concurrent load test against a REAL PostgreSQL.

    pip install -r requirements-dev.txt
    python tests/load_test.py
"""

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pgserver
import requests
from waitress import serve

pgdata = os.path.join(tempfile.mkdtemp(prefix="pgload"), "data")
srv = pgserver.get_server(pgdata, cleanup_mode="delete")
os.environ["DATABASE_URL"] = srv.get_uri()
os.environ["RENDER"] = "true"

from app import app
import db

PORT = 8020
BASE = "http://127.0.0.1:%d" % PORT
N = 80
RUN = str(int(time.time()))

print("postgres uri:", srv.get_uri())


def run_server():
    serve(app, host="127.0.0.1", port=PORT, threads=16,
          connection_limit=1000, channel_timeout=120)


threading.Thread(target=run_server, daemon=True).start()
time.sleep(4)

for _ in range(20):
    try:
        if requests.get(BASE + "/healthz", timeout=5).status_code == 200:
            break
    except Exception:
        time.sleep(1)

results = []
lock = threading.Lock()
barrier = threading.Barrier(N)


def student(i):
    s = requests.Session()
    loc = {"reqs": 0, "errors": []}
    try:
        barrier.wait()
        r = s.post(BASE + "/register",
                   data={"name": "PG Load %s %d" % (RUN, i),
                         "email": "pgload%s%d@example.com" % (RUN, i),
                         "next": "python"}, timeout=90)
        loc["reqs"] += 1
        if r.status_code not in (200, 302):
            loc["errors"].append("register %s" % r.status_code)
        db.execute("UPDATE registrations SET status = 'approved' "
                   "WHERE lower(email) = lower(?)", ("pgload%s%d@example.com" % (RUN, i),))
        s.get(BASE + "/start/python", timeout=90)
        loc["reqs"] += 1
        for _ in range(60):
            r = s.get(BASE + "/quiz", timeout=90, allow_redirects=False)
            loc["reqs"] += 1
            if r.status_code not in (200, 302):
                loc["errors"].append("quiz %s" % r.status_code)
                break
            r = s.post(BASE + "/quiz", data={"answer": "x"}, timeout=90,
                       allow_redirects=False)
            loc["reqs"] += 1
            if r.status_code not in (200, 302):
                loc["errors"].append("answer %s" % r.status_code)
                break
        r = s.post(BASE + "/submit", timeout=90, allow_redirects=False)
        loc["reqs"] += 1
        r = s.get(BASE + "/result", timeout=90)
        loc["reqs"] += 1
        if r.status_code != 200 or "Assessment Complete" not in r.text:
            loc["errors"].append("result %s" % r.status_code)
    except Exception as e:
        loc["errors"].append("EXC %s: %s" % (type(e).__name__, e))
    with lock:
        results.append(loc)


start = time.time()
ts = [threading.Thread(target=student, args=(i,)) for i in range(N)]
for t in ts:
    t.start()
for t in ts:
    t.join()
elapsed = time.time() - start

total = sum(r["reqs"] for r in results)
errs = [e for r in results for e in r["errors"]]
print()
print("=" * 60)
print("POSTGRES LOAD TEST: %d concurrent students" % N)
print("=" * 60)
print("total requests : %d" % total)
print("wall time      : %.1fs" % elapsed)
print("throughput     : %.0f req/s" % (total / elapsed))
print("errors         : %d" % len(errs))
if errs:
    print("  sample:", errs[:8])

print()
print("--- database integrity ---")
rows = db.query_all("SELECT COUNT(*) AS n FROM attempts")
print("attempts          :", rows[0]["n"])
rows = db.query_all("SELECT COUNT(*) AS n FROM attempts WHERE total = 60")
print("attempts total=60 :", rows[0]["n"])
rows = db.query_all("SELECT COUNT(*) AS n FROM registrations")
print("registrations     :", rows[0]["n"])
rows = db.query_all(
    "SELECT lower(email) AS e, role, COUNT(*) AS c FROM attempts "
    "GROUP BY lower(email), role HAVING COUNT(*) > 1")
print("duplicate attempts:", len(rows), "(must be 0)")

srv.cleanup()
