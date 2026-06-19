"""Server-surface tests: the assistant-facing cohesion layer (instructions + prompts).

These guard the MCP `instructions` channel and the workflow prompts — the only guidance the
LLM client receives beyond per-tool docstrings. They run without booting the engine.
"""

from __future__ import annotations

import asyncio

from server.main import mcp


def test_instructions_are_delivered():
    instr = mcp.instructions or ""
    # Sourced from server/ASSISTANT_GUIDE.md; must actually reach the client, not be empty.
    assert len(instr) > 500
    assert "Path of Exile 2" in instr
    # The cardinal rule has to survive — it's why answers stay grounded in the engine.
    assert "never" in instr.lower() and "engine" in instr.lower()


def test_workflow_prompts_registered():
    prompts = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert {"analyze_build", "build_from_goal", "audit_defenses"} <= prompts


def test_tool_surface_intact():
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 38


def test_server_version_matches_manifest():
    import json

    from server import paths
    from server.main import _server_version

    expected = json.loads((paths.BUNDLE_ROOT / "manifest.json").read_text())["version"]
    assert _server_version() == expected
