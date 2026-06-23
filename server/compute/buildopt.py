"""Holistic whole-build optimizer (`optimize_build`) — archetype-seeded commit-and-max.

The greedy per-slot/per-node tools are each locally optimal but myopic: they won't over-commit a
multiplier (crit, +levels, attack speed) before it pays off, so a from-scratch build caps far below
what the same chassis can compute once the lever is present. This does the synthesis they can't —
it commits an archetype's dominant lever as a *structure* across tree + gear + jewels + supports and
searches the commitment space on the engine, keeping the best constraint-satisfying build.

It is pure orchestration of tested primitives — `optimize_passives` (reset/require/goals), `plan_gear`
(auto_base/min_ehp), `optimize_jewel`, `optimize_supports`, `optimize_item`, plus the reference set
(`refbuilds`) for seeding and `benchmark` for placement. It invents no number; every figure is the
engine's. It does NOT bypass the inherent ceilings: perfect gear needs crafting-system modelling and
the 1M trigger meta needs the upstream PoB calc — it reaches the *gear-quality* ceiling for the
archetype, and says so.

Unlike the read-only optimizers, this is a STATE tool: it leaves the best build LOADED in the session
(so you can export_build / get_build / tweak from there) and reports what it committed + the
reference-set placement so the choice is transparent, not a black box.
"""

from __future__ import annotations

import concurrent.futures as cf
import re
from typing import Any

from ..knowledge import db as corpus
from ..knowledge import refbuilds
from . import craftopt, itemopt, supportopt
from .engine import PobEngine

_RES_KEYS = ("fire", "cold", "lightning")
_DAMAGE = {"fire", "cold", "lightning", "chaos", "physical"}
_DELIVERY = (
    "attack",
    "spell",
    "projectile",
    "melee",
    "minion",
    "totem",
    "trap",
    "mine",
    "brand",
    "slam",
    "channelling",
    "area",
)
# Jewel base by the build's dominant attribute (Diamond = all-attribute, the safe default).
_JEWEL_BASE = {"str": "Ruby", "dex": "Emerald", "int": "Sapphire"}
# Unique-pass target slots (gear only; jewels go through sockets, weapons are archetype-defining).
_UNIQUE_SLOTS = {
    "helmet": "Helmet",
    "body": "Body Armour",
    "gloves": "Gloves",
    "boots": "Boots",
    "belt": "Belt",
    "amulet": "Amulet",
    "ring": "Ring 1",
}


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _r2(x: Any) -> Any:
    return round(x, 2) if _num(x) else x


def _gem_tags(engine: PobEngine) -> set[str]:
    skill = str(engine.get_build().get("mainSkill") or "")
    gem = corpus.get_gem(skill) if skill else None
    return set(gem["tags"]) if gem and isinstance(gem.get("tags"), list) else set()


def _delivery_tags(engine: PobEngine) -> list[str]:
    tags = _gem_tags(engine)
    return [t for t in _DELIVERY if t in tags]


def _damage_types(engine: PobEngine) -> list[str]:
    tags = _gem_tags(engine)
    return [t for t in ("lightning", "fire", "cold", "chaos", "physical") if t in tags]


def _attr_bias(engine: PobEngine) -> str:
    st = engine.get_stats(["Str", "Dex", "Int"]).get("stats") or {}
    by = {"str": st.get("Str") or 0, "dex": st.get("Dex") or 0, "int": st.get("Int") or 0}
    return max(by, key=lambda k: by[k])


# Attribute levers — normally a dead stat for a build, but a unique-ENABLED archetype (e.g. Hand of
# Wisdom and Action: "lightning per N Intelligence") turns an attribute INTO the damage multiplier.
# Committing it stacks the attribute on tree+gear+jewels so the unique snowballs it into damage.
_ATTR_LEVERS = {
    "int": "Int",
    "intelligence": "Int",
    "str": "Str",
    "strength": "Str",
    "dex": "Dex",
    "dexterity": "Dex",
}
_ATTR_TREE_QUERY = {"Int": "intelligence", "Str": "strength", "Dex": "dexterity"}


