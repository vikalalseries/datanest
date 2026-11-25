"""Post-deploy smoke test for a running DataNest API. Uses only the standard library; makes no AI calls.

    python scripts/smoke_test.py https://datanest-api.onrender.com --origin https://your-app.vercel.app
    python scripts/smoke_test.py http://localhost:8000 --dev --origin http://localhost:5173

Checks: the service is up, login is required, the API docs are hidden (production), security headers are present,
CORS allows your frontend and nobody else, and HTTPS/HSTS is on (production).
Exit code 0 = all checks passed.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--origin", required=True, help="the frontend URL that should be allowed by CORS")
    ap.add_argument("--dev", action="store_true", help="local/dev server: skip production-only checks (docs hidden, HSTS)")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    results: list[tuple[bool, str]] = []

    def check(ok: bool, label: str, detail: str = ""):
        results.append((ok, label))
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))

    print(f"Smoke testing {base}\n")
    st, h, body = fetch(f"{base}/health")
    check(st == 200 and json.loads(body or b"{}").get("status") == "ok", "health endpoint is up", f"status {st}")
    st, h, body = fetch(f"{base}/api/auth/me")
    check(st == 401, "login is required (no token -> 401)", f"status {st}")
    try:
        err = json.loads(body)["error"]
        check(err.get("code") == "unauthorized" and "Traceback" not in body.decode() and "request_id" in err, "errors are clean JSON with a request id and no stack trace")
    except Exception:
        check(False, "errors are clean JSON with a request id and no stack trace")
    st, h, _ = fetch(f"{base}/api/sheets")
    check(st == 401, "data endpoints also require login", f"status {st}")
    st, h, _ = fetch(f"{base}/health")
    check(h.get("x-content-type-options") == "nosniff" and h.get("x-frame-options") == "DENY" and "referrer-policy" in h, "security headers present")
    st, h, _ = fetch(f"{base}/api/auth/me")
    check(h.get("cache-control") == "no-store", "API responses are not cacheable")
    pre = {"Origin": a.origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    st, h, _ = fetch(f"{base}/api/auth/me", "OPTIONS", pre)
    check(h.get("access-control-allow-origin") == a.origin, f"CORS allows {a.origin}", f"got {h.get('access-control-allow-origin')}")
    st, h, _ = fetch(f"{base}/api/auth/me", "OPTIONS", {**pre, "Origin": "https://evil.example"})
    check("access-control-allow-origin" not in h, "CORS refuses other websites", f"got {h.get('access-control-allow-origin')}")
    if not a.dev:
        check(base.startswith("https://"), "served over HTTPS")
        st, _, _ = fetch(f"{base}/docs")
        check(st == 404, "interactive API docs are hidden", f"status {st}")
        st, _, _ = fetch(f"{base}/openapi.json")
        check(st == 404, "API schema is hidden", f"status {st}")
        st, h, _ = fetch(f"{base}/health")
        check("max-age" in h.get("strict-transport-security", ""), "HSTS is enabled")
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
