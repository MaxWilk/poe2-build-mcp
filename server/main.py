"""poe2-build-mcp MCP server.

Exposes the full v1 surface: the compute layer (import + Path-of-Building-faithful stats,
passives, mutation, optimize), the offline knowledge corpus (items/skills/mods/uniques/
passives/mechanics search), and live ops (prices, data-version, self-update). Tool
implementations live in the layer packages; this module registers them and ships the
assistant-facing operating guide via the MCP `instructions` channel.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import paths
from . import scaffold
from .compute.engine import PobEngine
from .compute import solver
from .compute.pob_code import PobCodeError, decode_code, encode_code, is_link, to_xml
from .knowledge import advice
from .knowledge import db as corpus
from .knowledge import itemparse
from .knowledge import mechanics
from .live import meta as live_meta
from .live import prices as live_prices
from .live import update as live_update
from .live import version as live_version
from .live import wiki as live_wiki

# Operating guide handed to the LLM client (surfaced as "MCP Server Instructions").
# Sourced from a bundled markdown file so it's both human-editable and actually delivered;
# falls back to a one-liner if the file is ever missing so the server never fails to boot.
_GUIDE = Path(__file__).with_name("ASSISTANT_GUIDE.md")
try:
    _INSTRUCTIONS: str | None = _GUIDE.read_text(encoding="utf-8")
except OSError:
    _INSTRUCTIONS = (
        "Path of Exile 2 build toolset: an offline knowledge corpus plus a Path of Building "
        "compute engine. Every build number must come from a compute tool — never invent DPS, "
        "EHP, or resistances. One active build persists across calls."
    )

mcp = FastMCP("poe2-build-mcp", instructions=_INSTRUCTIONS)

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
    """Normalize a user-supplied build source (code / link / raw XML / local file) to PoB XML."""
    src = (source or "").strip()
    if not src:
        raise ValueError("empty build source")
    # A local PoB export file (XML or a saved share code), e.g. a path into PoB's Builds folder.
    if len(src) < 500 and "\n" not in src and Path(src).expanduser().is_file():
        src = Path(src).expanduser().read_text(encoding="utf-8").strip()
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
    try:
        xml = _source_to_xml(source)
    except (PobCodeError, ValueError) as e:
        return {"ok": False, "error": f"Could not read that build source: {e}"}
    return get_engine().load_build_xml(xml)


@mcp.tool()
def get_build_stats(keys: list[str] | None = None) -> dict[str, Any]:
    """Return Path-of-Building-computed stats for the currently loaded build.

    Pass `keys` to request specific stats (e.g. ["TotalDPS", "Life", "EnergyShield"]);
    omit it for a default summary. Every value is computed by the real PoB engine.
    """
    return get_engine().get_stats(keys)


@mcp.tool()
def get_build() -> dict[str, Any]:
    """Full read-back of the active build.

    Returns class/level/ascendancy, the main skill group (gems + levels), allocated
    notables/keystones/ascendancy nodes, equipped gear by slot, passive points used, and
    summary stats — so you can see the whole build you've assembled.
    """
    return get_engine().get_build()


@mcp.tool()
def get_defenses() -> dict[str, Any]:
    """Defensive summary for the active build: life/ES/mana/ward, armour/evasion, block,
    elemental + chaos resistances (with over-cap), and TotalEHP. Elemental resists are shown
    net of PoB's configurable area penalty (default Endgame -60%); the response includes the
    active `resistPenalty` and a note. Cap is 75%; aim at or just over it.
    """
    return get_engine().get_defenses()


@mcp.tool()
def export_build() -> dict[str, Any]:
    """Export the active build as a Path of Building import code.

    Paste the returned `code` into Path of Building (Import/Export → Import) or share it.
    """
    return {"code": encode_code(get_engine().get_xml())}


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
def list_config_options(query: str = "", limit: int = 60) -> dict[str, Any]:
    """List Path of Building configuration options usable with `set_config`.

    Covers combat conditions, charges, enemy settings, exposure, etc. Filter with `query`
    (matches the option's key or label), e.g. "boss", "charge", "exposure". Returns each
    option's `var` (the key for set_config), `type`, `label`, and valid `values` for dropdowns.
    """
    return get_engine().list_config_options(query=query, limit=limit)


@mcp.tool()
def equip_item(raw: str, slot: str | None = None) -> dict[str, Any]:
    """Equip an item on the active build from raw Path of Building item text.

    Replaces whatever is currently in the target slot. `slot` optionally forces the slot
    (e.g. "Ring 2", "Weapon 2"); otherwise the item's primary slot is used. Returns updated stats.
    """
    return get_engine().add_item(raw, slot=slot)


@mcp.tool()
def unequip_item(slot: str) -> dict[str, Any]:
    """Clear an equipment slot on the active build (e.g. "Ring 2", "Body Armour", "Weapon 1")."""
    return get_engine().unequip_item(slot)


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
    try:
        other_xml = _source_to_xml(source)
    except (PobCodeError, ValueError) as e:
        return {"ok": False, "error": f"Could not read the comparison build: {e}"}
    eng = get_engine()
    snapshot = eng.get_xml()
    current = eng.get_stats(keys)["stats"]
    try:
        eng.load_build_xml(other_xml)
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
def solve_for(metric: str, target: float, lever: str, tolerance: float = 0.01) -> dict[str, Any]:
    """Solve for the magnitude of one modifier needed to reach a stat target on the active build.

    Holds the build fixed and binary-searches `lever` until `metric` reaches `target` — every
    probe is a real engine evaluation, so the answer is computed, not estimated. Example:
    `solve_for("TotalDPS", 1000000, "increased fire damage")` →
    "you need ≈ +N% increased Fire Damage."

    `lever` is a named lever (e.g. "increased fire damage", "attack speed", "maximum life",
    "increased critical strike chance") or a raw custom-mod template containing "{}" for the
    magnitude (e.g. "+{} to Level of all Fire Skills"). Returns the required magnitude, or flags
    the target unreachable with the best achievable value (and `alreadyMet` if you're past it).

    Scope: ONE lever, ONE (increasing) metric. It does not balance survivability or cost and
    reports a *requirement* — verify with get_defenses / evaluate_build and confirm the magnitude
    is attainable via search_mods / find_supports_for.
    """
    return solver.solve_for(
        get_engine(), metric=metric, target=target, lever=lever, tolerance=tolerance
    )


@mcp.tool()
def rank_levers(
    metric: str = "TotalDPS", unit: float = 10.0, levers: list[str] | None = None
) -> dict[str, Any]:
    """Rank which stat levers give the most `metric` per unit on the active build — the min/max
    direction-finder ("where do I invest next?").

    Applies each lever at `unit` (default 10 = "10%" or "+10") and measures the real Δmetric,
    ranked high→low — so you can see, e.g., that lightning penetration beats increased lightning
    damage for this build. Defaults to a broad damage+defense set; pass build-specific `levers`
    (custom-mod templates containing "{}", e.g. "{}% increased Lightning Damage", "Damage
    Penetrates {}% Lightning Resistance") for sharper guidance. Greedy/marginal — levers are
    measured independently, so verify combined picks (more-multiplier stacking, breakpoints)
    together. Every value is engine-computed; use it to direct gear/tree/support choices.
    """
    return solver.rank_levers(get_engine(), metric=metric, unit=unit, levers=levers)


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
    most improves `metric` (e.g. "TotalDPS", "Life", "TotalEHP"). Use `metric="balanced"` to
    raise offense AND defense together (scores nodes by relative TotalDPS + TotalEHP gain, so it
    won't glass-cannon) — it returns start/final DPS and EHP. Pass `points=0` to use the full
    remaining point budget at the character's current level (slower). `node_type` defaults to
    "Notable". Returns the chosen nodes with per-step gains. Bounded greedy search, not a
    guaranteed global optimum.
    """
    return get_engine().optimize_passives(
        metric=metric, points=points, node_type=node_type, candidates=candidates
    )


@mcp.tool()
def scaffold_gear(
    pool: str = "auto", target_resist: int = 75, slots: list[str] | None = None
) -> dict[str, Any]:
    """Fill the active build's EMPTY armour/jewellery slots with placeholder BASELINE gear.

    Closes the build's *actual* defensive gaps so a from-scratch skeleton becomes engine-
    evaluable: it adds only the resistances that are below `target_resist` (default 75 — a build
    already capping a resist gets none) and a hit pool. `pool` is "auto" (Energy Shield for an
    ES/CI build, else Life), "life", "energy_shield", or "none". `slots` limits which empty slots
    to fill (default all). The items are an explicit BASELINE — NOT the player's real gear and NOT
    optimal; the assistant still chooses the weapon and offense/identity gear (via equip_item).
    Use this to complete a build's defenses, then re-check with get_defenses / evaluate_build and
    price the real versions with get_prices — and never present scaffolded gear as finished.
    """
    return scaffold.scaffold_gear(get_engine(), pool=pool, target_resist=target_resist, slots=slots)


def _server_version() -> str:
    """The installed server (code) version, read from the bundled manifest."""
    try:
        return json.loads((paths.BUNDLE_ROOT / "manifest.json").read_text()).get(
            "version", "unknown"
        )
    except (OSError, ValueError):
        return "unknown"


@mcp.tool()
def engine_health() -> dict[str, Any]:
    """Report engine + install diagnostics: liveness, LuaJIT and passive-tree versions, the
    installed data/server versions, and whether data is served from the auto-updated user-data
    copy or the bundled seed — so you can confirm exactly what's running.
    """
    eng = get_engine()
    health = eng.ping()  # {pong, jit}
    info = getattr(eng, "info", {}) or {}
    from_user_data = (paths.user_data_dir() / "corpus.sqlite").exists()
    return {
        **health,
        "treeVersion": info.get("treeVersion"),
        "dataVersion": live_update.installed_version(),
        "serverVersion": _server_version(),
        "dataSource": "user-data" if from_user_data else "bundled",
    }


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
def find_supports_for(skill: str, limit: int = 25) -> dict[str, Any]:
    """Find support gems for a skill: its curated recommendations plus tag-compatible supports."""
    return corpus.find_supports_for(skill, limit=limit)


@mcp.tool()
def explain_mechanic(topic: str) -> dict[str, Any]:
    """Explain a Path of Exile 2 mechanic (corpus — offline, deterministic).

    Returns our evergreen `principle` (hand-authored) plus the matching auto-refreshed `wiki`
    page when one exists (attributed: PoE2 Wiki, CC BY-NC-SA 3.0 — cite it when you use it).
    Curated principle topics include: resistances, ailments, armour, evasion, energy_shield,
    spirit, critical_strike, ehp, accuracy, recovery. If nothing matches, use `search_mechanics`
    to browse, or `lookup_mechanic` to fetch a page live from the wiki.
    """
    return mechanics.explain(topic)


@mcp.tool()
def search_mechanics(query: str, limit: int = 8) -> dict[str, Any]:
    """Full-text search the bundled wiki mechanics tier (corpus — offline, deterministic).

    Returns matching page titles + snippets + source links so you can pick one to read with
    `explain_mechanic`. Wiki content is PoE2 Wiki, CC BY-NC-SA 3.0 — attribute it when quoting.
    For a page not bundled here, use `lookup_mechanic` (live wiki fetch).
    """
    results = corpus.search_mechanics(query, limit=limit)
    return {
        "query": query,
        "results": results,
        "note": "Bundled wiki mechanics (CC BY-NC-SA 3.0). Use explain_mechanic(title) to read "
        "one; lookup_mechanic(topic) to fetch a page not in the corpus.",
    }


@mcp.tool()
def relevant_mechanics() -> dict[str, Any]:
    """The mechanics worth understanding for the ACTIVE build (corpus + engine).

    Reads the current build's signals — main skill + its tags (and the ailment its damage type
    builds), keystones, ascendancy notables, plus staples — and points each at its best corpus
    mechanics page. Also surfaces the engine's damage diagnostic, so an uncomputable layer
    (reservation buff, undamageable minion, %-life/corpse detonation) is called out up front.
    Use it when starting/auditing a build to read up before theorycrafting.
    """
    eng = get_engine()
    build = eng.get_build()
    skill = build.get("mainSkill")
    tags: list[str] = []
    if skill:
        gem = corpus.get_gem(skill)
        if gem:
            tags = gem.get("tags") or []
    topics = mechanics.relevant(
        skill=skill,
        tags=tags,
        keystones=build.get("keystones") or [],
        ascendancy=build.get("ascendancyNotables") or [],
    )
    diagnostic = eng.get_stats(["TotalDPS"]).get("warning")
    return {
        "mainSkill": skill,
        "relevant": topics,
        "diagnostic": diagnostic,
        "note": "Read these with explain_mechanic(title); use lookup_mechanic for anything not "
        "listed. Wiki content is CC BY-NC-SA 3.0 — attribute it. If `diagnostic` is set, that "
        "damage layer isn't engine-computable — validate it in-game.",
    }


@mcp.tool()
def build_advice(topic: str = "") -> dict[str, Any]:
    """Evergreen PoE2 build-optimization principles — durable rules, not a meta snapshot.

    Omit `topic` for the framing + section list; pass a topic (e.g. "defense", "offense",
    "resistances", "crit", "spirit", "red flags") to get that section. These are *principles*
    for deciding what to change; the actual DPS/EHP numbers still come from the compute tools.
    """
    return advice.advise(topic)


@mcp.tool()
def parse_item(text: str) -> dict[str, Any]:
    """Parse a Path of Exile 2 item (in-game clipboard or PoB item text) and enrich it.

    For each explicit affix, identifies its mod group and the **tier it rolled (T1 = best)**
    using the corpus' per-tier ranges, and reports **open prefix/suffix slots** for craftable
    rarities. Use it to evaluate a drop or plan a craft ("is this worth using / can I add
    more?"). Tiers and ranges are looked-up corpus facts — to see how the item changes a build,
    equip it with `equip_item`. Affix detection is best-effort; unmatched lines come back under
    `unrecognized`.
    """
    return itemparse.parse_item(text)


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
def get_meta_builds(league: str | None = None, limit: int = 15) -> dict[str, Any]:
    """Live ascendancy popularity from poe.ninja's ladder snapshot — CONTEXT, not a target.

    Returns the most-played ascendancies for a league (default the current challenge league)
    with each one's share % and a rising/falling/flat trend, plus the sample size. This is
    *popularity among logged ladder characters, not a recommendation* — popular is not the same
    as optimal or right for the player's goal. Use it to inform, not dictate: build to the
    user's stated goal, and only steer toward the meta when they explicitly ask for the
    "strongest"/"popular"/"meta" option. Covers ascendancy distribution only (no skill/item
    meta). Returns {ok: false} if poe.ninja is unreachable.
    """
    try:
        return live_meta.get_meta_builds(league=league, limit=limit)
    except live_meta.MetaError as e:
        return {"ok": False, "error": f"meta data unavailable: {e}"}


@mcp.tool()
def lookup_mechanic(topic: str) -> dict[str, Any]:
    """Fetch a concise mechanic/skill/item explanation LIVE from the PoE2 Wiki (live — network).

    The long-tail escape hatch: use this only when `explain_mechanic`/`search_mechanics` don't
    have the topic in the bundled corpus. Returns a short lead extract + source link, attributed
    (PoE2 Wiki, CC BY-NC-SA 3.0 — cite it). Time-sensitive and may be outdated; the engine
    remains the source of truth for any number. Returns {available: false} if the wiki is
    unreachable. Single, user-triggered, read-only — it never sends your build anywhere.
    """
    return live_wiki.lookup_mechanic(topic)


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


# ---------------------------------------------------------------------------
# Prompts — ready-made workflow entry points the client can surface to users.
# Each returns guidance that steers the assistant through the right tool sequence;
# the actual numbers always come from the compute engine, never from the prompt.
# ---------------------------------------------------------------------------


@mcp.prompt()
def start_build_session(opening: str = "") -> str:
    """Start a Path of Exile 2 build session — orients the assistant to drive the poe2-build tools."""
    tail = f"\n\nThe player's opening request:\n{opening}" if opening.strip() else ""
    return (
        "You're now in a Path of Exile 2 build session. Use the poe2-build tools as the source of "
        "truth for this whole conversation: every DPS / EHP / resistance / defense figure must come "
        "from the compute engine (e.g. get_build_stats, get_defenses, compare_to, solve_for) — don't "
        "answer build math from memory, and lean on build_advice / explain_mechanic for principles "
        "and mechanics.\n\n"
        "What you can do here:\n"
        "- Analyze a build: import_build (a PoB code, pobb.in/pastebin link, or XML), then get_build "
        "/ get_defenses / get_build_stats, and suggest engine-validated improvements.\n"
        "- Build from scratch: set_class → set_level → set_skill (find_supports_for for supports) → "
        "optimize_passives / alloc_passive → equip_item, validating each step on the engine.\n"
        "- Solve toward a goal: solve_for, evaluate_build, optimize_passives.\n"
        "- Look things up: items, gems, mods, uniques, passives, ascendancies; check live prices.\n\n"
        "If the player hasn't said what they want, ask whether they'd like to analyze an existing "
        "build, create one from a goal, or get advice — then go."
        f"{tail}"
    )


@mcp.prompt()
def analyze_build(source: str) -> str:
    """Import a PoB build and produce a grounded analysis with improvement ideas."""
    return (
        f"Import this Path of Exile 2 build and analyze it:\n\n{source}\n\n"
        "Steps: call import_build, then get_build, get_defenses, and get_build_stats to see "
        "where it stands. Identify the biggest weaknesses (offense, survivability, resist caps). "
        "Use the corpus (search_*, find_supports_for, explain_mechanic) to find concrete "
        "improvements, then VALIDATE each suggestion on the engine (mutate and re-read stats, "
        "or compare_to) before recommending it. Distinguish PoB-computed numbers from "
        "corpus facts, and never state a number the engine didn't produce."
    )


@mcp.prompt()
def build_from_goal(goal: str, character_class: str = "") -> str:
    """Create a verified build from a natural-language goal (create → validate → cost → present)."""
    cls = f" Start from the {character_class} class." if character_class else ""
    return (
        f"Create a Path of Exile 2 build for this goal:\n\n{goal}\n{cls}\n\n"
        "Follow create → validate → cost → present: set_class → set_level → set_skill (use "
        "find_supports_for for supports) → for an attack skill equip a weapon FIRST (equip_item) "
        "so DPS computes → allocate the tree (optimize_passives, including metric='balanced' to "
        "raise offense AND defense) → equip the weapon + offense/identity gear, then scaffold_gear "
        "to fill the remaining slots to capped resists + a real pool (replace it with real drops).\n\n"
        "A build is NOT done until it clears a real bar (see build_advice('targets')): resists "
        "capped, a full gear set, a meaningful hit pool, DPS that clears the player's content, and "
        "sustain. CONFIRM with get_defenses + evaluate_build against explicit goals; sanity-check "
        "with build_advice('red flags') and, if you have one, compare_to a known-good build. Check "
        "cost with get_prices and present with export_build. If the build is a partial skeleton or "
        "fails the goal, say so plainly — never present a draft or a failing build as finished."
    )


@mcp.prompt()
def audit_defenses() -> str:
    """Audit the active build's survivability and propose fixes."""
    return (
        "Audit the active build's defenses. Call get_defenses and report life/ES, EHP, and "
        "elemental + chaos resistances with over-cap. Remember PoB's default endgame resistance "
        "penalty makes fresh resists deeply negative — that's expected; the target is the 75% "
        "cap. Identify the weakest defensive layer and propose specific, engine-validated fixes "
        "(gear mods via search_mods, uniques, or passives), confirming each with the engine."
    )


def main() -> None:
    # Best-effort, throttled auto-update in the background; never blocks startup.
    threading.Thread(target=live_update.auto_update, args=(_reset_engine,), daemon=True).start()
    mcp.run()


if __name__ == "__main__":
    main()
