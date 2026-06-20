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
    assert {"start_build_session", "analyze_build", "build_from_goal", "audit_defenses"} <= prompts


def test_tool_surface_intact():
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 51


def test_equip_item_flags_illegal_affixes(monkeypatch):
    # The legality wiring: a body-armour "% maximum Mana" affix surfaces a warning (engine stubbed,
    # so this tests the corpus check + merge, not the calc).
    from server import main

    class _Stub:
        def add_item(self, raw, slot=None):
            return {"ok": True, "slot": slot or "Body Armour", "stats": {"TotalDPS": 1.0}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    raw = (
        "Rarity: Rare\nFantasy Plate\nSacramental Robe\n--------\n"
        "60% increased maximum Mana\n+40% to Fire Resistance"
    )
    res = main.equip_item(raw, slot="Body Armour")
    assert res.get("illegalAffixes")
    assert "Sacramental Robe" in (res.get("legalityWarning") or "")


def test_equip_item_clean_gear_has_no_warning(monkeypatch):
    from server import main

    class _Stub:
        def add_item(self, raw, slot=None):
            return {"ok": True, "slot": slot or "Ring 1", "stats": {}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    raw = (
        "Rarity: Rare\nGood Ring\nSapphire Ring\n--------\n"
        "+140 to maximum Mana\n+42% to Lightning Resistance"
    )
    res = main.equip_item(raw, slot="Ring 1")
    assert "illegalAffixes" not in res and "legalityWarning" not in res


def test_meta_builds_shape():
    # Network-free: exercise the league selection + formatting on a sample payload.
    from server.live import meta

    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "leagueUrl": "runesofaldur",
                "total": 124269,
                "statistics": [
                    {"class": "Martial Artist", "percentage": 24.5, "trend": 1},
                    {"class": "Spirit Walker", "percentage": 17.7, "trend": -1},
                ],
            },
            {"leagueName": "HC Runes of Aldur", "total": 5000, "statistics": []},
            {"leagueName": "Standard", "total": 999999, "statistics": []},
        ]
    }
    r = meta.shape(sample, limit=5)
    # defaults to the main softcore challenge league, not Standard/HC (despite Standard's total)
    assert r["ok"] and r["league"] == "Runes of Aldur" and r["sampleSize"] == 124269
    assert r["ascendancies"][0]["ascendancy"] == "Martial Artist"
    assert r["ascendancies"][0]["trend"] == "rising" and r["ascendancies"][1]["trend"] == "falling"
    assert meta.shape(sample, league="Standard")["league"] == "Standard"  # explicit override
    assert meta.shape(sample, league="Nope")["ok"] is False  # not found


def test_build_advice_sections():
    from server.knowledge import advice

    overview = advice.advise()
    assert overview["topics"]
    assert "engine" in overview["intro"].lower()  # framing: numbers come from the engine
    # the durable resistance-cap rule must survive in the defense section
    assert "75%" in advice.advise("defense")["text"]
    # fuzzy keyword match resolves a query that isn't a section title
    assert advice.advise("crit").get("topic")


def test_server_version_matches_manifest():
    import json

    from server import paths
    from server.main import _server_version

    expected = json.loads((paths.BUNDLE_ROOT / "manifest.json").read_text())["version"]
    assert _server_version() == expected
