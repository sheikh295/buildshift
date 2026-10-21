#!/usr/bin/env python3
"""Local GitHub fetch proxy for worker sandboxes.

Holds the PAT in-process only. Agents call buildshift-fetch / this HTTP API;
they never receive the token. Only URLs under the allowlisted owner/repo
(and raw.githubusercontent.com for that repo) are permitted.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _allowed_repo() -> tuple[str, str]:
    raw = (os.environ.get("ALLOWED_GITHUB_REPO") or "").strip().strip("/")
    if "/" not in raw:
        raise SystemExit("ALLOWED_GITHUB_REPO must be owner/name")
    owner, name = raw.split("/", 1)
    owner, name = owner.strip(), name.strip()
    if not owner or not name or "/" in name:
        raise SystemExit(f"invalid ALLOWED_GITHUB_REPO={raw!r}")
    return owner.lower(), name.lower()


OWNER, REPO = _allowed_repo()
TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
PORT = int(os.environ.get("GITHUB_PROXY_PORT") or "18741")


def _url_allowed(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("https", "http"):
        return False
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    path_l = path.lower()

    if host in {"github.com", "www.github.com", "api.github.com"}:
        # /owner/repo(/...) or /repos/owner/repo(/...)
        if path_l.startswith(f"/{OWNER}/{REPO}") or path_l.startswith(
            f"/{OWNER}/{REPO}/"
        ):
            return True
        if path_l.startswith(f"/repos/{OWNER}/{REPO}") or path_l.startswith(
            f"/repos/{OWNER}/{REPO}/"
        ):
            return True
        return False

    if host == "raw.githubusercontent.com":
        return path_l.startswith(f"/{OWNER}/{REPO}/") or path_l == f"/{OWNER}/{REPO}"

    return False


def _fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    if not _url_allowed(url):
        body = json.dumps(
            {
                "error": "url_not_allowed",
                "allowed_repo": f"{OWNER}/{REPO}",
                "url": url,
            }
        ).encode()
        return 403, {"content-type": "application/json"}, body

    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "buildshift-worker-proxy")
    req.add_header("Accept", "*/*")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            headers = {
                "content-type": resp.headers.get("content-type") or "application/octet-stream"
            }
            return int(resp.status), headers, data
    except urllib.error.HTTPError as exc:
        data = exc.read() if hasattr(exc, "read") else str(exc).encode()
        return int(exc.code), {"content-type": "text/plain"}, data
    except Exception as exc:  # noqa: BLE001 — surface to agent as 502
        body = json.dumps({"error": "proxy_fetch_failed", "detail": str(exc)}).encode()
        return 502, {"content-type": "application/json"}, body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter
        sys.stderr.write("[github-proxy] " + (fmt % args) + "\n")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/health", "/"):
            body = json.dumps({"ok": True, "repo": f"{OWNER}/{REPO}"}).encode()
            self._send(200, {"content-type": "application/json"}, body)
            return
        if parsed.path != "/fetch":
            self._send(404, {"content-type": "text/plain"}, b"not found")
            return
        qs = urllib.parse.parse_qs(parsed.query)
        url = (qs.get("url") or [""])[0].strip()
        if not url:
            self._send(400, {"content-type": "text/plain"}, b"missing url")
            return
        status, headers, body = _fetch(url)
        self._send(status, headers, body)

    def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        self.send_header("content-length", str(len(body)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    # Drop token from this process environ copy after capture (children of proxy won't be spawned)
    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    sys.stderr.write(
        f"[github-proxy] listening on 127.0.0.1:{PORT} allow={OWNER}/{REPO} token={'yes' if TOKEN else 'no'}\n"
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
