import asyncio
import os
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8080/mcp")
TOKEN = os.environ["LEDGER_TOKEN"]

async def main():
    transport = StreamableHttpTransport(
        url=MCP_URL,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    async with Client(transport=transport) as client:
        print(await client.list_tools())
        print("Balance:", await client.call_tool("check_balance", {}))

asyncio.run(main())