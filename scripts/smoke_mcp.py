"""Smoke test for the MCP tool layer (calls the tool functions directly, no transport).

Run from the repo root:  uv run python scripts/smoke_mcp.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.compute.pob_code import encode_code  # noqa: E402
from server.main import engine_health, get_build_stats, get_engine, import_build  # noqa: E402


def main() -> int:
    print("engine_health:", engine_health())

    # Produce a real import code from the engine, then drive the import_build tool with it.
    eng = get_engine()
    eng.new_build()
    eng.paste_skill("Fireball 20/0  1")
    code = encode_code(eng.get_xml())

    res = import_build(code)
    print("import_build :", res["mainSkill"])

    stats = get_build_stats(["TotalDPS", "AverageDamage", "Life", "Mana", "ManaCost"])
    print("get_build_stats:", stats["stats"])

    assert stats["stats"].get("TotalDPS"), "expected non-zero TotalDPS via MCP tools"
    print("\nMCP TOOLS SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
