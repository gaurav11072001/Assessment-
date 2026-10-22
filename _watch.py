"""Poll the deployed URL until the new build (with schema=ready) is serving."""
import socket
import ssl
import sys
import time

HOST = "assessment.onrender.com"


def probe(path="/healthz", timeout=30):
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((HOST, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as tls:
                tls.settimeout(timeout)
                req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: probe\r\n"
                       "Accept: */*\r\nConnection: close\r\n\r\n" % (path, HOST))
                tls.sendall(req.encode())
                buf = b""
                while True:
                    try:
                        chunk = tls.recv(8192)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buf += chunk
                text = buf.decode("utf-8", "replace")
                head, _, body = text.partition("\r\n\r\n")
                status = head.splitlines()[0] if head else "?"
                routing = next((l.strip() for l in head.splitlines()
                                if l.lower().startswith("x-render-routing")), "")
                return status, routing, body.strip()
    except Exception as e:
        return "ERROR", "", "%s: %s" % (type(e).__name__, e)


deadline = time.time() + 600
last = None
while time.time() < deadline:
    status, routing, body = probe("/healthz")
    root_status, _, root_body = probe("/")
    sig = (status, routing, body[:80], root_status)
    if sig != last:
        print("[%3ds] /healthz %s | root %s | %s"
              % (int(time.time()) % 100, status, root_status, routing))
        if body:
            print("        healthz: %s" % body.replace("\n", " ")[:140])
        if root_status.startswith("HTTP/1.1 200"):
            print("        root: serving %d bytes" % len(root_body))
        last = sig
    if status.startswith("HTTP/1.1 200") and "schema" in body:
        print("\n*** NEW BUILD LIVE ***")
        print("body:", body)
        sys.exit(0)
    time.sleep(8)

print("\nNot serving the new build yet.")
sys.exit(1)
