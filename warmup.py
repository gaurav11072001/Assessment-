"""Warm up a sleeping Render free instance before an exam.

A free web service spins down after 15 minutes without traffic and takes
about a minute to start again. Run this a few minutes before candidates are
due so the first student does not sit through a cold start.

Usage:
    python warmup.py https://your-app.onrender.com
    python warmup.py https://your-app.onrender.com --keep-alive 60

--keep-alive <seconds> pings every N seconds until interrupted (useful if
the exam window is long and there may be quiet stretches).
"""

import argparse
import sys
import time

import urllib.error
import urllib.request


def ping(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "warmup/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except Exception as e:
        return None, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url", help="e.g. https://assessment-xyz.onrender.com")
    ap.add_argument("--keep-alive", type=int, default=0,
                    help="ping every N seconds until Ctrl+C")
    ap.add_argument("--attempts", type=int, default=6,
                    help="how many times to retry while waking up")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    health = base + "/healthz"

    print("Waking up %s ..." % base)
    for i in range(1, args.attempts + 1):
        t0 = time.time()
        status, body = ping(health)
        took = time.time() - t0
        if status == 200:
            print("  attempt %d: %s in %.1fs -> %s" % (i, status, took, body.strip()))
            if args.keep_alive:
                break
            print("\nInstance is awake and warm.")
            return 0
        print("  attempt %d: %s in %.1fs (%s)" % (i, status, took, body))
        time.sleep(10)

    print("\nStill not awake after %d attempts." % args.attempts)
    return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main())
