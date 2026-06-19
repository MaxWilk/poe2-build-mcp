"""poe2-build-mcp MCP server.

v1 in progress. Currently exposes the compute layer (import + faithful stats from the
headless Path of Building engine). Corpus/search and live-ops tools land in later milestones.
"""

from __future__ import annotations

import threading
from typing import Any

from mcp.server.fastmcp import FastMCP

from .compute.engine import PobEngine
from .compute.pob_code import decode_code, is_link, to_xml
from .knowledge import db as corpus
from .live import prices as live_prices
from .live import update as live_update
from .live import version as live_version

mcp = FastMCP("poe2-build-mcp")

_engine: PobEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> PobEngine:
    """Return the shared headless engine, (re)starting it if needed."""
    global _engine
    with _engine_lock:
        if _engine is None or _engine.proc.poll() is not None:
            _engine = PobEngine()
        return _engine


def _reset_engine() -> None:
    """Close the shared engine so the next call respawns it (e.g. after an update)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.close()
            _engine = None


def _source_to_xml(source: str) -> str:
    """Normalize a user-supplied build source (code / link / raw XML) to PoB XML."""
    src = (source or "").strip()
    if not src:
        raise ValueError("empty build source")
    if is_link(src):
        return to_xml(src)
    if "PathOfBuilding" in src and "<" in src:
        return src  # already raw PoB XML
    return decode_code(src)  # otherwise assume a PoB import/share code


@mcp.tool()
def import_build(source: str) -> dict[str, Any]:
    """Import a Path of Exile 2 build for analysis and theorycrafting.

    `source` may be a Path of Building import/share code, a pobb.in or pastebin link, or
    raw PoB XML. Returns the selected main skill and a summary of engine-computed stats.
    The imported build becomes the active build for subsequent tool calls.
    """
    return get_engine().load_build_xml(_source_to_xml(source))


@mcp.tool()
def get_build_stats(keys: list[str] | None = None) -> dict[str, Any]:
    """Return Path-of-Building-computed stats for the currently loaded build.

    Pass `keys` to request specific stats (e.g. ["TotalDPS", "Life", "EnergyShield"]);
    omit it for a default summary. Every value is computed by the real PoB engine.
    """
    return get_engine().get_stats(keys)


@mcp.tool()
def set_class(class_name: str, ascendancy: str | None = None) -> dict[str, Any]:
    """Set the active build's character class and (optionally) ascendancy from scratch.

    `class_name` is a base class (e.g. "Mercenary", "Witch", "Ranger"); `ascendancy` is one of
    its ascendancies (e.g. "Witchhunter"). This re-roots the passive tree at that class's start,
    so subsequent passive search/allocate/optimize operate on the correct class. Returns stats.
    """
    return get_engine().set_class(class_name, ascendancy=ascendancy)


@mcp.tool()
def set_level(level: int) -> dict[str, Any]:
    """Set the active build's character level (1-100). Returns updated stats."""
    return get_engine().set_level(level)


@mcp.tool()
def set_skill(skill: str) -> dict[str, Any]:
    """Set the active build's main skill using Path of Building's paste format.

    Format: "<Gem Name> <level>/<quality>  <count>", e.g. "Fireball 20/0  1". Multiple
    gems (a skill + its supports) can be newline-separated. Returns updated stats.
    """
    return get_engine().paste_skill(skill)


@mcp.tool()
def set_config(
    options: dict[str, Any] | None = None, custom_mods: str | None = None
) -> dict[str, Any]:
    """Set combat/configuration options and/or extra modifiers on the active build.

    `options` are Path of Building config keys, e.g. {"enemyIsBoss": "Boss"},
    {"usePowerCharges": true}. `custom_mods` is free-form modifier text applied to the
    character, e.g. "100% increased Fire Damage\\n+2 to Level of all Fire Skills".
    Recomputes and returns stats.
    """
    return get_engine().set_config(options=options, custom_mods=custom_mods)


@mcp.tool()
def equip_item(raw: str) -> dict[str, Any]:
    """Equip an item on the active build from raw Path of Building item text.

    The item is auto-slotted by its base type. Returns updated stats.
    """
    return get_engine().add_item(raw)


