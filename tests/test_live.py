"""Live end-to-end smoke test against the deployed Render service.

Handles the free-tier cold start: retries until the instance answers.
Set ADMIN_USER / ADMIN_PASSWORD to verify the smoke-test registration.
"""
import os
import re
import sys
import time

import requests

HOSTS = ["https://assessment-61j8.onrender.com"]

BASE = None
for h in HOSTS:
    for attempt in range(10):
        try:
            r = requests.get(h + "/healthz", timeout=90)
            if r.status_code == 200 and "postgresql" in r.text:
                BASE = h
                break
        except Exception:
            pass
        print("   %s attempt %d: not ready" % (h, attempt + 1))
        time.sleep(8)
    if BASE:
        break

if not BASE:
    print("Could not reach the service.")
    sys.exit(1)

print("BASE:", BASE)
print()
print("healthz  :", requests.get(BASE + "/healthz", timeout=60).text)

s = requests.Session()
r = s.get(BASE + "/", timeout=60)
print("landing  :", r.status_code, len(r.text), "bytes")
for label, needle in [("DoxPro logo", "logo.png"),
                       ("EXAMPORTAL nav", "examportal-logo.svg"),
                       ("Start CTA", "Start Assessment"),
                       ("stats 2102+", "2102+")]:
    print("   %-16s %s" % (label, needle in r.text))

print()
print("--- registration ---")
r = s.post(BASE + "/register", data={"name": "Live Smoke Test",
                                     "email": "smoke.live@example.com",
                                     "next": "python"}, timeout=60)
print("register :", r.status_code, r.headers.get("Location"))

print()
print("--- exam ---")
r = s.get(BASE + "/start/python", timeout=60, allow_redirects=False)
print("start    :", r.status_code, r.headers.get("Location"))
r = s.get(BASE + "/quiz", timeout=60)
m = re.search(r'data-remaining="(\d+)"', r.text)
print("quiz     :", r.status_code, "timer_seconds=%s" % (m.group(1) if m else "?"))
print("   timer   :", "Time Remaining" in r.text)
print("   monitor :", "violationBanner" in r.text)
print("   locked  :", "user-select: none" in r.text)

for i in range(60):
    s.post(BASE + "/quiz", data={"answer": "x"}, timeout=60, allow_redirects=False)
r = s.post(BASE + "/submit", timeout=60, allow_redirects=False)
print("submit   :", r.status_code, r.headers.get("Location"))
r = s.get(BASE + "/done", timeout=60)
print("done     :", r.status_code, "submitted=%s" % ("Exam Submitted" in r.text))
r = s.get(BASE + "/quiz", timeout=60, allow_redirects=False)
print("logged out:", r.status_code, r.headers.get("Location"))

print()
print("--- retake blocked ---")
s2 = requests.Session()
s2.post(BASE + "/resume", data={"email": "smoke.live@example.com"}, timeout=60)
r = s2.get(BASE + "/start/python", timeout=60, allow_redirects=False)
print("retake   :", r.status_code, r.headers.get("Location"))

print()
print("--- admin ---")
a = requests.Session()
a.post(BASE + "/admin/login", data={"username": "admin", "password": "admin123"}, timeout=60)
r = a.get(BASE + "/admin", timeout=60)
print("dashboard:", r.status_code, "student listed:", "Live Smoke Test" in r.text)
r = a.get(BASE + "/admin/attempt/1", timeout=60)
print("detail   :", r.status_code)
r = requests.get(BASE + "/admin", timeout=60, allow_redirects=False)
print("no-auth  :", r.status_code, r.headers.get("Location"))
