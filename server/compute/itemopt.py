"""Gear slot min-maxer (thin engine + corpus coordinator).

Searches a slot's real craftable affix pool for the best-in-slot rare that maximizes a metric
(e.g. TotalDPS on a weapon), respecting crafting reality: prefix/suffix limits, mod-group
exclusivity, and the base's mod restrictions. Every candidate is engine-evaluated (batched via
eval_items) — nothing is estimated. The result is a *theoretical best-in-slot target* with
idealized rolls; verify attainability and price with get_prices.

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


def optimize_item(
    engine: PobEngine,
    slot: str,
    metric: str = "TotalDPS",
    base: str | None = None,
    ilvl: int = 82,
    rolls: str = "realistic",
    thorough: bool = False,
    keep_resists_capped: bool = True,
) -> dict[str, Any]:
    """Craft the best-in-slot rare for `metric`. See module docstring."""
    build = engine.get_build()
    gear = build.get("gear") or {}
    if not base:
        cur = gear.get(slot)
        base = cur.get("base") if isinstance(cur, dict) else None
    if not base:
        return {
            "ok": False,
            "error": f"No base for slot '{slot}'. Equip an item there first, or pass base=.",
        }

    pool = db.affix_pool(base, ilvl=ilvl)
    pre = [
        {"group": m["group"], "line": _roll(m["text"], rolls), "type": "prefix"}
        for m in pool["prefixes"]
    ]
    suf = [
        {"group": m["group"], "line": _roll(m["text"], rolls), "type": "suffix"}
        for m in pool["suffixes"]
    ]
    if not pre and not suf:
        return {"ok": False, "error": f"No craftable affixes found for base '{base}'."}

    snapshot = engine.get_xml()
    try:
        before = engine.get_stats([metric])["stats"].get(metric)
        before_res = (
            (engine.get_defenses().get("resistOverCap") or {}) if keep_resists_capped else {}
        )

        chosen_pre: list[dict[str, str]] = []
        chosen_suf: list[dict[str, str]] = []
        used: set[str] = set()

        def lines() -> list[str]:
            return [x["line"] for x in chosen_pre + chosen_suf]

        def metric_of(line_sets: list[list[str]]) -> list[float | None]:
            res = engine.eval_items(
                slot, [_item_text(base, ls, slot) for ls in line_sets], keys=[metric]
            )["results"]
            return [(r.get(metric) if isinstance(r, dict) else None) for r in res]

        def best_of(opts: list[dict[str, str]], base_lines: list[str]) -> tuple[int | None, float]:
            if not opts:
                return None, -1.0
            vals = metric_of([base_lines + [c["line"]] for c in opts])
            bi, bv = None, -1.0
            for i, v in enumerate(vals):
                if v is not None and (bi is None or v > bv):
                    bi, bv = i, v
            return bi, bv

        # Greedy: each round add the affix (respecting 3 prefix / 3 suffix + group exclusivity) that
        # most improves the metric, until full or no candidate helps.
        cur_metric = metric_of([lines()])[0] or 0.0
        while len(chosen_pre) < 3 or len(chosen_suf) < 3:
            opts: list[dict[str, str]] = []
            if len(chosen_pre) < 3:
                opts += [c for c in pre if c["group"] not in used]
            if len(chosen_suf) < 3:
                opts += [c for c in suf if c["group"] not in used]
            bi, bv = best_of(opts, lines())
            if bi is None or bv <= cur_metric + 1e-9:
                break
            c = opts[bi]
            (chosen_pre if c["type"] == "prefix" else chosen_suf).append(c)
            used.add(c["group"])
            cur_metric = bv

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
                        if bi is not None and bv > cur_metric + 1e-9:
                            grp_list[idx] = swaps[bi]
                            used = {x["group"] for x in chosen_pre + chosen_suf}
                            cur_metric = bv
                            improved = True
                if improved:
                    continue

        chosen = chosen_pre + chosen_suf
        final = _item_text(base, lines(), slot)
        engine.add_item(final, slot=slot)
        after = engine.get_stats([metric])["stats"].get(metric)
        warnings = []
        if keep_resists_capped:
            after_res = engine.get_defenses().get("resistOverCap") or {}
            # "Capped" = a non-negative over-cap buffer, so this is correct for raised max-res too,
            # not just the default 75 (compare the buffer, not a hard-coded cap number).
            broke = [
                el for el in _RES_KEYS if (before_res.get(el) or 0) >= 0 > (after_res.get(el) or 0)
            ]
            if broke:
                warnings.append(
                    "this max-{} item drops {} resistance below cap — re-cap on another slot or "
                    "trade a damage suffix for resistance.".format(metric, "/".join(broke))
                )
        if not chosen:
            warnings.append(
                f"no affix in this base's pool improved {metric} — the active skill likely doesn't "
                "scale off this slot (e.g. damage that doesn't use this item's stats). The crafted "
                "item is blank; pick a slot/metric the skill actually moves, or optimize a defensive "
                "metric (e.g. TotalEHP) on this slot instead."
            )
    finally:
        engine.load_build_xml(snapshot)

    return {
        "ok": True,
        "slot": slot,
        "base": base,
        "metric": metric,
        "item": final,
        "affixes": [x["line"] for x in chosen],
        "metricBefore": round(before, 2) if isinstance(before, (int, float)) else before,
        "metricAfter": round(after, 2) if isinstance(after, (int, float)) else after,
        "warnings": warnings,
        "note": (
            f"Theoretical best-in-slot for {metric} ({rolls} rolls) from this base's real mod pool "
            "— equip it with equip_item, then verify attainability/price with get_prices. Greedy "
            "search; pass thorough=true for a swap pass. Ignores un-modelled mechanics."
        ),
    }
