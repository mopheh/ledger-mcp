"""MCP server exposing the Ledger API to AI clients over stdio.

It is a thin client of the running Ledger API: every call is made with the
configured API key, so authentication, account ownership and idempotency are
enforced by the API, not here.

Environment:
    LEDGER_API_KEY   required, an `sk_...` key from POST /auth/generate-api-key
    LEDGER_API_URL   optional, defaults to http://127.0.0.1:8000

Run from the `ledger/` directory: python -m app.mcp_server
"""
import os
from uuid import uuid4

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API_URL = os.environ.get("LEDGER_API_URL", "http://127.0.0.1:8000").rstrip("/")

mcp = MCPServer(
    "ledger",
    instructions=(
        "Check balances and move money between accounts in the Ledger. "
        "Amounts are integers in the account's smallest unit. "
        "If a transfer call fails or times out, retry it with the same "
        "idempotency_key so money is never moved twice."
    ),
)


async def _call(method: str, path: str, **kwargs) -> dict:
    api_key = os.environ.get("LEDGER_API_KEY")
    if not api_key:
        raise ToolError("LEDGER_API_KEY is not set")
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as client:
            response = await client.request(
                method, path, headers={"Authorization": f"Bearer {api_key}"}, **kwargs
            )
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the Ledger API at {API_URL}: {exc!r}")
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ToolError(f"Ledger API error {response.status_code}: {detail}")
    return response.json()


@mcp.tool()
async def check_balance(account_id: int | None = None) -> dict:
    """Get the balance of one of your accounts.

    account_id may be omitted only if you have exactly one account.
    """
    params = {} if account_id is None else {"account_id": account_id}
    return await _call("GET", "/accounts/check-balance", params=params)


@mcp.tool()
async def transfer(
    from_account_id: int,
    to_account_number: str,
    amount: int,
    idempotency_key: str | None = None,
) -> dict:
    """Transfer money from one of your accounts to another account.

    The destination is identified by its account number. Both accounts must
    use the same currency. If idempotency_key is omitted a new one is generated
    and returned; to retry a failed or uncertain call, pass the same key again.
    """
    key = idempotency_key or str(uuid4())
    transaction = await _call(
        "POST",
        "/accounts/transfer",
        json={
            "from_account_id": from_account_id,
            "to_account_number": to_account_number,
            "amount": amount,
            "idempotency_key": key,
        },
    )
    return {"idempotency_key": key, **transaction}


if __name__ == "__main__":
    mcp.run("stdio")