def _attr_stat(lever: str | None) -> str | None:
    """The engine attribute stat ('Int'/'Str'/'Dex') an attribute lever stacks, else None."""
    return _ATTR_LEVERS.get(lever.lower()) if lever else None


def _lever_tree_query(lever: str, damage_types: list[str]) -> str | None:
    """Map a reference `topLevers` name -> a passive-tree search query whose top notables we REQUIRE
    (the seed over-commitment). None = a gear/gem-driven lever (e.g. +levels) with no special tree
    cluster — handled by optimizing gear/supports for the metric (≈ the balanced pass)."""
    low = lever.lower()
    attr = _attr_stat(lever)
    if attr:
        return _ATTR_TREE_QUERY[attr]  # stack the attribute's tree clusters (the bootstrap)
    if "crit" in low or "critical" in low:
        return "critical"
    if "attack speed" in low:
        return "attack speed"
    if "cast speed" in low:
        return "cast speed"
    if "penetrat" in low or "exposure" in low:
        return (damage_types[0] + " penetration") if damage_types else "penetration"
    if "more damage" in low or ("increased" in low and "damage" in low):
        return (damage_types[0] + " damage") if damage_types else "damage"
    return None


def _require_tree_nodes(engine: PobEngine, query: str, top: int = 2) -> list[int]:
    """Up to `top` reachable notable ids for `query` — search_passives already orders by relevance
    then nearest pathDist, so the head is the most relevant, cheapest-to-path cluster."""
    r = engine.search_passives(query=query, node_type="Notable", limit=12)
    out: list[int] = []
    for n in r.get("nodes") or r.get("results") or []:
        if n.get("alloc"):
            continue
        if not _num(n.get("pathDist")):
            continue
        nid = n.get("id")
        if _num(nid):
            out.append(int(nid))
        if len(out) >= top:
            break
    return out


def _near_jewel_sockets(engine: PobEngine, n: int) -> list[int]:
    """The `n` nearest UNALLOCATED jewel sockets (by pathDist) — requiring far ones wastes the point
    budget that should go to damage, so we sort nearest-first and cap."""
    if n <= 0:
        return []
    socks = engine.list_jewel_sockets().get("sockets") or []
    cands: list[tuple[float, int]] = []
    for s in socks:
        if s.get("allocated"):
            continue
        sid = s.get("socket")
        if not _num(sid):
            continue
        info = engine.get_passive(int(sid))
        node = info.get("node") if isinstance(info.get("node"), dict) else info
        pd = node.get("pathDist") if isinstance(node, dict) else None
        if isinstance(pd, (int, float)) and not isinstance(pd, bool):
            cands.append((float(pd), int(sid)))
    cands.sort()
    return [sid for _, sid in cands[:n]]


def _result(engine: PobEngine, metric: str, min_ehp: float | None) -> dict[str, Any]:
    """Whole-build snapshot for ranking: the metric + defensive constraint flags."""
    st = engine.get_stats(["TotalDPS", "FullDPS"]).get("stats") or {}
    d = engine.get_defenses() or {}
    missing = d.get("resistMissing") or {}
    res_capped = all((missing.get(e) or 0) <= 0 for e in _RES_KEYS)
    ehp = d.get("totalEHP")
    ehp_ok = (ehp or 0) >= min_ehp if min_ehp else True
    val = st.get(metric)
    if not _num(val):
        val = st.get("TotalDPS")
    score = float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else 0.0
    return {
        "metricValue": _r2(val),
        "TotalDPS": _r2(st.get("TotalDPS")),
        "FullDPS": _r2(st.get("FullDPS")),
        "TotalEHP": _r2(ehp),
        "resistsCapped": res_capped,
        "ehpFloorMet": ehp_ok,
        "constraintsMet": bool(res_capped and ehp_ok),
        "score": score,
    }


def _equip_plan(engine: PobEngine, plan: list[dict[str, Any]]) -> None:
    for p in plan:
        item, slot = p.get("item"), p.get("slot")
        if item and slot:
            engine.add_item(item, slot=slot)


