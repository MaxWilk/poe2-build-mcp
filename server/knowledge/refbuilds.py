"""Reference / calibration build library (corpus tier — offline, read-only).

Loads data/reference_builds.json (engine-verified high-end builds spanning many archetypes) and
exposes `search` + `benchmark`. These are CALIBRATION references, NOT templates: callers must not
reproduce them. They exist to (a) range-check a build's numbers and (b) reveal which lever an
archetype actually scales on. Pure data — no engine/compute import (benchmark takes already-computed
active stats), so the knowledge↔compute boundary stays clean.
"""

from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from typing import Any

from .. import paths

REFERENCE_ONLY_NOTE = (
    "Reference / CALIBRATION only — NOT templates. Never copy, export, or recommend one of these "
    "wholesale when a user asks for a build; build to the user's stated goal. Use them only to "
    "(a) check a build's numbers sit in a sane endgame range and (b) see which lever an archetype "
    "scales on (then confirm on the real build with rank_levers)."
)


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    p = paths.reference_builds_path()
    if not p.exists():
        return {"builds": [], "treeVersion": None, "count": 0}
    return json.loads(p.read_text(encoding="utf-8"))


def _haystack(b: dict[str, Any]) -> str:
    parts: list[Any] = [
        b.get("class"),
        b.get("ascendancy"),
        b.get("mainSkill"),
        b.get("defenseIdentity"),
        b.get("dominantLever"),
    ]
    parts += (b.get("damageTypes") or []) + (b.get("delivery") or []) + (b.get("keystones") or [])
    return " ".join(str(x) for x in parts if x).lower()


def _slim(b: dict[str, Any]) -> dict[str, Any]:
    """A calibration slice — verified numbers + archetype tags + the scaling lever. No raw code,
    no gear/passive list: there is deliberately nothing here to copy into a build."""
    v = b.get("verified") or {}
    return {
        "class": b.get("class"),
        "ascendancy": b.get("ascendancy"),
        "mainSkill": b.get("mainSkill"),
        "damageTypes": b.get("damageTypes"),
        "delivery": b.get("delivery"),
        "defenseIdentity": b.get("defenseIdentity"),
        "verified": {
            "TotalDPS": v.get("TotalDPS"),
            "TotalEHP": v.get("TotalEHP"),
            "Life": v.get("Life"),
            "EnergyShield": v.get("EnergyShield"),
            "Mana": v.get("Mana"),
            "resistsCapped": v.get("resistsCapped"),
            "chaosHandled": v.get("chaosHandled"),
        },
        "dominantLever": b.get("dominantLever"),
        "topLevers": b.get("topLevers"),
        "dpsComputable": b.get("dpsComputable", True),
    }


def search(query: str = "", limit: int = 8) -> dict[str, Any]:
    """Reference builds matching `query` (class/ascendancy/skill/element/delivery/defense/lever)."""
    d = _data()
    builds = d.get("builds") or []
    terms = [t for t in (query or "").lower().split() if t]
    if terms:
        scored = [(sum(1 for t in terms if t in _haystack(b)), b) for b in builds]
        scored = [(s, b) for s, b in scored if s]
        scored.sort(key=lambda x: -x[0])
        chosen = [b for _, b in scored[:limit]]
    else:
        chosen = builds[:limit]
    return {
        "note": REFERENCE_ONLY_NOTE,
        "treeVersion": d.get("treeVersion"),
        "totalAvailable": len(builds),
        "count": len(chosen),
        "builds": [_slim(b) for b in chosen],
    }


def _dist(vals: list[Any]) -> dict[str, Any] | None:
    nums = sorted(v for v in vals if isinstance(v, (int, float)))
    if not nums:
        return None
    n = len(nums)

    def q(p: float) -> int:
        return round(nums[max(0, min(n - 1, round(p * (n - 1))))])

    return {
        "min": round(nums[0]),
        "p25": q(0.25),
        "median": q(0.5),
        "p75": q(0.75),
        "max": round(nums[-1]),
        "n": n,
    }


def _placement(value: float, dist: dict[str, Any] | None) -> str:
    if not dist:
        return "no reference data for this archetype"
    if value < dist["min"]:
        return "BELOW the reference range"
    if value > dist["max"]:
        return "ABOVE the reference range"
    return "within the reference range"


def benchmark(
    total_dps: float | None,
    full_dps: float | None,
    ehp: float | None,
    delivery: list[str] | None = None,
) -> dict[str, Any]:
    """Place an already-computed active build against the verified reference distribution.

    `delivery` (the active skill's tags, e.g. ["spell","projectile"]) narrows to the same archetype
    when possible; otherwise the whole set is used. Returns ranges + where the build sits + the
    levers those references scale on — for calibration, not imitation.
    """
    d = _data()
    computable = [b for b in (d.get("builds") or []) if b.get("dpsComputable")]
    want = {t.lower() for t in (delivery or [])}
    subset = [b for b in computable if want & set(b.get("delivery") or [])]
    scope = "/".join(sorted(want)) + " builds" if subset else "all reference builds"
    if not subset:
        subset = computable
    dps_dist = _dist([(b.get("verified") or {}).get("TotalDPS") for b in subset])
    ehp_dist = _dist([(b.get("verified") or {}).get("TotalEHP") for b in subset])
    levers = Counter(b.get("dominantLever") for b in subset if b.get("dominantLever"))
    return {
        "note": REFERENCE_ONLY_NOTE,
        "comparedAgainst": scope,
        "sampleSize": len(subset),
        "dps": {
            "yours": round(total_dps or 0),
            "fullDpsYours": round(full_dps) if full_dps else None,
            "reference": dps_dist,
            "placement": _placement(total_dps or 0, dps_dist),
        },
        "ehp": {
            "yours": round(ehp or 0),
            "reference": ehp_dist,
            "placement": _placement(ehp or 0, ehp_dist),
        },
        "archetypeDominantLevers": [{"lever": k, "builds": c} for k, c in levers.most_common(3)],
        "guidance": (
            "Calibrate, don't copy. If DPS/EHP sit below the reference range, find the missing "
            "MULTIPLIER (not margins): run rank_levers on THIS build — across these references the "
            "top lever is almost always '+levels to skills', then a 'more' multiplier or penetration "
            "for the committed element. Raise this build's own weakest layer toward the range."
        ),
    }