@mcp.tool()
def evaluate_build(goals: dict[str, Any]) -> dict[str, Any]:
    """Check the active build against named numeric goals.

    `goals` maps a stat to a constraint: a bare number (treated as a minimum) or an object
    like {"min": 500000, "max": 1000000}. Example:
    {"TotalDPS": {"min": 500000}, "Life": {"min": 5000}, "TotalEHP": 20000}.
    Returns per-goal pass/fail with actual values and an overall `pass`.
    """
    stats = get_engine().get_stats(list(goals.keys()))["stats"]
    results = []
    all_ok = True
    for stat, constraint in goals.items():
        lo = hi = None
        if isinstance(constraint, dict):
            lo, hi = constraint.get("min"), constraint.get("max")
        else:
            lo = constraint
        value = stats.get(stat)
        ok = (
            isinstance(value, (int, float))
            and (lo is None or value >= lo)
            and (hi is None or value <= hi)
        )
        all_ok = all_ok and ok
        results.append({"stat": stat, "value": value, "min": lo, "max": hi, "ok": ok})
    return {"pass": all_ok, "results": results}


@mcp.tool()
def compare_to(source: str, keys: list[str] | None = None) -> dict[str, Any]:
    """Compare the active build against another build (code/link/XML) without losing it.

    Snapshots the current build, loads `source` to read its stats, then restores the
    current build. Returns the current stats, the other build's stats, and per-stat deltas
    (other - current).
    """
    eng = get_engine()
    snapshot = eng.get_xml()
    current = eng.get_stats(keys)["stats"]
    try:
        eng.load_build_xml(_source_to_xml(source))
        other = eng.get_stats(keys)["stats"]
    finally:
        eng.load_build_xml(snapshot)
    delta = {
        k: other[k] - current[k]
        for k in current.keys() & other.keys()
        if isinstance(current[k], (int, float)) and isinstance(other[k], (int, float))
    }
    return {"current": current, "other": other, "delta": delta}


@mcp.tool()
def search_passives(
    query: str = "", node_type: str | None = None, limit: int = 30
) -> dict[str, Any]:
    """Search the active build's passive tree by node name or stat text.

    `node_type` filters by kind: "Notable", "Keystone", "Mastery", or "Normal" (small nodes).
    Returns nodes with their id, stats, whether they're allocated, and `pathDist` (points to
    reach from the current tree; absent if unreachable). Use the id with alloc/dealloc.
    """
    return get_engine().search_passives(query=query, node_type=node_type, limit=limit)


@mcp.tool()
def get_passive(node: str | int) -> dict[str, Any]:
    """Return a passive node's details by id (preferred) or exact name."""
    return get_engine().get_passive(node)


@mcp.tool()
def alloc_passive(node: str | int) -> dict[str, Any]:
    """Allocate a passive node (and the shortest path to it) by id or name.

    Returns points spent and the resulting stat deltas. Fails if the node isn't reachable
    from the currently allocated tree.
    """
    return get_engine().alloc_passive(node)


@mcp.tool()
def dealloc_passive(node: str | int) -> dict[str, Any]:
    """Deallocate a passive node (and nodes that depend on it) by id or name.

    Returns points freed and the resulting stat deltas.
    """
    return get_engine().dealloc_passive(node)


@mcp.tool()
def optimize_passives(
    metric: str = "TotalDPS", points: int = 3, node_type: str = "Notable", candidates: int = 50
) -> dict[str, Any]:
    """Greedily allocate passive points to maximize a stat on the active build.

    Spends up to `points` points, each step allocating the reachable node (and its path) that
    most improves `metric` (e.g. "TotalDPS", "Life", "TotalEHP"). `node_type` defaults to
    "Notable". Returns the chosen nodes with per-step gains and the start/final metric values.
    This is a bounded greedy search, not a guaranteed global optimum.
    """
    return get_engine().optimize_passives(
        metric=metric, points=points, node_type=node_type, candidates=candidates
    )


@mcp.tool()
def engine_health() -> dict[str, Any]:
    """Report headless calculation-engine status (LuaJIT version, liveness)."""
    return get_engine().ping()


