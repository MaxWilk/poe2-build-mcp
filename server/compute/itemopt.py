"""Gear slot min-maxer (thin engine + corpus coordinator).

Searches a slot's real craftable affix pool for the best-in-slot rare. It maximizes either a
single `metric` (e.g. TotalDPS on a weapon) or a weighted blend of metrics via `goals`
(e.g. {"TotalDPS": .6, "TotalEHP": .4}) so one craft can carry both damage AND defense —
respecting crafting reality: prefix/suffix limits, mod-group exclusivity, and the base's mod
restrictions. Every candidate is engine-evaluated (batched via eval_items) — nothing is estimated.
The result is a *theoretical best-in-slot target* with idealized rolls; verify attainability and
price with get_prices.

Like solve_for/optimize_passives, this is a bounded mechanical search over engine truth — it
optimizes a goal the caller gives, it does not decide the goal.
"""

from __future__ import annotations

import re
from typing import Any

from ..knowledge import db
from .engine import PobEngine

_RANGE = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")
_RES_KEYS = ("fire", "cold", "lightning")


def _num(x: Any) -> bool:
    """True for a real number (bool excluded — JSON true/false must not count as 1/0)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _round2(x: Any) -> Any:
    return round(x, 2) if _num(x) else x


def _roll(text: str, rolls: str) -> str:
    """Turn a range mod ("+(80-90) to maximum Life") into a concrete roll."""

    def sub(m: re.Match[str]) -> str:
        a, b = float(m.group(1)), float(m.group(2))
        v = b if rolls == "max" else round(a + 0.85 * (b - a))
        return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:g}"

    return _RANGE.sub(sub, text)


def _item_text(base: str, lines: list[str], slot: str) -> str:
    body = "\n".join(lines)
    return f"Rarity: Rare\nOptimized {slot}\n{base}\n--------\n{body}"


def _craft_summary(
    chosen: list[dict[str, Any]], prefix_pool: int, suffix_pool: int
) -> dict[str, Any]:
    """A coarse craft-effort / attainability estimate (NOT a market price).

    The data has no usable spawn-weights (all 1), so 'effort' is inferred from how many specific
    affixes the craft needs, how many are a TOP tier of several (rarer rolls), and the item level
    required — a rough realism check, not a probability or a divine cost.
    """
    n = len(chosen)
    deep = sum(1 for c in chosen if (c.get("tiers") or 1) >= 4)
    min_ilvl = max((c.get("ilvl") or 0 for c in chosen), default=0)
    score = n + deep
    if n == 0:
        effort = "trivial"
    elif score <= 3:
        effort = "low"
    elif score <= 6:
        effort = "moderate"
    elif score <= 9:
        effort = "high"
    else:
        effort = "very high"
    return {
        "effort": effort,
        "minItemLevel": min_ilvl,
        "prefixPool": prefix_pool,
        "suffixPool": suffix_pool,
        "topTierAffixesNeeded": deep,
        "note": (
            f"~{effort} craft: {n} specific affix(es)"
            + (f" ({deep} a top tier of several)" if deep else "")
            + f" on an ilvl {min_ilvl}+ base, competing in a pool of {prefix_pool} prefix / "
            f"{suffix_pool} suffix mods. Rough heuristic from tier depth + pool size (no spawn-weight "
            "data); essence/bench crafts can make specific mods deterministic and cheaper."
        ),
    }


def optimize_item(
    engine: PobEngine,
    slot: str,
    metric: str = "TotalDPS",
    base: str | None = None,
    ilvl: int = 82,
    rolls: str = "realistic",
    thorough: bool = False,
    keep_resists_capped: bool = True,
    goals: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Craft the best-in-slot rare for a single `metric`, or a weighted blend via `goals`.

    `goals` (e.g. {"TotalDPS": .6, "TotalEHP": .4}) scores each candidate by the weighted sum of
    *relative* gains vs the bare base, so a single craft balances offense and defense (real endgame
    gear is blended, not pure-DPS or pure-EHP). Omit `goals` for the single-`metric` behaviour.
    See the module docstring.
    """
    build = engine.get_build()
    gear = build.get("gear") or {}
    if not base:
        cur_item = gear.get(slot)
        base = cur_item.get("base") if isinstance(cur_item, dict) else None
    if not base:
        return {
            "ok": False,
            "error": f"No base for slot '{slot}'. Equip an item there first, or pass base=.",
        }

    # `goals` = weighted multi-objective (blended gear); falls back to the single `metric`.
    weights: dict[str, float] = {}
    if goals:
        weights = {str(k): float(v) for k, v in goals.items() if _num(v) and float(v) > 0}
        if not weights:
            return {
                "ok": False,
                "error": "goals must map stat names to positive weights, "
                'e.g. {"TotalDPS": 0.6, "TotalEHP": 0.4}.',
            }
    keys = list(weights) if weights else [metric]

    pool = db.affix_pool(base, ilvl=ilvl)
    pre = [
        {
            "group": m["group"],
            "line": _roll(m["text"], rolls),
            "type": "prefix",
            "tiers": m.get("tiers", 1),
            "ilvl": m.get("required_level", 0),
        }
        for m in pool["prefixes"]
    ]
    suf = [
        {
            "group": m["group"],
            "line": _roll(m["text"], rolls),
            "type": "suffix",
            "tiers": m.get("tiers", 1),
            "ilvl": m.get("required_level", 0),
        }
        for m in pool["suffixes"]
    ]
    if not pre and not suf:
        return {"ok": False, "error": f"No craftable affixes found for base '{base}'."}

    snapshot = engine.get_xml()
    try:
        before_vals = engine.get_stats(keys)["stats"]
        before_missing = (
            (engine.get_defenses().get("resistMissing") or {}) if keep_resists_capped else {}
        )

        chosen_pre: list[dict[str, str]] = []
        chosen_suf: list[dict[str, str]] = []
        used: set[str] = set()

        def lines() -> list[str]:
            return [x["line"] for x in chosen_pre + chosen_suf]

        def stats_of(line_sets: list[list[str]]) -> list[dict[str, Any]]:
            res = engine.eval_items(
                slot, [_item_text(base, ls, slot) for ls in line_sets], keys=keys
            )["results"]
            return [r if isinstance(r, dict) else {} for r in res]

        # Bare base = the craft's starting point; relative gains in `goals` mode are measured from it.
        base_stats = stats_of([[]])[0]
        denom = {k: max(abs(base_stats.get(k) or 0.0), 1.0) for k in keys}

        def score(st: dict[str, Any]) -> float:
            """Weighted relative gain vs the bare base (goals mode), else the raw metric value."""
            if weights:
                return sum(
                    w * ((st.get(k) or 0.0) - (base_stats.get(k) or 0.0)) / denom[k]
                    for k, w in weights.items()
                )
            v = st.get(metric)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            return float("-inf")

        def best_of(opts: list[dict[str, str]], base_lines: list[str]) -> tuple[int | None, float]:
            if not opts:
                return None, float("-inf")
            sts = stats_of([base_lines + [c["line"]] for c in opts])
            bi, bv = None, float("-inf")
            for i, st in enumerate(sts):
                s = score(st)
                if s > bv:
                    bi, bv = i, s
            return bi, bv

        # Greedy: each round add the affix (respecting 3 prefix / 3 suffix + group exclusivity) that
        # most improves the score, until full or no candidate helps.
        cur = score(base_stats)
        while len(chosen_pre) < 3 or len(chosen_suf) < 3:
            opts: list[dict[str, str]] = []
            if len(chosen_pre) < 3:
                opts += [c for c in pre if c["group"] not in used]
            if len(chosen_suf) < 3:
                opts += [c for c in suf if c["group"] not in used]
            bi, bv = best_of(opts, lines())
            if bi is None or bv <= cur + 1e-9:
                break
            c = opts[bi]
            (chosen_pre if c["type"] == "prefix" else chosen_suf).append(c)
            used.add(c["group"])
            cur = bv

        # Optional swap pass: replace each chosen affix with an unused one OF THE SAME TYPE if it
        # improves — catches greedy local optima without breaking the prefix/suffix split.
        if thorough:
            improved = True
            while improved:
                improved = False
                for grp_list, poolside in ((chosen_pre, pre), (chosen_suf, suf)):
                    for idx in range(len(grp_list)):
                        rest = grp_list[:idx] + grp_list[idx + 1 :]
                        rest_used = used - {grp_list[idx]["group"]}
                        swaps = [c for c in poolside if c["group"] not in rest_used]
                        other = [x["line"] for x in (chosen_suf if poolside is pre else chosen_pre)]
                        base_lines = [x["line"] for x in rest] + other
                        bi, bv = best_of(swaps, base_lines)
                        if bi is not None and bv > cur + 1e-9:
                            grp_list[idx] = swaps[bi]
                            used = {x["group"] for x in chosen_pre + chosen_suf}
                            cur = bv
                            improved = True
                if improved:
                    continue

        chosen = chosen_pre + chosen_suf
        final = _item_text(base, lines(), slot)
        engine.add_item(final, slot=slot)
        after_vals = engine.get_stats(keys)["stats"]
        warnings = []
        if keep_resists_capped:
            after_missing = engine.get_defenses().get("resistMissing") or {}
            # A resist "broke" if it was at/above cap before (0 points missing) and is below cap
            # after (>0 missing). `resistMissing` uses PoB's real per-element cap, so this is correct
            # for raised max-res too — not a hard-coded 75. (PoB floors *ResistOverCap at 0, so the
            # old over-cap-goes-negative check could never fire.)
            broke = [
                el
                for el in _RES_KEYS
                if (before_missing.get(el) or 0) <= 0 < (after_missing.get(el) or 0)
            ]
            if broke:
                warnings.append(
                    "this craft drops {} resistance below cap — re-cap on another slot, or add "
                    "TotalEHP to `goals` so the craft keeps resistances itself.".format(
                        "/".join(broke)
                    )
                )
        if not chosen:
            warnings.append(
                "no affix in this base's pool improved the goal — the active skill likely doesn't "
                "scale off this slot (e.g. damage that doesn't use this item's stats). The crafted "
                "item is blank; pick a slot/metric the skill actually moves, or optimize a defensive "
                "metric (e.g. TotalEHP) on this slot instead."
            )
    finally:
        engine.load_build_xml(snapshot)

    goal_desc = (
        "blend " + ", ".join(f"{k}×{w:g}" for k, w in weights.items()) if weights else metric
    )
    out: dict[str, Any] = {
        "ok": True,
        "slot": slot,
        "base": base,
        "item": final,
        "affixes": [x["line"] for x in chosen],
        "attainability": [
            {"affix": c["line"], "ilvl": c.get("ilvl", 0), "tiers": c.get("tiers", 1)}
            for c in chosen
        ],
        "craft": _craft_summary(chosen, len(pre), len(suf)),
        "warnings": warnings,
        "note": (
            f"Theoretical best-in-slot for {goal_desc} ({rolls} rolls) from this base's real mod "
            "pool — equip it with equip_item, then verify attainability/price with get_prices. "
            "Greedy search; pass thorough=true for a swap pass. Ignores un-modelled mechanics."
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBefore"] = {k: _round2(before_vals.get(k)) for k in keys}
        out["metricsAfter"] = {k: _round2(after_vals.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["metricBefore"] = _round2(before_vals.get(metric))
        out["metricAfter"] = _round2(after_vals.get(metric))
    return out


_UPGRADE_SLOTS = (
    "Weapon 1",
    "Weapon 2",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
    "Belt",
    "Amulet",
    "Ring 1",
    "Ring 2",
)


def rank_upgrades(
    engine: PobEngine,
    metric: str = "TotalDPS",
    goals: dict[str, float] | None = None,
    slots: list[str] | None = None,
    rolls: str = "realistic",
    top: int = 8,
) -> dict[str, Any]:
    """Rank gear slots by how much recrafting each would gain — 'what should I upgrade next'.

    Recrafts each candidate slot independently (via optimize_item, single `metric` or weighted
    `goals`) to its best, measures the gain over the CURRENT item there, and ranks high→low.
    Read-only: every probe is snapshotted and restored. Gains are NOT additive — recrafting one slot
    shifts the others — so upgrade the top slot, then re-run. Empty slots with no base are skipped
    (optimize that slot directly with a `base` to explore them).
    """
    candidate_slots = list(slots) if slots else list(_UPGRADE_SLOTS)
    ranked: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for slot in candidate_slots:
        r = optimize_item(
            engine, slot, metric=metric, goals=goals, rolls=rolls, keep_resists_capped=True
        )
        if not r.get("ok"):
            skipped.append({"slot": slot, "reason": str(r.get("error", "no craftable affixes"))})
            continue
        entry: dict[str, Any] = {"slot": slot, "affixes": r["affixes"], "item": r["item"]}
        if r.get("warnings"):
            entry["warnings"] = r["warnings"]
        if goals:
            mb, ma = r["metricsBefore"], r["metricsAfter"]
            entry["deltas"] = {k: _round2((ma.get(k) or 0) - (mb.get(k) or 0)) for k in ma}
            entry["score"] = round(
                sum(
                    w * (((ma.get(k) or 0) - (mb.get(k) or 0)) / max(abs(mb.get(k) or 0), 1.0))
                    for k, w in goals.items()
                    if _num(w)
                ),
                4,
            )
            entry["_sort"] = entry["score"]
        else:
            mb, ma = r.get("metricBefore"), r.get("metricAfter")
            if isinstance(ma, (int, float)) and isinstance(mb, (int, float)):
                delta = float(ma) - float(mb)  # gain from recrafting this slot
            else:
                delta = float(ma) if isinstance(ma, (int, float)) else 0.0  # empty slot = full add
            entry["metric"] = metric
            entry["before"], entry["after"], entry["delta"] = mb, ma, _round2(delta)
            entry["_sort"] = delta
        ranked.append(entry)
    ranked.sort(key=lambda x: x["_sort"] if _num(x.get("_sort")) else 0.0, reverse=True)
    for e in ranked:
        e.pop("_sort", None)
    return {
        "ok": True,
        "metric": "blend" if goals else metric,
        "goals": goals or None,
        "ranked": ranked[:top],
        "skipped": skipped,
        "note": (
            "Each slot recrafted independently to its best for the goal, ranked by the gain over "
            "your CURRENT item there — upgrade the top slot first. Gains are NOT additive (crafting "
            "one slot shifts the rest); re-run after each real change. Targets are theoretical — "
            "price them with get_prices."
        ),
    }
