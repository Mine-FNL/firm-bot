"""FastAPI surface for firm-bot.

Endpoints
---------
GET  /                                     → single-page chat UI (HTML)
GET  /v1/firms                             → list known firms (admin)
POST /v1/firms                             → create a firm
GET  /v1/firms/{slug}/config               → read firm config
PATCH /v1/firms/{slug}/config              → update firm config (system prompt, model)
POST /v1/firms/{slug}/ingest               → scan source/, extract, chunk, embed, index
GET  /v1/firms/{slug}/stats                → chunk counts + file counts
POST /v1/firms/{slug}/query                → ask a question, get an annotated answer
POST /v1/firms/{slug}/upload               → upload one file into source/
POST /v1/firms/{slug}/eval                 → run faithfulness eval over a Q/A fixture

v0.1 deliberately has NO auth. Each firm is a closed deployment
(self-hosted inside a firm's network). When you put this on the
internet, add auth — see SECURITY.md in the docs/ folder.
"""
from __future__ import annotations

from .app import app

__all__ = ["app"]
