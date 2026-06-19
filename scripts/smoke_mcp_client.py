"""End-to-end MCP test: spawn the server over stdio and drive it via the MCP protocol.

Proves the server is a real, installable MCP (initialize -> list tools -> call tool),
not just a set of callable functions.

Run from the repo root:  uv run python scripts/smoke_mcp_client.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from server.compute.pob_code import encode_code  # noqa: E402
from server.compute.engine import PobEngine  # noqa: E402


def _make_import_code() -> str:
    """Produce a real PoB import code (Fireball) to feed the server."""
    with PobEngine() as eng:
        eng.new_build()
        eng.paste_skill("Fireball 20/0  1")
        return encode_code(eng.get_xml())


async def main() -> int:
    code = _make_import_code()

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.main"],
        cwd=str(REPO_ROOT),
        env=dict(os.environ),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("server         :", init.serverInfo.name, init.serverInfo.version)

            tools = await session.list_tools()
            print("tools          :", [t.name for t in tools.tools])

            health = await session.call_tool("engine_health", {})
            print("engine_health  :", _text(health))

            imported = await session.call_tool("import_build", {"source": code})
            print("import_build   :", _text(imported))

            stats = await session.call_tool(
                "get_build_stats", {"keys": ["TotalDPS", "Life", "Mana"]}
            )
            print("get_build_stats:", _text(stats))

            # corpus tools over the protocol
            gem = await session.call_tool("get_gem", {"name_or_id": "Fireball"})
            print("get_gem        :", _text(gem)[:220])
            skills = await session.call_tool(
                "find_skills", {"query": "fire", "gem_type": "active", "limit": 5}
            )
            print("find_skills    :", _text(skills)[:220])

    print("\nMCP CLIENT SMOKE OK")
    return 0


def _text(result: object) -> str:
    content = getattr(result, "content", None)
    if not content:
        return str(result)
    parts = [getattr(block, "text", str(block)) for block in content]
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