def _craft_weapon(engine: PobEngine, metric: str) -> None:
    """Polish the main-hand to pure metric (the single biggest lever) — plan_gear leaves weapons
    blended; this maxes them. No-op if the slot has no base."""
    r = itemopt.optimize_item(engine, "Weapon 1", metric=metric, thorough=True)
    if r.get("ok") and r.get("item"):
        engine.add_item(r["item"], slot="Weapon 1")


def _fill_jewels(engine: PobEngine, metric: str, base: str) -> int:
    """Socket every ALLOCATED jewel socket with its best metric-raising rare jewel. Re-optimizes
    filled sockets too, so a later pass improves them on the now-stronger build. Returns count."""
    socks = engine.list_jewel_sockets().get("sockets") or []
    filled = 0
    for s in socks:
        if not s.get("allocated"):
            continue
        sid = s.get("socket")
        if not _num(sid):
            continue
        j = itemopt.optimize_jewel(engine, metric=metric, base=base)
        if j.get("ok") and j.get("item"):
            engine.equip_jewel(j["item"], socket=int(sid))
            filled += 1
    return filled


def _apply_supports(engine: PobEngine, metric: str) -> None:
    r = supportopt.optimize_supports(engine, metric=metric)
    if not r.get("ok"):
        return
    skill = r.get("skill")
    if not skill:
        return
    sup = r.get("supports") or []
    text = f"{skill} 20/20 1" + ("\n" + "\n".join(sup) if sup else "")
    engine.paste_skill(text)


def _unique_item_text(full: dict[str, Any]) -> str:
    """Build canonical PoB item text from a corpus unique. The stored `text` already leads with
    name/base (and sometimes a `League:` line) before the mods, so we take name/base from their own
    fields and keep only the mod lines — otherwise the name/base get duplicated into the mod block."""
    name = str(full.get("name") or "")
    base = str(full.get("base") or "")
    mods = [
        ln
        for ln in str(full.get("text") or "").splitlines()
        if ln.strip()
        and ln.strip() != name
        and ln.strip() != base
        and not ln.lower().startswith("league:")
    ]
    return f"Rarity: Unique\n{name}\n{base}\n--------\n" + "\n".join(mods)


def _unique_pass(engine: PobEngine, metric: str, min_ehp: float | None) -> list[dict[str, Any]]:
    """v2 — try the build-relevant uniques per gear slot: equip each, keep it only if it raises the
    metric without breaking the defensive constraints. Best-effort and bounded; a unique that ENABLES
    a mechanic (rather than just adding stats) won't always show its value here — those are flagged
    for manual review. Read-only per candidate (snapshot/restore), persists only kept upgrades."""
    skill = str(engine.get_build().get("mainSkill") or "")
    tags = _gem_tags(engine)
    keywords = sorted(
        (tags & _DAMAGE) | (tags & {"spell", "attack", "projectile", "minion", "melee", "area"})
    )
    if skill:
        keywords.append(skill)
    if not keywords:
        return []
    cands = corpus.relevant_uniques(keywords, limit=24)
    swapped: list[dict[str, Any]] = []
    base = _result(engine, metric, min_ehp)
    cur = base["score"]
    for u in cands:
        itype = str(u.get("item_type") or "").lower()
        slot = next((s for key, s in _UNIQUE_SLOTS.items() if key in itype), None)
        if not slot:
            continue
        full = corpus.get_unique(str(u.get("name") or ""))
        if not full or not full.get("text"):
            continue
        raw = _unique_item_text(full)
        snap = engine.get_xml()
        try:
            engine.add_item(raw, slot=slot)
            r = _result(engine, metric, min_ehp)
            keep = r["score"] > cur + 1e-9 and r["constraintsMet"] >= base["constraintsMet"]
        except Exception:
            keep = False
            r = base
        if keep:
            cur = r["score"]
            swapped.append(
                {"slot": slot, "unique": full.get("name"), "metricValue": r["metricValue"]}
            )
        else:
            engine.load_build_xml(snap)
    return swapped


