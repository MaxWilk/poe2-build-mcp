"""Support-gem set optimizer (engine search; needs no magnitude data).

Greedily picks the support gems that most raise a metric (or weighted goals) for the active main
skill, measuring each combination on the real engine. The corpus has support-gem identity but not
effect magnitudes, so the only honest way to value a support is to try it — this is a bounded
mechanical search over engine truth, like optimize_passives / optimize_item.
"""

from __future__ import annotations

from typing import Any

from ..knowledge import db
from .engine import PobEngine


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _r2(x: Any) -> Any:
    return round(x, 2) if _num(x) else x


def _screen_set(skill: str, screen: int) -> list[str]:
    """Tag-relevant supports to solo-screen: recommended + on-element first, then delivery, deduped
    and bounded to `screen`.

    On-element supports (those sharing the skill's damage type) lead so they survive the bound — they
    include the premier levers (penetration, added/increased element damage) that a tag-COUNT ranking
    buries, because such a support often shares ONLY the element tag and so looks "least relevant".
    """
    info = db.find_supports_for(skill, limit=9999)
    rec = info.get("recommended") or []
    comp = info.get("compatible") or []
    on_elem = [c["name"] for c in comp if c.get("on_element")]
    delivery = [c["name"] for c in comp if not c.get("on_element")]
    out: list[str] = []
    seen: set[str] = set()
    for nm in (*rec, *on_elem, *delivery):
        if nm and nm not in seen:
            seen.add(nm)
            out.append(nm)
    return out[: max(screen, 1)]


def optimize_supports(
    engine: PobEngine,
    metric: str = "TotalDPS",
    goals: dict[str, float] | None = None,
    max_supports: int = 5,
    candidates: int = 16,
    screen: int = 48,
) -> dict[str, Any]:
    """Greedily choose the best support-gem set for the active main skill (engine-measured).

    `goals` (weighted, e.g. {"TotalDPS":.7,"TotalEHP":.3}) blends objectives; omit for single
    `metric`. Builds the candidate pool by MEASUREMENT, not tags: it solo-measures the skill's
    tag-relevant supports (`screen` of them; on-element supports — those sharing the skill's damage
    type, like penetration — are always included), keeps the strongest `candidates`, then greedily
    adds the support that most improves the goal each round until the sockets are full or nothing
    helps (over-cap gems are ignored, so they show no gain). Read-only: the build is restored.
    """
    grp = engine.get_build().get("mainSkillGroup") or []
    if not grp:
        return {"ok": False, "error": "No active main skill — set_skill first."}
    head = grp[0]
    skill = head["name"]
    lvl, qual = head.get("level", 20), head.get("quality", 0)

    weights: dict[str, float] = {}
    if goals:
        weights = {str(k): float(v) for k, v in goals.items() if _num(v) and float(v) > 0}
        if not weights:
            return {"ok": False, "error": "goals must map stat names to positive weights."}
    keys = list(weights) if weights else [metric]

    screen_names = _screen_set(skill, screen)
    if not screen_names:
        return {"ok": False, "error": f"No supports found for '{skill}'."}

    snapshot = engine.get_xml()
    try:

        def measure(supports: list[str]) -> dict[str, Any]:
            text = f"{skill} {lvl}/{qual} 1"
            if supports:
                text += "\n" + "\n".join(supports)
            r = engine.paste_skill(text)
            st = r.get("stats") if isinstance(r, dict) else None
            return st if isinstance(st, dict) else {}

        base_stats = measure([])  # skill alone = the baseline
        denom = {k: max(abs(base_stats.get(k) or 0.0), 1.0) for k in keys}

        def score(st: dict[str, Any]) -> float:
            if weights:
                return sum(
                    w * ((st.get(k) or 0.0) - (base_stats.get(k) or 0.0)) / denom[k]
                    for k, w in weights.items()
                )
            v = st.get(metric)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            return float("-inf")

        # Candidate pool by MEASUREMENT, not tag count. A support's shared-tag count is a poor proxy
        # for value — top DPS levers like penetration or added-damage often share only the element
        # tag and would be truncated out of a tag-ranked list. So solo-measure each tag-relevant
        # support and keep the strongest `candidates` for the combo-aware greedy below. This is what
        # lets the search find e.g. Lightning Penetration on a lightning skill.
        base_sc = score(base_stats)
        screened = sorted(
            ((score(measure([nm])), nm) for nm in screen_names),
            key=lambda t: t[0],
            reverse=True,
        )
        pool = [nm for sc, nm in screened if sc > base_sc + 1e-9][:candidates]

        chosen: list[str] = []
        cur = base_sc
        progression: list[dict[str, Any]] = []
        while len(chosen) < max_supports:
            best_nm, best_sc, best_st = None, cur, None
            for nm in pool:
                if nm in chosen:
                    continue
                st = measure(chosen + [nm])
                sc = score(st)
                if sc > best_sc + 1e-9:
                    best_nm, best_sc, best_st = nm, sc, st
            if best_nm is None:
                break  # nothing improves, or sockets full (extra gems ignored -> no gain)
            chosen.append(best_nm)
            cur = best_sc
            progression.append({"added": best_nm, **{k: _r2((best_st or {}).get(k)) for k in keys}})
        final_stats = measure(chosen)
    finally:
        engine.load_build_xml(snapshot)

    out: dict[str, Any] = {
        "ok": True,
        "skill": skill,
        "supports": chosen,
        "screened": len(screen_names),
        "candidatesTried": len(pool),
        "progression": progression,
        "note": (
            "Engine search — each support is valued empirically (the corpus has no support "
            "magnitudes). The pool is chosen by MEASUREMENT not tags: every tag-relevant support is "
            "solo-measured and the strongest kept, then combined greedily. Stops when nothing helps "
            "or the skill's sockets are full (over-cap gems are ignored). Apply with "
            "set_skill('<skill> <lvl>/<q> 1 / " + " / ".join(chosen or ["<support>"]) + "'). "
            "Greedy, not a global optimum."
        ),
    }
    if weights:
        out["goals"] = weights
        out["metricsBase"] = {k: _r2(base_stats.get(k)) for k in keys}
        out["metricsFinal"] = {k: _r2(final_stats.get(k)) for k in keys}
    else:
        out["metric"] = metric
        out["baseValue"] = _r2(base_stats.get(metric))
        out["finalValue"] = _r2(final_stats.get(metric))
    if not chosen:
        out["warning"] = (
            "No support improved the skill — its DPS may be uncomputable (e.g. an attack with no "
            "weapon equipped; equip a weapon first), or the candidates don't fit/help."
        )
    return out
