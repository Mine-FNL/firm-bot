"""Integration adapters for firm-bot.

Each sub-package is a separate integration target (Slack, Teams, Google
Workspace, …). The core ``firm_bot`` engine stays free of any vendor
SDKs — adapters import nothing from the adapter's vendor SDK either;
they expose thin primitives the operator wires into the vendor's
official runtime (e.g. Slack's Bolt for Python, Microsoft Graph SDK).

Available integrations are re-exported here as the public API.
"""

from __future__ import annotations

from . import slack

__all__ = ["slack"]