def commit_and_max(
    engine: PobEngine,
    snapshot: str,
    levers: list[str],
    *,
    metric: str,
    min_ehp: float | None,
    passes: int,
    max_jewel_sockets: int,
    try_uniques: bool,
    damage_types: list[str],
    combat: dict[str, Any],
    kept_slots: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build the version that maximally commits the lever SET `levers` (empty = balanced) across
    tree+gear+jewels+supports, evaluated as the whole build. Starts fresh from `snapshot`. The
    over-commitment lives in REQUIRING every lever's tree clusters AT ONCE (which greedy won't take)
    + filling jewel sockets — so MULTIPLE multipliers (crit × attack-speed × penetration) compound
    instead of just one, then the metric-greedy gear/jewels/supports pile on, breaking the chicken-egg.

    A single ATTRIBUTE lever (Int/Str/Dex) is special: a unique-enabled archetype (e.g. HoWA: lightning
    per Int) makes the attribute the damage multiplier, but the greedy won't bootstrap it. So we stack
    the ATTRIBUTE itself on tree+gear+jewels — the equipped unique snowballs it into the real `metric`.
    `kept_slots` are build-defining uniques NOT to recraft."""
    engine.load_build_xml(snapshot)

    # A single attribute lever stacks the attribute itself; a damage stack uses the real metric and
    # over-commits every lever's clusters together so they compound.
    attr = _attr_stat(levers[0]) if len(levers) == 1 else None
    gear_metric = attr or metric

    require: list[str | int] = []
    seen_nodes: set[int] = set()
    for lev in levers:
        q = _lever_tree_query(lev, damage_types)
        if not q:
            continue
        for nid in _require_tree_nodes(engine, q):
            if nid not in seen_nodes:
                seen_nodes.add(nid)
                require.append(nid)
    require += _near_jewel_sockets(engine, max_jewel_sockets)

    # Tree goals: an attribute lever STACKS the attribute (the bootstrap the greedy won't climb); else
    # DPS, with a light EHP weight when a floor is set so the tree carries some defence (pinnacle ~20k).
    if attr:
        tree_goals: dict[str, float] | None = (
            {attr: 0.7, "TotalEHP": 0.3} if min_ehp else {attr: 1.0}
        )
    else:
        tree_goals = {"TotalDPS": 0.75, "TotalEHP": 0.25} if min_ehp else None
    tree = engine.optimize_passives(
        metric=metric, points=0, reset=True, require=require or None, goals=tree_goals
    )
    engine.set_config(options=combat)

    gear_slots = (
        [s for s in (*_CRAFT_OFFENSE, *_CRAFT_DEFENSE) if s not in kept_slots]
        if kept_slots
        else None
    )
    jewel_base = _JEWEL_BASE.get(_attr_bias(engine), "Diamond")
    jewels = 0
    for _ in range(max(1, passes)):
        plan = itemopt.plan_gear(
            engine, dps_weight=0.85, min_ehp=min_ehp, metric=gear_metric, slots=gear_slots
        )
        _equip_plan(engine, plan.get("plan") or [])
        if "Weapon 1" not in kept_slots:
            _craft_weapon(engine, metric)  # weapon chases the REAL metric (its flat damage matters)
        jewels = _fill_jewels(engine, gear_metric, jewel_base)
        _apply_supports(engine, metric)

    uniques: list[dict[str, Any]] = []
    if try_uniques:
        uniques = _unique_pass(engine, metric, min_ehp)

    res = _result(engine, metric, min_ehp)
    res["lever"] = " + ".join(levers) if levers else "balanced"
    res["treeRequired"] = require
    res["jewelsSocketed"] = jewels
    res["uniquesEquipped"] = uniques
    res["requireSkipped"] = tree.get("requireSkipped") or []
    res["xml"] = engine.get_xml()
    return res


def _setup_archetype(engine: PobEngine, base: str, arch: dict[str, Any]) -> str | None:
    """Produce a starting snapshot for a candidate archetype (v3 multi-archetype). `arch` keys:
    class, ascendancy, skill, weapon (full PoB item text for the main hand). Returns the snapshot
    XML, or None if it couldn't be set up."""
    try:
        engine.load_build_xml(base)
        if arch.get("class"):
            engine.set_class(str(arch["class"]), arch.get("ascendancy"))
        if arch.get("weapon"):
            engine.add_item(str(arch["weapon"]), slot="Weapon 1")
        if arch.get("skill"):
            engine.paste_skill(f"{arch['skill']} 20/20 1")
        return engine.get_xml()
    except Exception:
        return None


