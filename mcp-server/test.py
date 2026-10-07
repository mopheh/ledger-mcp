import asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
YOUR_API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0IiwiZXhwIjoxNzkwMzk5MjcyfQ.naO9vn2cynF4flS4rONRkkX2bmAMAjd1-G3SJCXag7Q"  # Replace
async def main():
    # Create a FastMCP client with the streamable-http transport
    transport = StreamableHttpTransport(url="http://localhost:8080/mcp", headers={"Authorization": f"Bearer {YOUR_API_TOKEN}"})

    async with Client(transport=transport) as client:
        result = await client.call_tool("check_balance", {})
        print("Balance:", result)


asyncio.run(main())