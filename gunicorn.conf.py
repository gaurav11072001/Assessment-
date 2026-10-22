"""Gunicorn configuration tuned for Render.

Concurrency model: worker processes x threads = concurrent request handlers.
Every request here is a small HTML render or one indexed DB query
(sub-millisecond), so 70 candidates refreshing a question page every ~30
seconds (~3 req/s) is comfortably within capacity.

Sizing (measured: ~59 MB RSS per worker under 80 concurrent students):
  Render free  (512 MB)  -> 2 workers x 8 threads = 16 handlers   (~120 MB)
  Render starter (512 MB)-> 2 workers x 8 threads = 16 handlers   (~120 MB)
  Render standard(2 GB)  -> 4 workers x 8 threads = 32 handlers   (~240 MB)

Override with WEB_CONCURRENCY / WEB_THREADS.
"""

import multiprocessing
import os


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


bind = "0.0.0.0:%s" % os.environ.get("PORT", "8000")

_cpu = multiprocessing.cpu_count()
workers = _int_env("WEB_CONCURRENCY", max(2, min(4, _cpu * 2)))
threads = _int_env("WEB_THREADS", 8)
worker_class = "gthread"

# Keep the process responsive during a burst of simultaneous submissions.
timeout = 120
graceful_timeout = 30
keepalive = 5

# Worker recycling is disabled by default. During a 1-hour exam a worker
# restart would drop keep-alive connections, and a browser does NOT retry a
# POST -- that would cost a student an answer. Set MAX_REQUESTS>0 outside
# exam hours if you need leak protection.
max_requests = _int_env("MAX_REQUESTS", 0)
max_requests_jitter = _int_env("MAX_REQUESTS_JITTER", 0)

# Do not preload: each worker needs its own DB pool after fork.
preload_app = False

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'

# Trust Render's proxy for correct scheme/host handling.
forwarded_allow_ips = "*"