def _run_levers(
    engine: PobEngine,
    snapshot: str,
    lever_sets: list[list[str]],
    *,
    parallel: bool,
    max_workers: int,
    **kw: Any,
) -> list[dict[str, Any]]:
    """Run commit_and_max for each lever SET (a set commits several levers together). Sequential by
    default; with `parallel`, spread the sets across a small pool of independent engine subprocesses
    (each used by exactly one thread, so the sync stdio stays safe) — the real speedup."""
    if not parallel or len(lever_sets) <= 1:
        return [commit_and_max(engine, snapshot, ls, **kw) for ls in lever_sets]

    n = min(max(2, max_workers), len(lever_sets))
    extras = [PobEngine(script=engine.script) for _ in range(n - 1)]
    engines = [engine, *extras]
    chunks: list[list[list[str]]] = [lever_sets[i::n] for i in range(n)]

    def work(eng: PobEngine, chunk: list[list[str]]) -> list[dict[str, Any]]:
        return [commit_and_max(eng, snapshot, ls, **kw) for ls in chunk]

    try:
        with cf.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(work, engines[i], chunks[i]) for i in range(n)]
            out: list[dict[str, Any]] = []
            for f in futs:
                out += f.result()
        return out
    finally:
        for e in extras:
            e.close()


_CRAFT_OFFENSE = ("Weapon 1", "Amulet", "Gloves", "Ring 1", "Ring 2")
_CRAFT_DEFENSE = ("Body Armour", "Helmet", "Boots", "Belt", "Weapon 2")


def _resists_capped(engine: PobEngine) -> bool:
    missing = engine.get_defenses().get("resistMissing") or {}
    return all((missing.get(e) or 0) <= 0 for e in _RES_KEYS)


def _converge(
    engine: PobEngine,
    require: list[str | int] | None,
    *,
    metric: str,
    min_ehp: float | None,
    combat: dict[str, Any],
    kept_slots: tuple[str, ...] = (),
    passes: int = 2,
) -> dict[str, Any]:
    """Post-craft convergence — the fix for multipliers that bootstrap each other but get committed at
    DIFFERENT stages. Crafting reveals crit MULTI, but the tree was planned BEFORE crafting, so crit
    CHANCE never got committed (it stays low, the multi is wasted). And crit chance has its OWN
    bootstrap inside the tree — a crit wheel is many small nodes, each marginal until most of it is
    allocated — so a free re-plan won't climb it. So when we see high multi + low chance, we FORCE the
    crit clusters (+ re-craft so the weapon supplies local crit, + crit jewels/supports), re-measure,
    and keep only a strict constraint-satisfying gain. Verified to roughly DOUBLE a from-scratch
    Lightning Spear (the wasted 4.36x multi at 32.7% chance). Build is left LOADED at the best."""
    tree_goals = {"TotalDPS": 0.75, "TotalEHP": 0.25} if min_ehp else None
    jewel_base = _JEWEL_BASE.get(_attr_bias(engine), "Diamond")
    base_require = list(require or [])
    best_xml = engine.get_xml()
    best_res = _result(engine, metric, min_ehp)
    for _ in range(max(1, passes)):
        s = engine.get_stats(["CritChance", "CritMultiplier"]).get("stats") or {}
        # the dominant attack/spell under-stack: a big crit MULTI sitting on a low crit CHANCE.
        extra: list[str | int] = []
        if (s.get("CritMultiplier") or 0) >= 2.5 and (s.get("CritChance") or 0) < 80:
            extra = [
                n for n in _require_tree_nodes(engine, "critical", top=3) if n not in base_require
            ]
        if not extra:
            break  # nothing under-stacked left to force
        engine.optimize_passives(
            metric=metric, points=0, reset=True, require=base_require + extra, goals=tree_goals
        )
        engine.set_config(options=combat)
        _craft_gear(
            engine, metric, kept_slots
        )  # re-craft: the weapon now supplies local crit chance
        _fill_jewels(engine, metric, jewel_base)
        _apply_supports(engine, metric)
        res = _result(engine, metric, min_ehp)
        if res["score"] > best_res["score"] and res["constraintsMet"] >= best_res["constraintsMet"]:
            best_res, best_xml, base_require = res, engine.get_xml(), base_require + extra
        else:
            break
    engine.load_build_xml(best_xml)
    return best_res


