# -*- coding: utf-8 -*-
"""A Dropbox that fits in one process: the handful of endpoints the sync
uses, on an in-memory dict, served by `http.server` in a thread.

    with FakeDropbox() as box:
        os.environ["KINGMAKER_DROPBOX_API"] = box.url   # before importing dropbox.py

Files carry `rev` and `server_modified` like the real thing; `upload` in
"update" mode fails with `path/conflict/file` when the rev moved on;
`box.fail_next(429, retry_after=1)` injects one rate-limited answer;
`box.clock` is the server's idea of "now", advanced by the tests.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeDropbox:
    def __init__(self) -> None:
        self.files: dict[str, dict] = {}          # path_lower → {name, path, data, rev, modified}
        self.folders: set[str] = set()
        self.clock = time.time()
        self.revs = 0
        self.calls: list[str] = []
        self.injected: list[tuple[int, dict]] = []
        self.refreshes = 0
        # The real service keeps an upload of identical bytes as the same
        # revision, `server_modified` included; switched on by the tests
        # that must survive that.
        self.dedupe = False
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    # ------------------------------------------------------------ control
    def __enter__(self) -> "FakeDropbox":
        box = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a) -> None:
                pass

            def do_POST(self) -> None:
                box.handle(self)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_a) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def fail_next(self, status: int, retry_after: float | None = None, summary: str = "too_many_requests") -> None:
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
        self.injected.append((status, {"headers": headers, "summary": summary}))

    def stamp(self, when: float | None = None) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when if when is not None else self.clock))

    def put(self, path: str, data: bytes, when: float | None = None) -> dict:
        """A file placed by the test itself (paths as the API sees them:
        with the leading slash)."""
        with self.lock:
            return self._write("/" + path.lstrip("/"), data, when)

    def _write(self, path: str, data: bytes, when: float | None = None) -> dict:
        self.revs += 1
        entry = {"name": path.rsplit("/", 1)[-1], "path": path, "data": data,
                 "rev": f"{self.revs:016x}", "modified": when if when is not None else self.clock}
        self.files[path.lower()] = entry
        parent = path.rsplit("/", 1)[0] if "/" in path.strip("/") else ""
        while parent and parent != "/":
            self.folders.add(parent.lower())
            parent = parent.rsplit("/", 1)[0] if "/" in parent.strip("/") else ""
        return entry

    def _meta(self, entry: dict) -> dict:
        return {".tag": "file", "name": entry["name"], "path_lower": entry["path"].lower(),
                "path_display": entry["path"], "rev": entry["rev"], "size": len(entry["data"]),
                "server_modified": self.stamp(entry["modified"]),
                "client_modified": self.stamp(entry["modified"])}

    # ------------------------------------------------------------ serving
    def handle(self, h: BaseHTTPRequestHandler) -> None:
        route = h.path.split("?")[0]
        self.calls.append(route)
        length = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(length) if length else b""
        if self.injected:
            status, extra = self.injected.pop(0)
            self._answer(h, status, {"error_summary": extra["summary"], "error": {".tag": extra["summary"]}},
                         extra["headers"])
            return
        if route == "/oauth2/token":
            fields = dict(p.split("=", 1) for p in body.decode().split("&") if "=" in p)
            grant = fields.get("grant_type")
            if grant == "refresh_token":
                self.refreshes += 1
                self._answer(h, 200, {"access_token": f"at-{self.refreshes}", "expires_in": 14400,
                                      "token_type": "bearer"})
            elif grant == "authorization_code" and fields.get("code") == "GOOD-CODE":
                self._answer(h, 200, {"access_token": "at-0", "refresh_token": "rt-secret",
                                      "expires_in": 14400, "account_id": "dbid:test", "uid": "1"})
            else:
                self._answer(h, 400, {"error": "invalid_grant", "error_description": "code not valid"})
            return
        if not h.headers.get("Authorization", "").startswith("Bearer "):
            self._answer(h, 401, {"error_summary": "invalid_access_token/"})
            return
        arg = {}
        content_type = h.headers.get("Content-Type") or ""
        if h.headers.get("Dropbox-API-Arg"):
            arg = json.loads(h.headers["Dropbox-API-Arg"])
        elif content_type.startswith("application/json"):
            arg = json.loads(body.decode("utf-8") or "null") or {}
        elif body or content_type:
            # What the real service says to a form post on an RPC route.
            self._answer(h, 400, {"error_summary": f'Bad HTTP "Content-Type" header: {content_type}. '
                                  'Expecting one of application/json, application/json; charset=utf-8, text/.'})
            return
        with self.lock:
            self._dispatch(h, route, arg, body)

    def _dispatch(self, h, route: str, arg: dict, body: bytes) -> None:
        path = str(arg.get("path") or "")
        key = path.lower()
        if route == "/2/users/get_current_account":
            self._answer(h, 200, {"account_id": "dbid:test", "name": {"display_name": "Test Owner"},
                                  "email": "owner@example.test"})
        elif route == "/2/users/get_space_usage":
            used = sum(len(e["data"]) for e in self.files.values())
            self._answer(h, 200, {"used": used, "allocation": {".tag": "individual", "allocated": 2 * 1024 ** 3}})
        elif route == "/2/auth/token/revoke":
            self._answer(h, 200, {})
        elif route == "/2/files/get_metadata":
            entry = self.files.get(key)
            if entry is None:
                self._answer(h, 409, {"error_summary": "path/not_found/", "error": {".tag": "path"}})
            else:
                self._answer(h, 200, self._meta(entry))
        elif route == "/2/files/list_folder":
            if key and key not in self.folders and not any(k.startswith(key + "/") for k in self.files):
                self._answer(h, 409, {"error_summary": "path/not_found/", "error": {".tag": "path"}})
                return
            entries = [self._meta(e) for k, e in self.files.items()
                       if k.rsplit("/", 1)[0] == key or (not key and "/" not in k.strip("/"))]
            self._answer(h, 200, {"entries": entries, "cursor": "c", "has_more": False})
        elif route == "/2/files/download":
            entry = self.files.get(key)
            if entry is None:
                self._answer(h, 409, {"error_summary": "path/not_found/", "error": {".tag": "path"}})
            else:
                self._answer(h, 200, entry["data"], {"Dropbox-API-Result": json.dumps(self._meta(entry))}, raw=True)
        elif route == "/2/files/upload":
            mode = arg.get("mode") or {".tag": "add"}
            tag = mode.get(".tag")
            existing = self.files.get(key)
            if tag == "add" and existing is not None:
                self._answer(h, 409, {"error_summary": "path/conflict/file/", "error": {".tag": "path"}})
                return
            if tag == "update" and (existing is None or existing["rev"] != mode.get("update")):
                self._answer(h, 409, {"error_summary": "path/conflict/file/", "error": {".tag": "path"}})
                return
            if self.dedupe and existing is not None and existing["data"] == body:
                self._answer(h, 200, self._meta(existing))     # nothing new: the old revision stays
                return
            entry = self._write(path, body)
            self._answer(h, 200, self._meta(entry))
        elif route == "/2/files/delete_v2":
            entry = self.files.pop(key, None)
            if entry is None:
                self._answer(h, 409, {"error_summary": "path_lookup/not_found/", "error": {".tag": "path_lookup"}})
            else:
                self._answer(h, 200, {"metadata": self._meta(entry)})
        elif route == "/2/files/create_folder_v2":
            if key in self.folders:
                self._answer(h, 409, {"error_summary": "path/conflict/folder/", "error": {".tag": "path"}})
            else:
                self.folders.add(key)
                self._answer(h, 200, {"metadata": {".tag": "folder", "name": path.rsplit("/", 1)[-1]}})
        else:
            self._answer(h, 404, {"error_summary": "unknown route"})

    @staticmethod
    def _answer(h, status: int, payload, headers: dict | None = None, raw: bool = False) -> None:
        data = payload if raw else json.dumps(payload).encode("utf-8")
        h.send_response(status)
        h.send_header("Content-Type", "application/octet-stream" if raw else "application/json")
        h.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            h.send_header(name, value)
        h.end_headers()
        h.wfile.write(data)
