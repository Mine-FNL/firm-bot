"""Synchronous firm-bot HTTP client.

The SDK targets any firm-bot server version ``>= 0.2.0``. It uses only
Python standard-library modules (``urllib``, ``json``, ``mimetypes``,
``http``) — no ``requests`` / ``httpx`` / ``pydantic`` dependency.

All public methods are synchronous. The HTTP client is intentionally
simple: one ``urllib.request.Request`` per call, raised status codes
mapped to typed exceptions, JSON bodies parsed into dataclasses.
Streaming endpoints (``query/stream``) are not wrapped here — they
require a streaming HTTP client, which is out of scope for the
synchronous SDK.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any

from .errors import (
    AuthError,
    FirmBotError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .types import (
    AuditLogEntry,
    EvalResult,
    FirmConfig,
    FirmSummary,
    IngestResult,
    QueryResponse,
    UploadResult,
)

# Map HTTP status -> exception class. Anything not in this map is
# treated as a generic FirmBotError. 409 Conflict is intentionally NOT
# mapped — it carries semantic meaning callers may want to handle
# (firm-already-exists) so we let it bubble up as the base class.
_STATUS_MAP: dict[int, type[FirmBotError]] = {
    400: ValidationError,
    401: AuthError,
    403: AuthError,
    404: NotFoundError,
    422: ValidationError,
    429: RateLimitError,
}


class FirmBotClient:
    """Synchronous client for the firm-bot HTTP API.

    >>> client = FirmBotClient("http://localhost:8080", api_key="fb_...")
    >>> firms = client.list_firms()
    >>> [f.slug for f in firms]
    []

    The client is stateless apart from its base URL, auth header, and
    timeout — safe to share across threads provided the underlying
    transport is. (``urllib.request`` opens a fresh socket per call,
    so no shared mutable state is involved.)
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 60.0,
    ) -> None:
        # Strip a single trailing slash so URL building is unambiguous.
        self.base_url: str = base_url.rstrip("/")
        self.api_key: str = api_key
        self.timeout_s: float = float(timeout_s)

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def list_firms(self) -> list[FirmSummary]:
        """``GET /v1/firms`` — list all configured firms."""
        payload = self._request("GET", "/v1/firms")
        items = payload.get("firms", []) if isinstance(payload, dict) else []
        return [FirmSummary.from_dict(item) for item in items]

    def create_firm(
        self,
        slug: str,
        name: str,
        *,
        system_prompt: str = "",
        llm_model: str = "",
        contact_email: str = "",
    ) -> FirmConfig:
        """``POST /v1/firms`` — create a new firm.

        Any extra firm-creation fields supported by the server can be
        supplied via ``**kwargs`` if you construct the request manually
        — but the explicit kwargs cover every field the firm-bot 0.2
        ``CreateFirmRequest`` model accepts.
        """
        body: dict[str, Any] = {
            "slug": slug,
            "name": name,
            "system_prompt": system_prompt,
            "llm_model": llm_model,
            "contact_email": contact_email,
        }
        payload = self._request("POST", "/v1/firms", json_body=body)
        return FirmConfig.from_dict(payload)

    def get_firm(self, slug: str) -> FirmConfig:
        """``GET /v1/firms/{slug}/config`` — read full firm config.

        The server additionally returns ``effective_system_prompt``,
        which is the resolved system prompt after template substitution
        (root default + firm override). It is surfaced as
        :attr:`FirmConfig.effective_system_prompt`.
        """
        payload = self._request("GET", self._firm_path(slug, "config"))
        return FirmConfig.from_dict(payload)

    def update_firm(self, slug: str, **patch: Any) -> FirmConfig:
        """``PATCH /v1/firms/{slug}/config`` — partial update.

        Pass any subset of ``name``, ``system_prompt``, ``llm_model``,
        ``contact_email``, ``notes``. Unknown fields are forwarded as-is
        so newer server fields work transparently.
        """
        payload = self._request("PATCH", self._firm_path(slug, "config"), json_body=patch)
        return FirmConfig.from_dict(payload)

    def ingest(self, slug: str, source_dir: str | Path) -> IngestResult:
        """Upload every file under ``source_dir`` then trigger ingest.

        Walks ``source_dir`` recursively, uploads each file via
        :meth:`upload_file`, then calls ``POST /v1/firms/{slug}/ingest``.
        Returns the resulting :class:`IngestResult`.

        For very large corpora prefer streaming uploads directly via
        :meth:`upload_file` so you can show progress to the user.
        """
        root = Path(source_dir)
        if not root.is_dir():
            raise ValueError(f"source_dir is not a directory: {source_dir!r}")
        for entry in sorted(root.rglob("*")):
            if entry.is_file():
                self.upload_file(slug, entry)
        payload = self._request(
            "POST",
            self._firm_path(slug, "ingest"),
            query={"force": "false"},
        )
        return IngestResult.from_dict(payload)

    def upload_file(self, slug: str, file_path: str | Path) -> UploadResult:
        """``POST /v1/firms/{slug}/upload`` — upload a single file.

        Builds an RFC 7578 ``multipart/form-data`` body using only
        stdlib (no ``requests``). The file is streamed into a
        ``BytesIO``-equivalent boundary buffer because
        :mod:`urllib.request` cannot natively consume a pathlib Path.
        """
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"file not found: {file_path!r}")
        body, content_type = self._encode_multipart(path)
        payload = self._request(
            "POST",
            self._firm_path(slug, "upload"),
            raw_body=body,
            raw_content_type=content_type,
        )
        return UploadResult.from_dict(payload)

    def query(
        self,
        slug: str,
        question: str,
        k: int = 6,
        run_guard: bool = True,
        history: list[dict[str, str]] | None = None,
    ) -> QueryResponse:
        """``POST /v1/firms/{slug}/query`` — non-streaming query.

        ``k`` defaults to 6 to match firm-bot's ``answer_k`` default
        for new deployments. ``history`` is an open shape — the server
        only inspects the ``role`` and ``content`` keys per message,
        but extra keys are passed through so future schema work
        remains backwards-compatible.
        """
        body: dict[str, Any] = {
            "question": question,
            "k": k,
            "run_guard": run_guard,
        }
        if history is not None:
            body["history"] = list(history)
        payload = self._request("POST", self._firm_path(slug, "query"), json_body=body)
        return QueryResponse.from_dict(payload)

    def get_audit_log(
        self,
        slug: str,
        since: str | None = None,
        until: str | None = None,
        format: str = "json",
    ) -> Any:
        """``GET /v1/firms/{slug}/audit-log`` — read the per-firm audit log.

        ``format`` may be ``"json"`` (returns a list of
        :class:`AuditLogEntry`), ``"csv"`` (returns a raw CSV string),
        ``"jsonl"`` (returns a raw JSON-Lines string), or ``"md"``
        (returns a Markdown table). Other values raise
        :class:`ValueError`.

        ``since`` and ``until`` are ISO 8601 timestamps. The server
        defaults them to the last 90 days / now respectively.
        """
        if format not in {"json", "csv", "jsonl", "md"}:
            raise ValueError(f"unsupported audit log format: {format!r}")
        query: dict[str, str] = {"fmt": format}
        if since is not None:
            query["since"] = since
        if until is not None:
            query["until"] = until
        payload = self._request(
            "GET",
            self._firm_path(slug, "audit-log"),
            query=query,
            raw_response=format != "json",
        )
        if format != "json":
            return payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        return [AuditLogEntry.from_dict(item) for item in (payload or [])]

    def eval_firm(self, slug: str, cases: list[dict[str, Any]]) -> EvalResult:
        """``POST /v1/firms/{slug}/eval`` — run a faithfulness eval.

        Each entry in ``cases`` is a dict with ``question`` plus the
        optional ``expected_sources`` and ``expected_keywords`` lists.
        """
        payload = self._request(
            "POST",
            self._firm_path(slug, "eval"),
            json_body={"cases": list(cases)},
        )
        return EvalResult.from_dict(payload)

    # ------------------------------------------------------------------ #
    # Internal request plumbing                                          #
    # ------------------------------------------------------------------ #

    def _firm_path(self, slug: str, *parts: str) -> str:
        """Build ``/v1/firms/{slug}/{part1}/{part2}...`` with URL-escaping.

        Slugs are restricted to ``[a-z0-9][a-z0-9_-]{1,40}`` by the
        server, so URL-escaping is mostly defensive — but we still
        apply ``quote`` to prevent a malformed slug from breaking
        the URL.
        """
        segments = [urllib.parse.quote(seg, safe="") for seg in ("v1", "firms", slug, *parts)]
        return "/" + "/".join(segments)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        raw_body: bytes | None = None,
        raw_content_type: str | None = None,
        query: Mapping[str, str] | None = None,
        raw_response: bool = False,
    ) -> Any:
        """Single round-trip to firm-bot.

        Maps non-2xx responses to typed exceptions (see
        :mod:`.errors`) and decodes JSON bodies for callers. Setting
        ``raw_response=True`` skips JSON decoding so callers can read
        text/csv / text/markdown / application/x-ndjson payloads
        verbatim.
        """
        url = self.base_url + path
        if query:
            url = f"{url}?{urllib.parse.urlencode(dict(query))}"

        headers: dict[str, str] = {
            "Accept": "application/json",
            "X-API-Key": self.api_key,
            "User-Agent": "firm-bot-sdk/0.1.0",
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif raw_body is not None:
            data = raw_body
            if raw_content_type is not None:
                headers["Content-Type"] = raw_content_type

        req = urllib.request.Request(url=url, data=data, method=method, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            # The HTTPError object exposes the same .read() / .status
            # surface as a successful response. Decode the body so
            # callers can inspect the structured error detail.
            err_body_bytes = exc.read() if hasattr(exc, "read") else b""
            err_body: Any = (
                self._decode_body(err_body_bytes) if err_body_bytes else None
            )
            self._raise_for_status(exc.code, err_body, path)
            # _raise_for_status always raises; this line is unreachable
            # but keeps type-checkers happy.
            raise ServerError(
                f"unreachable: status {exc.code} did not map to an exception",
                status=exc.code,
                body=err_body,
                path=path,
            ) from exc
        except urllib.error.URLError as exc:
            # Network-level failure (DNS, refused, timeout). Surface
            # the underlying exception via __cause__ so callers can
            # inspect the original urllib reason.
            raise FirmBotError(
                f"network error contacting {self.base_url}: {exc.reason}",
                path=path,
            ) from exc
        except TimeoutError as exc:
            raise FirmBotError(
                f"timeout after {self.timeout_s}s contacting {self.base_url}",
                path=path,
            ) from exc

        if status < 200 or status >= 300:
            # Success path with a non-2xx status — should be impossible
            # for urlopen (it raises HTTPError on non-2xx) but guard
            # anyway so behaviour is well-defined if the contract ever
            # changes.
            self._raise_for_status(status, self._decode_body(body), path)
            raise ServerError(  # pragma: no cover - defensive
                f"unexpected status {status}", status=status, path=path
            )

        if raw_response:
            return body.decode("utf-8", errors="replace")
        return self._decode_body(body)

    def _decode_body(self, body: bytes) -> Any:
        """Decode an HTTP body as JSON when possible, else UTF-8 text.

        The firm-bot API only returns JSON for application/json
        responses, but a few endpoints (CSV / Markdown / JSONL) emit
        other media types that the SDK treats as raw strings — those
        paths go through ``raw_response=True`` so this method is
        called with a known-JSON body in practice.
        """
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body.decode("utf-8", errors="replace")

    def _raise_for_status(self, status: int, body: Any, path: str) -> None:
        """Translate an HTTP status into the SDK's exception hierarchy."""
        if status in _STATUS_MAP:
            cls = _STATUS_MAP[status]
            detail: Any = body
            if isinstance(body, dict) and "detail" in body:
                detail = body["detail"]
            message = str(detail) if detail is not None else HTTPStatus(status).phrase
            raise cls(message, status=status, body=body, path=path)
        if 500 <= status <= 599:
            raise ServerError(
                f"server error {status}",
                status=status,
                body=body,
                path=path,
            )
        # Fallback: surface unknown status codes as the base class so
        # the caller can still react (e.g. handle 409 themselves).
        raise FirmBotError(
            f"unexpected status {status}",
            status=status,
            body=body,
            path=path,
        )

    # ------------------------------------------------------------------ #
    # Multipart encoding (stdlib only)                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encode_multipart(file_path: Path) -> tuple[bytes, str]:
        """Encode a file as ``multipart/form-data``.

        Returns the encoded body bytes plus the matching
        ``Content-Type`` header (including the random boundary).
        Avoids any third-party deps — stdlib ``email`` is overkill
        for a single-field upload and its boundary generation is
        fiddly, so we hand-roll a minimal encoder.
        """
        boundary = "----firm-bot-sdk" + _random_hex(16)
        filename = file_path.name
        ctype, _ = mimetypes.guess_type(filename)
        if ctype is None:
            ctype = "application/octet-stream"
        file_bytes = file_path.read_bytes()
        parts: list[bytes] = []
        parts.append(f"--{boundary}\r\n".encode("ascii"))
        parts.append(
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        parts.append(f"Content-Type: {ctype}\r\n\r\n".encode("ascii"))
        parts.append(file_bytes)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        body = b"".join(parts)
        content_type = f"multipart/form-data; boundary={boundary}"
        return body, content_type


def _random_hex(length: int) -> str:
    """Generate ``length`` random hex chars without importing secrets."""
    # ``random`` is fine for a non-cryptographic multipart boundary;
    # the boundary only needs to be unpredictable enough to not
    # collide with file content.
    import random

    return "".join(random.choice("0123456789abcdef") for _ in range(length))
