"""Gunicorn configuration tuned for Render.

Concurrency model: 2 worker processes x 8 threads = 16 concurrent request
handlers. Each request in this app is a small HTML render or a single indexed
DB query (sub-millisecond), so 80 candidates refreshing a question page every
~30 seconds (~3 req/s steady state) is comfortably within capacity.

Set WEB_CONCURRENCY in the environment to scale workers with the plan:
  starter  (0.5 CPU, 512 MB) -> 2
  standard (1 CPU,   2 GB)  -> 4
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
workers = _int_env("WEB_CONCURRENCY", max(2, _cpu * 2))
threads = _int_env("WEB_THREADS", 8)
worker_class = "gthread"

# Keep the process responsive during a burst of simultaneous submissions.
timeout = 120
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically to avoid memory creep on long-lived instances.
max_requests = 2000
max_requests_jitter = 200

# Do not preload: each worker needs its own DB pool after fork.
preload_app = False

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'

# Trust Render's proxy for correct scheme/host handling.
forwarded_allow_ips = "*"
