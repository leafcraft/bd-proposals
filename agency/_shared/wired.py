"""Is a connector wired? — decided by its vault record, never by .env.

A connector's address and token live only in the vault (Studio →
Infrastructure). The day-0 stand-ins ask here whether the record the real
connector would use exists, so their "not wired" messages stay honest.
"""
from __future__ import annotations

from leafmesh import connection_rows
from leafmesh.vault.refs import UnresolvedVaultRef

OPPORTUNITY_FEED_RECORD = "opportunity_feed_n8n"
DMS_RECORD = "dms_mcp"


async def vault_record_exists(name: str) -> bool:
    """True when the vault record `name` exists. connection_rows raises
    UnresolvedVaultRef when there is no such record (or no vault at all) →
    not wired. Any other error means the record exists but is not ours to
    read as rows (an n8n / MCP record, or an agents allowlist) → wired."""
    try:
        await connection_rows(name)
        return True
    except UnresolvedVaultRef:
        return False
    except PermissionError:  # SecretNotAllowed: the record exists; it only limits which agents read it
        return True
