"""
Minimal example: one MCP tool (check_balance) wired to your existing
ledger HTTP API. Meant purely to show the shape of an MCP server —
not a full server, just enough to see how the pieces connect.

Uses the `fastmcp` package (built on top of the official MCP Python SDK)
and the streamable-http transport, matching the "separate service,
HTTP API" architecture you already decided on.

    pip install fastmcp httpx
"""

import os
import uuid

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

LEDGER_API_BASE = "http://localhost:8000"

# Independent of any limit the ledger API itself enforces — this is a
# separate, MCP-only ceiling on what an LLM-initiated transfer can move.
MCP_TRANSFER_LIMIT_CENTS = int(os.environ.get("MCP_TRANSFER_LIMIT_CENTS", "10000"))

mcp = FastMCP("ledger-mcp")


@mcp.tool()
async def check_balance(account_id: int | None = None) -> dict:
    """
    Checks the available balance for the authenticated user.

    Identity comes from the Authorization header on the MCP connection,
    forwarded straight through to the ledger API, which resolves it to a
    user. account_id only selects among that user's own accounts; the
    API rejects any account the user doesn't own. It can be omitted when
    the user has exactly one account.
    """
    headers = get_http_headers(include={"authorization"})
    auth_header = headers.get("authorization")

    if not auth_header:
        return {"error": "Missing Authorization header — connect with a valid API token."}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                f"{LEDGER_API_BASE}/accounts/check-balance",
                headers={"Authorization": auth_header},
                params={"account_id": account_id} if account_id is not None else None,
            )
        except httpx.TimeoutException:
            return {"error": "Timed out waiting for the ledger API to respond."}

    try:
        body = resp.json()
    except ValueError:
        return {"error": f"Ledger API returned a non-JSON response (status {resp.status_code})."}

    if resp.status_code != 200:
        return {"error": body.get("detail", "Failed to fetch balance")}

    return body


@mcp.tool()
async def transfer_funds(
    from_account_id: int, receiver_account_number: str, amount_cents: int
) -> dict:
    """
    Transfers money from one of the authenticated user's accounts to
    another account, up to the configured MCP transfer limit.

    - The user is always the identity resolved from the Authorization
      header. from_account_id picks which of *their* accounts to debit;
      the ledger API rejects any account they don't own.
    - amount_cents is checked against the MCP-only transfer limit before
      the ledger API is ever called; an over-limit request never reaches
      /transfer.
    - idempotency_key is generated here, once per invocation — it's an
      internal correctness mechanism for safe retries, not a decision
      the caller should be making.
    """
    if amount_cents <= 0:
        return {"error": "amount_cents must be positive."}

    if amount_cents > MCP_TRANSFER_LIMIT_CENTS:
        return {
            "error": (
                f"Transfer of {amount_cents} cents exceeds the MCP transfer "
                f"limit of {MCP_TRANSFER_LIMIT_CENTS} cents."
            )
        }

    headers = get_http_headers(include={"authorization"})
    auth_header = headers.get("authorization")

    if not auth_header:
        return {"error": "Missing Authorization header — connect with a valid API token."}

    idempotency_key = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{LEDGER_API_BASE}/accounts/transfer",
                headers={"Authorization": auth_header},
                json={
                    "from_account_id": from_account_id,
                    "to_account_number": receiver_account_number,
                    "amount": amount_cents,
                    "idempotency_key": idempotency_key,
                },
            )
        except httpx.TimeoutException:
            return {"error": "Timed out waiting for the ledger API to respond."}

    try:
        body = resp.json()
    except ValueError:
        return {"error": f"Ledger API returned a non-JSON response (status {resp.status_code})."}

    if resp.status_code != 200:
        return {"error": body.get("detail", "Transfer failed.")}

    return body


if __name__ == "__main__":
    # streamable-http, not stdio, since you're building a multi-user
    # remote server rather than a single local subprocess
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)