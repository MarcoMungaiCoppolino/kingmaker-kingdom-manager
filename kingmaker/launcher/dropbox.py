"""A small Dropbox client, standard library only: what the sync needs and
nothing more.

OAuth with PKCE and no redirect (the code is shown on dropbox.com and pasted
into the launcher), a refresh token that does not expire, short-lived access
tokens refreshed on demand. Every call honours `Retry-After` on 429 and
retries a few times with a growing pause; `too_many_write_operations` is
retried at once, as Dropbox asks. The base URLs can be pointed at a fake
server through `KINGMAKER_DROPBOX_API` (tests only).
"""
from __future__ import annotations

import base64
import email.utils
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

API = os.environ.get("KINGMAKER_DROPBOX_API", "").rstrip("/") or "https://api.dropboxapi.com"
CONTENT = os.environ.get("KINGMAKER_DROPBOX_CONTENT", "").rstrip("/") or "https://content.dropboxapi.com"
WWW = os.environ.get("KINGMAKER_DROPBOX_WWW", "").rstrip("/") or "https://www.dropbox.com"
SCOPES = ("account_info.read", "files.metadata.read", "files.metadata.write",
          "files.content.read", "files.content.write")
RETRIES = 5
TIMEOUT = 30.0
UPLOAD_LIMIT = 150 * 1024 * 1024
USER_AGENT = "Kingmaker-Kingdom-Manager"


class DropboxError(Exception):
    """An answer Dropbox gave and we could not use: `status` and the JSON
    `error` when there was one, `summary` for the log."""

    def __init__(self, status: int, summary: str, error: dict | None = None) -> None:
        super().__init__(f"{status}: {summary}")
        self.status = status
        self.summary = summary
        self.error = error or {}

    @property
    def conflict(self) -> bool:
        """The compare-and-swap lost: the file changed under our `rev`."""
        return self.status == 409 and "conflict" in self.summary

    @property
    def not_found(self) -> bool:
        return self.status == 409 and "not_found" in self.summary


