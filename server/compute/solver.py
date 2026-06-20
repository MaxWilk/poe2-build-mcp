"""Single-lever target solver.

Answers "how much more X do I need to hit Y?" by holding the active build fixed and
binary-searching the magnitude of one *lever* (a custom modifier we vary) until a chosen
metric reaches a target. Every probe is a real PoB evaluation — nothing is estimated.

Deliberately scoped: it solves ONE lever for ONE (monotonically increasing) metric. It does
not balance survivability or cost, and it reports a *requirement* — which the caller should then
check is actually attainable on real gear/tree. The build is restored exactly afterward.
"""

from __future__ import annotations

from typing import Any

from .engine import PobEngine

# Friendly lever name -> custom-mod template ("{}" is the magnitude). These parse as global
# custom mods in PoB-PoE2. For anything else, pass a raw template containing "{}".
LEVERS: dict[str, str] = {
    "increased damage": "{}% increased Damage",
    "increased physical damage": "{}% increased Physical Damage",
    "increased elemental damage": "{}% increased Elemental Damage",
    "increased fire damage": "{}% increased Fire Damage",
    "increased cold damage": "{}% increased Cold Damage",
    "increased lightning damage": "{}% increased Lightning Damage",
    "increased chaos damage": "{}% increased Chaos Damage",
    "increased spell damage": "{}% increased Spell Damage",
    "increased attack damage": "{}% increased Attack Damage",
    "increased attack speed": "{}% increased Attack Speed",
    "increased cast speed": "{}% increased Cast Speed",
    "attack speed": "{}% increased Attack Speed",
    "cast speed": "{}% increased Cast Speed",
    "increased critical strike chance": "{}% increased Critical Strike Chance",
    "life": "+{} to maximum Life",
    "maximum life": "+{} to maximum Life",
    "energy shield": "+{} to maximum Energy Shield",
    "maximum energy shield": "+{} to maximum Energy Shield",
}

_CAP = 100_000.0  # max lever magnitude before declaring a target unreachable
_MAX_ITERS = 44


def _template_for(lever: str) -> str:
    key = lever.strip().lower()
    if key in LEVERS:
        return LEVERS[key]
    if "{}" in lever:
        return lever  # caller-supplied raw template
    return "{}% increased " + lever.strip()  # last resort: treat as an "increased X" stat


def _fmt(m: float) -> str:
    return str(int(round(m))) if abs(m - round(m)) < 1e-9 else f"{m:.2f}"


def solve_for(
    engine: PobEngine,
    metric: str,
    target: float,
    lever: str,
    tolerance: float = 0.01,
) -> dict[str, Any]:
    template = _template_for(lever)
    build = engine.get_build()
    base_mods = (build.get("customMods") or "") if isinstance(build, dict) else ""
    snapshot = engine.get_xml()

    def probe(m: float) -> float:
        mod = template.format(_fmt(m))
        combined = f"{base_mods}\n{mod}".strip() if base_mods else mod
        v = engine.set_config(custom_mods=combined, keys=[metric])["stats"].get(metric)
        return float(v) if isinstance(v, (int, float)) else float("nan")

    try:
        f0 = probe(0.0)
        if f0 != f0:  # NaN — metric not produced for this build
            return {"ok": False, "error": f"metric '{metric}' is not available on this build"}
        if f0 >= target:
            return {
                "ok": True,
                "metric": metric,
                "target": target,
                "alreadyMet": True,
                "requiredMagnitude": 0.0,
                "baseline": round(f0, 4),
                "lever": template,
            }

        # Expand an upper bound until the metric clears the target (or we hit the cap).
        lo, hi = 0.0, 16.0
        fhi = probe(hi)
        iters = 2
        while fhi < target and hi < _CAP and iters < _MAX_ITERS:
            lo, hi = hi, hi * 2
            fhi = probe(hi)
            iters += 1

        if abs(fhi - f0) < 1e-9:
            return {
                "ok": False,
                "error": (
                    f"lever '{template}' does not affect {metric} on this build "
                    "(not a valid modifier, or it doesn't apply to this skill/defense)"
                ),
            }
        if fhi < target:
            return {
                "ok": True,
                "metric": metric,
                "target": target,
                "reachable": False,
                "bestAchievable": round(fhi, 4),
                "atMagnitude": round(hi, 2),
                "baseline": round(f0, 4),
                "lever": template,
                "note": "target not reachable with this lever alone — try a different lever or "
                "combine changes (gear + tree + supports).",
            }

        # Bisect [lo, hi] for the minimal magnitude that reaches the target.
        while iters < _MAX_ITERS and (hi - lo) > max(tolerance * hi, 1e-6):
            mid = (lo + hi) / 2
            if probe(mid) >= target:
                hi = mid
            else:
                lo = mid
            iters += 1

        achieved = probe(hi)
        return {
            "ok": True,
            "metric": metric,
            "target": target,
            "reachable": True,
            "requiredMagnitude": round(hi, 2),
            "achievedValue": round(achieved, 4),
            "baseline": round(f0, 4),
            "lever": template,
            "note": "single-lever solve; it does not account for survivability or cost — verify "
            "the result with get_defenses / evaluate_build, and confirm the magnitude is "
            "attainable on real gear/tree.",
        }
    finally:
        engine.load_build_xml(snapshot)


