"""Custom exceptions for firm-bot.

The error hierarchy is deliberately flat — there's no need for
deep inheritance when every error ends up as a 4xx or 5xx response.

Convention:
- ``FirmBotError`` is the root; catch this in CLI / API to surface a
  user-friendly message.
- All subclasses carry a ``user_message`` attribute suitable for
  rendering in the UI without leaking internals.
- Operators see the full traceback via ``logging.exception``;
  end-users see ``user_message``.
"""
from __future__ import annotations


class FirmBotError(Exception):
    """Base class for all firm-bot errors."""

    user_message: str = "An internal error occurred."

    def __init__(self, message: str = "", *, user_message: str | None = None) -> None:
        super().__init__(message or self.user_message)
        if user_message is not None:
            self.user_message = user_message


class ConfigError(FirmBotError):
    user_message = "Configuration is invalid."


class InvalidSlugError(ConfigError):
    user_message = "Slug must be lowercase, alphanumeric, with - or _."


class FirmExistsError(FirmBotError):
    user_message = "A firm with that slug already exists."


class FirmNotFoundError(FirmBotError):
    user_message = "No firm with that slug."


class IngestError(FirmBotError):
    user_message = "Failed to ingest one or more files."


class NotIndexedError(FirmBotError):
    user_message = (
        "This firm has no indexed chunks yet. "
        "Drop files into the firm's source/ directory and run "
        "`firm-bot ingest <slug>` first."
    )


class EmptyQueryError(FirmBotError):
    user_message = "Question cannot be empty."


class OllamaUnreachableError(FirmBotError):
    user_message = (
        "Could not reach the local Ollama server. "
        "Is Ollama running on the configured host?"
    )


class JudgeVerdictError(FirmBotError):
    """The judge LLM could not produce a parseable verdict."""

    user_message = "Citation guard could not evaluate the answer."


class FileTooLargeError(FirmBotError):
    user_message = "Uploaded file exceeds the maximum allowed size."
