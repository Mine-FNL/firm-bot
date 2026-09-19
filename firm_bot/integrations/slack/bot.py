"""Thin HTTP client for the firm-bot REST API.

Used by the Slack adapter to query firm-bot. Pure stdlib so the
adapter ships with zero new dependencies.

We only call two endpoints:

- ``POST /v1/firms/{slug}/query`` — non-streaming answer + citations
- ``GET  /v1/firms`` — list firms (operator onboarding / admin)

The streaming endpoint (``/v1/firms/{slug}/query/stream``) is
intentionally not wrapped here. The Slack adapter posts one
threaded reply per question; SSE chunking would complicate the
per-message block layout and isn't needed for the 4000-char limit.
A future Slack adapter that wants progressive typing can wrap the
streaming endpoint itself.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class FirmBotClientError(Exception):
    """Raised when firm-bot returns a non-2xx or is unreachable.

    Attributes
    ----------
    status_code:
        HTTP status code (if any). ``None`` for transport-level
        failures (``URLError``, DNS, connection refused).
    body:
        Parsed JSON body if the server returned one, otherwise the
        raw text. ``None`` if no body was returned.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class FirmBotClient:
    """HTTP client for firm-bot's REST API.

    One client per operator workspace. Threading model: methods are
    synchronous and block on the network. Callers that need non-blocking
    behaviour (e.g. Bolt for Python async handlers) should wrap calls
    in :func:`asyncio.to_thread` or use a worker queue.

    Parameters
    ----------
    base_url:
        Root URL of the firm-bot API, e.g. ``"http://localhost:7860"``.
        Trailing slash is stripped.
    api_key:
        Workspace's firm-bot API key. Sent as
        ``Authorization: Bearer <key>``.
    timeout_s:
        Per-request timeout in seconds. Default 60 — answers can be
        slow on first call (cold model load). Operators with tight
        budgets can lower it.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = float(timeout_s)

    def query(self, firm_slug: str, question: str, **kwargs: Any) -> dict[str, Any]:
        """Query a firm and return the JSON answer payload.

        Extra ``kwargs`` are forwarded as request-body fields —
        typically ``history``, ``k``, ``run_guard`` — matching the
        ``QueryRequest`` schema in ``firm_bot.api.app``.
        """
        body: dict[str, Any] = {"question": question}
        body.update(kwargs)
        result = self._request("POST", f"/v1/firms/{firm_slug}/query", body=body)
        if not isinstance(result, dict):
            raise FirmBotClientError(
                f"firm-bot /query returned non-object body: {type(result).__name__}"
            )
        return result

    def list_firms(self) -> list[dict[str, Any]]:
        """Return the list of configured firms.

        Calls ``GET /v1/firms``. Raises :class:`FirmBotClientError`
        on transport or non-2xx errors.
        """
        result = self._request("GET", "/v1/firms")
        # The endpoint returns ``{"firms": [...], "data_dir": "..."}``;
        # accept either that shape or a bare list for forward-compat.
        if isinstance(result, dict):
            firms_raw = result.get("firms")
            if isinstance(firms_raw, list):
                return [f for f in firms_raw if isinstance(f, dict)]
            return []
        if isinstance(result, list):
            return [f for f in result if isinstance(f, dict)]
        return []

    def health(self) -> bool:
        """Return ``True`` if ``GET /healthz`` returns 2xx."""
        try:
            self._request("GET", "/healthz")
        except FirmBotClientError:
            return False
        return True

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "firm-bot-integrations-slack/0.1",
        }
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise FirmBotClientError(
                f"firm-bot unreachable at {url}: {exc.reason}",
            ) from exc

        if not raw:
            return None
        try:
            parsed: object = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FirmBotClientError(
                f"firm-bot returned non-JSON body from {method} {path}",
            ) from exc
        if isinstance(parsed, (dict, list)):
            return parsed
        # Scalar JSON values (string, number, bool) are unexpected
        # for the endpoints we call; raise rather than silently coerce.
        raise FirmBotClientError(
            f"firm-bot returned unexpected JSON scalar from {method} {path}: "
            f"{type(parsed).__name__}"
        )

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> FirmBotClientError:
        raw = b""
        try:
            raw = exc.read()
        except Exception:  # best-effort read on error path
            raw = b""
        body: Any = None
        if raw:
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                body = raw.decode("utf-8", errors="replace")
        return FirmBotClientError(
            f"firm-bot returned HTTP {exc.code} for {exc.url}: {body}",
            status_code=exc.code,
            body=body,
        )