# Broad default candidate levers for the marginal scan (custom-mod templates, "{}" = magnitude).
# Damage + defence; irrelevant ones simply rank ~0 for a given metric.
_DEFAULT_LEVERS = [
    "{}% increased Damage",
    "{}% increased Attack Speed",
    "{}% increased Cast Speed",
    "{}% increased Critical Strike Chance",
    "{}% increased Critical Damage Bonus",
    "Damage Penetrates {}% Elemental Resistances",
    "+{} to maximum Life",
    "+{} to maximum Energy Shield",
]


def rank_levers(
    engine: PobEngine,
    metric: str = "TotalDPS",
    unit: float = 10.0,
    levers: list[str] | None = None,
) -> dict[str, Any]:
    """Rank candidate stat levers by their marginal gain to `metric` on the current build.

    The min/max direction-finder: applies each lever at `unit` and measures the real delta, so
    you can see where investment pays off most. Levers are measured independently (greedy).
    """
    templates = levers or _DEFAULT_LEVERS
    build = engine.get_build()
    base_mods = (build.get("customMods") or "") if isinstance(build, dict) else ""
    snapshot = engine.get_xml()
    try:
        base = engine.get_stats([metric])["stats"].get(metric)
        if not isinstance(base, (int, float)):
            return {"ok": False, "error": f"metric '{metric}' is not available on this build"}
        base = float(base)
        out: list[dict[str, Any]] = []
        for raw in templates:
            template = _template_for(raw)
            mod = template.format(_fmt(unit))
            combined = f"{base_mods}\n{mod}".strip() if base_mods else mod
            v = engine.set_config(custom_mods=combined, keys=[metric])["stats"].get(metric)
            if isinstance(v, (int, float)):
                gain = float(v) - base
                out.append(
                    {
                        "lever": template,
                        "gain": round(gain, 2),
                        "gainPerUnit": round(gain / unit, 4),
                    }
                )
        out.sort(key=lambda r: r["gain"], reverse=True)
        return {
            "ok": True,
            "metric": metric,
            "unit": unit,
            "baseline": round(base, 2),
            "levers": out,
            "note": (
                "Marginal gain of each lever at the stated unit on the CURRENT build — a greedy "
                "'where to invest' guide. Levers are measured independently, so verify combined "
                "picks (more-multiplier stacking, breakpoints) together. Pass your build's "
                "specific levers (e.g. '{}% increased Lightning Damage') for sharper results."
            ),
        }
    finally:
        engine.load_build_xml(snapshot)