def _craft_gear(
    engine: PobEngine, metric: str, kept_slots: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    """'Awesome gear' post-pass: re-craft every equipped gear slot with the FULL crafting system
    (runes + Perfect essences + corruption). Each slot keeps a resist/EHP weight (offense damage-heavy,
    defense EHP-heavy) so it doesn't strip its resistances, then a re-cap pass restores any cross-slot
    resist balance the per-slot crafting disturbed. Crafted on the live build so gains compound. Heavy.
    `kept_slots` (build-defining uniques) are left untouched — never recrafted into a rare."""
    gear = engine.get_build().get("gear") or {}
    craftable = [
        s
        for s, cur in gear.items()
        if isinstance(cur, dict) and cur.get("base") and "Jewel" not in s and s not in kept_slots
    ]
    crafted: dict[str, dict[str, Any]] = {}

    def do(slot: str, goals: dict[str, float]) -> None:
        r = craftopt.craft_item(engine, slot, goals=goals)
        if r.get("ok") and r.get("item"):
            engine.add_item(r["item"], slot=slot)
            c = r.get("crafting") or {}
            if c.get("runes") or c.get("essencesUsed") or c.get("corruptedImplicit"):
                crafted[slot] = {"slot": slot, **c}

    for slot in craftable:
        if slot in _CRAFT_OFFENSE:
            do(slot, {metric: 0.85, "TotalEHP": 0.15})  # keep resists/EHP, don't go pure-DPS
        else:
            do(slot, {"TotalEHP": 0.8, metric: 0.2})

    # Per-slot crafting can disturb plan_gear's cross-slot resist allocation; recraft defence slots
    # toward pure EHP (PoB's EHP heavily credits capped resists) until the build is capped again.
    if not _resists_capped(engine):
        for slot in [s for s in _CRAFT_DEFENSE if s in craftable]:
            if _resists_capped(engine):
                break
            do(slot, {"TotalEHP": 1.0})

    return list(crafted.values())


_CEILING_NOTE = (
    "Best found (engine-verified), not a global optimum. Reaches the gear-quality ceiling for this "
    "archetype — committed lever across tree + gear + jewels + supports. Pass crafting=true to also "
    "apply the full crafting system (runes + Perfect essences + corruption) to every slot. The one "
    "thing it CANNOT model is energy-meta TRIGGERS (e.g. Cast on Critical → Comet) — upstream PoB. "
    "Run apply_combat_profile with the conditions THIS build actually produces (shock/curse/charges) "
    "for the in-fight DPS, and validate_build before presenting."
)


def optimize_build(
    engine: PobEngine,
    *,
    metric: str = "TotalDPS",
    min_ehp: float | None = 20000,
    levers: list[str] | None = None,
    tier: str = "Pinnacle",
    passes: int = 2,
    max_jewel_sockets: int = 3,
    try_uniques: bool = False,
    crafting: bool = False,
    uniques: list[str] | None = None,
    converge: bool = False,
    combat: dict[str, Any] | None = None,
    archetypes: list[dict[str, Any]] | None = None,
    parallel: bool = False,
    max_workers: int = 3,
) -> dict[str, Any]:
    """Assemble a complete, verified, high-`metric` build for the ACTIVE archetype (class+ascendancy+
    skill+weapon already set) via archetype-seeded commit-and-max. Leaves the best build LOADED.

    `levers` auto-seeds from the reference set for the build's delivery when omitted; pass explicit
    reference lever names to force the search. `min_ehp` is the EHP floor (hard constraint, with
    resists-capped). `try_uniques` adds the v2 unique pass. `uniques` EQUIPS named build-defining
    uniques and PRESERVES them (never recrafted) — and if one scales damage off an attribute (e.g.
    HoWA: "per N Intelligence"), that attribute is auto-added as a lever so the search stacks it (a
    unique-enabled archetype the greedy can't otherwise reach). `archetypes` (v3) evaluates alternative
    class/skill/weapon configs too and keeps the best. `parallel` spreads the search across engine
    subprocesses. See the module docstring.
    """
    b = engine.get_build()
    skill = str(b.get("mainSkill") or "")
    if not skill:
        return {
            "ok": False,
            "error": "No active main skill — set_class + set_skill (or import a build) first.",
        }
    level = b.get("level")
    if isinstance(level, int) and level < 30:
        return {
            "ok": False,
            "error": f"Build is level {level} — too few passive points to optimize a tree (an empty "
            "tree gives a weak, misleading result). set_level to an endgame level (~90+) first, or "
            "import a real build.",
        }

    delivery = _delivery_tags(engine)
    damage_types = _damage_types(engine)
    if "attack" in delivery and not (b.get("gear") or {}).get("Weapon 1"):
        return {
            "ok": False,
            "error": "Attack skill with no main-hand weapon — equip a weapon base first (it's "
            "archetype-defining, so the optimizer won't pick it). Spell skills don't need one.",
        }

    # Minions / DoT / triggers deal damage the player doesn't "hit" for — TotalDPS reads ~0 while
    # FullDPS carries it. Optimizing the default TotalDPS would then optimize ZERO (a silent 0-DPS
    # build), so auto-switch to FullDPS when that's the real damage signal.
    metric_note: str | None = None
    if metric == "TotalDPS":
        bare = engine.get_stats(["TotalDPS", "FullDPS"]).get("stats") or {}
        if (bare.get("TotalDPS") or 0) < 1 and (bare.get("FullDPS") or 0) > 1:
            metric = "FullDPS"
            metric_note = (
                "auto-switched to metric=FullDPS (TotalDPS ~0 — a minion/DoT/trigger skill)"
            )

    # Equip + PRESERVE build-defining uniques, and auto-seed the attribute lever any of them ENABLES
    # (e.g. HoWA scales lightning off Intelligence → stack Int). Kept slots are never recrafted.
    kept_list: list[str] = []
    auto_levers: list[str] = []
    for name in uniques or []:
        full = corpus.get_unique(name)
        if not full or not full.get("text"):
            continue
        itype = str(full.get("item_type") or "").lower()
        uslot = next((s for key, s in _UNIQUE_SLOTS.items() if key in itype), None)
        if not uslot:
            continue
        engine.add_item(_unique_item_text(full), slot=uslot)
        kept_list.append(uslot)
        for attr_word in ("intelligence", "strength", "dexterity"):
            if re.search(rf"per\s+\d+\s+{attr_word}", str(full["text"]), re.I):
                auto_levers.append(attr_word)  # unique-enabled attribute archetype
    kept_slots = tuple(dict.fromkeys(kept_list))

    seeded = list(levers) if levers is not None else refbuilds.archetype_levers(delivery)
    seeded += [lv for lv in auto_levers if lv not in seeded]
    # Dedup seeded levers by tree-query (so "crit damage"/"crit chance" don't both run) and split
    # damage levers from attribute levers (attribute levers need their own attribute-stacking gear).
    damage_lv: list[str] = []
    attr_lv: list[str] = []
    seen_q: set[str] = set()
    for lev in seeded:
        q = _lever_tree_query(lev, damage_types)
        if q is None or q in seen_q:
            continue  # gear/gem-driven (≈ balanced) or duplicate cluster — skip the redundant run
        seen_q.add(q)
        (attr_lv if _attr_stat(lev) else damage_lv).append(lev)

    # Candidate SETS: balanced; each single damage lever; the STACKED set (all damage levers committed
    # together so their multipliers compound — the multi-lever commit); and each attribute lever solo.
    candidates: list[list[str]] = [[]]
    candidates += [[lv] for lv in damage_lv]
    if len(damage_lv) >= 2:
        candidates.append(list(damage_lv))  # the multi-lever stack
    candidates += [[lv] for lv in attr_lv]

    profile = combat or {"enemyIsBoss": tier, "conditionFullEnergyShield": True}
    snapshot = engine.get_xml()
    kw: dict[str, Any] = dict(
        metric=metric,
        min_ehp=min_ehp,
        passes=passes,
        max_jewel_sockets=max_jewel_sockets,
        try_uniques=try_uniques,
        damage_types=damage_types,
        combat=profile,
        kept_slots=kept_slots,
    )

    results = _run_levers(
        engine, snapshot, candidates, parallel=parallel, max_workers=max_workers, **kw
    )
    for r in results:
        r["archetype"] = "active"

    # v3 multi-archetype: evaluate each proposed config from the same base, keep all results.
    for arch in archetypes or []:
        arch_snap = _setup_archetype(engine, snapshot, arch)
        if arch_snap is None:
            continue
        ares = _run_levers(
            engine, arch_snap, candidates, parallel=parallel, max_workers=max_workers, **kw
        )
        label = arch.get("skill") or arch.get("ascendancy") or arch.get("class") or "archetype"
        for r in ares:
            r["archetype"] = str(label)
        results += ares

    if not results:
        return {"ok": False, "error": "Optimizer produced no candidate builds."}

    # Objective: best metric among constraint-satisfying builds; fall back to best metric + flag.
    satisfying = [r for r in results if r.get("constraintsMet")]
    best = max(satisfying or results, key=lambda r: r["score"])
    engine.load_build_xml(best["xml"])  # leave the winner loaded in the session

    # 'Awesome gear' post-pass: apply the full crafting system to the winner's gear, then re-measure.
    crafted_gear: list[dict[str, Any]] = []
    if crafting:
        crafted_gear = _craft_gear(engine, metric, kept_slots)
        post = _result(engine, metric, min_ehp)
        for k in ("TotalDPS", "FullDPS", "TotalEHP", "resistsCapped", "ehpFloorMet", "score"):
            best[k] = post[k]

    # Convergence: re-plan tree + jewels + supports on the (crafted) winner so synergistic multipliers
    # the earlier stages couldn't bootstrap (crit CHANCE once crafting supplied crit MULTI) get stacked.
    converged = False
    if converge:
        before = best.get("score") or 0
        c = _converge(
            engine,
            best.get("treeRequired") or None,
            metric=metric,
            min_ehp=min_ehp,
            combat=profile,
            kept_slots=kept_slots,
        )
        if (c.get("score") or 0) > before:
            converged = True
            for k in ("TotalDPS", "FullDPS", "TotalEHP", "resistsCapped", "ehpFloorMet", "score"):
                best[k] = c[k]

    bench = refbuilds.benchmark(
        best.get("TotalDPS"), best.get("FullDPS"), best.get("TotalEHP"), delivery
    )

    def _slim(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "lever": r.get("lever"),
            "archetype": r.get("archetype"),
            "metricValue": r.get("metricValue"),
            "TotalEHP": r.get("TotalEHP"),
            "constraintsMet": r.get("constraintsMet"),
            "jewelsSocketed": r.get("jewelsSocketed"),
        }

    return {
        "ok": True,
        "metric": metric,
        "metricNote": metric_note,
        "committed": best.get("lever"),
        "committedArchetype": best.get("archetype"),
        "result": {
            "TotalDPS": best.get("TotalDPS"),
            "FullDPS": best.get("FullDPS"),
            "TotalEHP": best.get("TotalEHP"),
            "resistsCapped": best.get("resistsCapped"),
            "ehpFloorMet": best.get("ehpFloorMet"),
            "jewelsSocketed": best.get("jewelsSocketed"),
            "uniquesEquipped": best.get("uniquesEquipped") or [],
            "uniquesKept": list(uniques or []),
            "craftedGear": crafted_gear,
            "converged": converged,
        },
        "constraints": {"minEHP": min_ehp, "resistsCapped": True, "satisfied": bool(satisfying)},
        "leverResults": sorted(
            (_slim(r) for r in results), key=lambda r: r.get("metricValue") or 0, reverse=True
        ),
        "benchmark": bench,
        "combatProfile": profile,
        "note": _CEILING_NOTE,
    }