# ------------------------------------------------------------------- OAuth
def new_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def authorize_url(app_key: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    query = urllib.parse.urlencode({
        "client_id": app_key, "response_type": "code",
        "token_access_type": "offline", "scope": " ".join(SCOPES),
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    return f"{WWW}/oauth2/authorize?{query}"


def _token_call(fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(f"{API}/oauth2/token", data=data, method="POST",
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body)
        except ValueError:
            detail = {}
        raise DropboxError(error.code, detail.get("error_description") or body[:200], detail)


def exchange_code(app_key: str, verifier: str, code: str) -> dict:
    """The pasted code → `{"access_token", "refresh_token", "expires_in", "account_id"}`."""
    return _token_call({"grant_type": "authorization_code", "code": code.strip(),
                        "client_id": app_key, "code_verifier": verifier})


def refresh(app_key: str, refresh_token: str) -> dict:
    return _token_call({"grant_type": "refresh_token", "refresh_token": refresh_token,
                        "client_id": app_key})


# ------------------------------------------------------------------ client
@dataclass
class Credential:
    """What a host needs to reach the table's folder. Travels in
    `launcher.json`, never in the database."""
    app_key: str
    refresh_token: str
    account_id: str = ""
    account_name: str = ""
    app_name: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Credential | None":
        if not raw or not raw.get("app_key") or not raw.get("refresh_token"):
            return None
        return cls(**{f: str(raw.get(f, "")) for f in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


class Client:
    """Files in the app folder. Paths are given without the leading slash
    and relative to the folder; `rev` values are Dropbox's."""

    def __init__(self, credential: Credential, sleep: Callable[[float], None] = time.sleep) -> None:
        self.credential = credential
        self.sleep = sleep
        self._access: str = ""
        self._expires_at: float = 0.0

    # ------------------------------------------------------------ plumbing
    def _token(self) -> str:
        if not self._access or time.time() > self._expires_at - 60:
            answer = refresh(self.credential.app_key, self.credential.refresh_token)
            self._access = str(answer["access_token"])
            self._expires_at = time.time() + float(answer.get("expires_in") or 14400)
        return self._access

    @staticmethod
    def _http_date(value: str | None) -> float | None:
        """An HTTP Date header as seconds since the epoch; None when absent
        or not a date (a proxy's, say)."""
        if not value:
            return None
        try:
            return email.utils.parsedate_to_datetime(value).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None

    def _call(self, base: str, route: str, arg: dict | None = None, body: bytes | None = None,
              raw: bool = False, arg_in_header: bool = False) -> tuple[bytes, dict]:
        """One request with retries. Returns (body, api-result json)."""
        for attempt in range(RETRIES):
            headers = {"Authorization": f"Bearer {self._token()}", "User-Agent": USER_AGENT}
            data = body
            if arg_in_header:
                headers["Dropbox-API-Arg"] = json.dumps(arg or {}, ensure_ascii=True)
                if body is not None:
                    headers["Content-Type"] = "application/octet-stream"
            else:
                # An RPC call: JSON, and `null` when there are no parameters.
                # An empty body would go out as a form post, which Dropbox
                # refuses with a complaint about the Content-Type.
                headers["Content-Type"] = "application/json"
                data = json.dumps(arg).encode("utf-8") if arg is not None else b"null"
            request = urllib.request.Request(f"{base}/2/{route}", data=data if data is not None else b"",
                                             method="POST", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                    content = answer.read()
                    result_header = answer.headers.get("Dropbox-API-Result")
                    if result_header:
                        result = json.loads(result_header)
                        # The server's clock, free with every answer: what a
                        # record's age is judged by, without writing a file
                        # to read the time off (`sync.server_now`).
                        when = self._http_date(answer.headers.get("Date"))
                        if when is not None and isinstance(result, dict):
                            result["_server_time"] = when
                        return content, result
                    if raw:
                        return content, {}
                    return content, (json.loads(content.decode("utf-8")) if content.strip() else {})
            except urllib.error.HTTPError as error:
                text = error.read().decode("utf-8", "replace")
                try:
                    detail = json.loads(text)
                except ValueError:
                    detail = {}
                summary = str(detail.get("error_summary") or text[:200])
                if error.code == 401 and attempt == 0:
                    self._access = ""          # expired early: refresh and retry once
                    continue
                if error.code == 429 or error.code >= 500:
                    wait = error.headers.get("Retry-After")
                    pause = float(wait) if wait not in (None, "") else min(2 ** attempt, 30)
                    if "too_many_write_operations" in summary:
                        pause = 0.0
                    self.sleep(pause)
                    continue
                raise DropboxError(error.code, summary, detail)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == RETRIES - 1:
                    raise DropboxError(0, f"unreachable: {error}")
                self.sleep(min(2 ** attempt, 30))
        raise DropboxError(429, "gave up after retries")

    # ------------------------------------------------------------- account
    def account(self) -> dict:
        _body, result = self._call(API, "users/get_current_account")
        return result

    def space_usage(self) -> tuple[int, int]:
        """(used, allocated) in bytes."""
        _body, result = self._call(API, "users/get_space_usage")
        allocation = result.get("allocation") or {}
        return int(result.get("used") or 0), int(allocation.get("allocated") or 0)

    def revoke(self) -> None:
        try:
            self._call(API, "auth/token/revoke")
        except DropboxError:
            pass

    # --------------------------------------------------------------- files
    @staticmethod
    def _path(path: str) -> str:
        return "/" + path.strip("/") if path.strip("/") else ""

    def metadata(self, path: str) -> dict | None:
        """The file's metadata (`rev`, `server_modified`, `size`…) or None."""
        try:
            _body, result = self._call(API, "files/get_metadata", {"path": self._path(path)})
        except DropboxError as error:
            if error.not_found:
                return None
            raise
        return result

    def list_folder(self, path: str) -> list[dict]:
        """The entries of a folder, all pages; [] when the folder is missing."""
        try:
            _body, result = self._call(API, "files/list_folder", {"path": self._path(path)})
        except DropboxError as error:
            if error.not_found:
                return []
            raise
        entries = list(result.get("entries") or [])
        while result.get("has_more"):
            _body, result = self._call(API, "files/list_folder/continue", {"cursor": result["cursor"]})
            entries += result.get("entries") or []
        return entries

    def download(self, path: str) -> tuple[bytes, dict]:
        body, result = self._call(CONTENT, "files/download", {"path": self._path(path)},
                                  body=None, raw=True, arg_in_header=True)
        return body, result

    def upload(self, path: str, data: bytes, mode: str = "overwrite", rev: str | None = None) -> dict:
        """`mode` is "add", "overwrite" or "update" (with `rev`: the
        compare-and-swap, DropboxError.conflict when the file moved on)."""
        if len(data) > UPLOAD_LIMIT:
            raise DropboxError(413, "file larger than one upload call allows")
        write_mode: dict = {".tag": mode}
        if mode == "update":
            write_mode["update"] = rev or ""
        arg = {"path": self._path(path), "mode": write_mode, "autorename": False, "mute": True}
        _body, result = self._call(CONTENT, "files/upload", arg, body=data, arg_in_header=True)
        return result

    def delete(self, path: str) -> None:
        try:
            self._call(API, "files/delete_v2", {"path": self._path(path)})
        except DropboxError as error:
            if not error.not_found:
                raise

    def create_folder(self, path: str) -> None:
        try:
            self._call(API, "files/create_folder_v2", {"path": self._path(path), "autorename": False})
        except DropboxError as error:
            if "conflict" not in error.summary:
                raise
