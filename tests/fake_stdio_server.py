from __future__ import annotations

import asyncio
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


async def main() -> None:
    server = Server("iron-test-stdio")

    @server.list_tools()
    async def _tools() -> list[Tool]:
        return [
            Tool(
                name="ping",
                description="reply with pong",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    @server.call_tool()
    async def _call(name: str, args: dict[str, Any]) -> list[TextContent]:
        if name == "ping":
            return [TextContent(type="text", text="pong")]
        raise ValueError(f"unknown tool {name}")

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