# --------------------------------------------------------------------------------------
# Corpus / knowledge tools (bundled SQLite; no engine required)
# --------------------------------------------------------------------------------------
@mcp.tool()
def search_items(
    query: str = "", item_class: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Search Path of Exile 2 item bases by name/tags, optionally filtered by item class.

    Returns matching bases (name, item_class, drop_level, tags). Use `get_item` for full detail.
    """
    return corpus.search_items(query=query, item_class=item_class, limit=limit)


@mcp.tool()
def get_item(name_or_id: str) -> dict[str, Any] | None:
    """Return full data for a single item base by exact name or metadata id."""
    return corpus.get_item(name_or_id)


@mcp.tool()
def find_skills(
    query: str = "",
    gem_type: str | None = None,
    tag: str | None = None,
    color: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Find skill/support gems by text, tag, color, or type.

    `gem_type` is one of "active", "support", "spirit". `tag` filters by gem tag (e.g. "fire",
    "projectile", "minion"). `color` is "r"/"g"/"b". Returns gems with recommended supports.
    """
    return corpus.find_skills(query=query, gem_type=gem_type, tag=tag, color=color, limit=limit)


@mcp.tool()
def get_gem(name_or_id: str) -> dict[str, Any] | None:
    """Return full data for a single gem by name or id (tags, granted skills, supports, types)."""
    return corpus.get_gem(name_or_id)


@mcp.tool()
def list_ascendancies(character: str | None = None) -> list[dict[str, Any]]:
    """List Path of Exile 2 ascendancies, optionally filtered by base class."""
    return corpus.list_ascendancies(character=character)


@mcp.tool()
def search_mods(
    query: str = "", item_tag: str | None = None, mod_type: str | None = None, limit: int = 30
) -> list[dict[str, Any]]:
    """Search Path of Exile 2 affixes/modifiers by readable text.

    `item_tag` filters by what the mod can roll on (e.g. "ring", "amulet", "body_armour");
    `mod_type` is "prefix" or "suffix". Returns mod text, type, required level, and rolls-on tags.
    """
    return corpus.search_mods(query=query, item_tag=item_tag, mod_type=mod_type, limit=limit)


@mcp.tool()
def reverse_lookup(stat: str, limit: int = 30) -> dict[str, Any]:
    """Find where a stat comes from: matching affixes, gems, and unique items.

    Example: reverse_lookup("maximum life") or reverse_lookup("increased fire damage").
    """
    return corpus.reverse_lookup(stat, limit=limit)


@mcp.tool()
def search_uniques(
    query: str = "", item_type: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Search Path of Exile 2 unique items by name, base, or mod text.

    `item_type` filters by slot family (e.g. "ring", "body", "bow"). Use `get_unique` for full text.
    """
    return corpus.search_uniques(query=query, item_type=item_type, limit=limit)


@mcp.tool()
def get_unique(name: str) -> dict[str, Any] | None:
    """Return a unique item's full readable text (base, mods) by name."""
    return corpus.get_unique(name)


@mcp.tool()
def corpus_info() -> dict[str, Any]:
    """Report the bundled game-data corpus version and entity counts."""
    return corpus.corpus_info()


# --------------------------------------------------------------------------------------
# Live ops (network: prices, data freshness, corpus updates)
# --------------------------------------------------------------------------------------
@mcp.tool()
def get_prices(
    query: str = "",
    kind: str = "currency",
    category: str | None = None,
    league: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Look up live Path of Exile 2 market prices (poe2scout.com).

    `kind` is "currency" or "unique". `query` filters by name (e.g. "divine", "mageblood").
    Defaults to the current challenge league; prices are in the league's base currency.
    """
    return live_prices.get_prices(
        query=query, kind=kind, category=category, league=league, limit=limit
    )


@mcp.tool()
def list_price_leagues() -> list[dict[str, Any]]:
    """List Path of Exile 2 leagues available for pricing (with the current one flagged)."""
    return live_prices.list_leagues()


@mcp.tool()
def check_data_version() -> dict[str, Any]:
    """Compare the bundled game-data corpus against upstream and report the current league."""
    return live_version.check_data_version()


@mcp.tool()
def update_corpus(rebuild_from_source: bool = False) -> dict[str, Any]:
    """Rebuild the game-data corpus locally from RePoE (power-user / offline path).

    Most users don't need this — the server auto-updates from validated releases. Pass
    rebuild_from_source=true to re-fetch RePoE and rebuild the corpus right now.
    """
    return live_version.update_corpus(rebuild_from_source=rebuild_from_source)


@mcp.tool()
def check_for_updates() -> dict[str, Any]:
    """Check whether a newer validated release (engine + corpus) is available to install."""
    return live_update.check_for_updates()


@mcp.tool()
def apply_updates() -> dict[str, Any]:
    """Download and install the latest validated release (engine + corpus) now."""
    # Close the engine first so it doesn't hold a cwd lock on the files being replaced
    # (matters on Windows when re-updating an engine already installed in user-data).
    _reset_engine()
    return live_update.apply_updates()


def main() -> None:
    # Best-effort, throttled auto-update in the background; never blocks startup.
    threading.Thread(target=live_update.auto_update, args=(_reset_engine,), daemon=True).start()
    mcp.run()


if __name__ == "__main__":
    main()
