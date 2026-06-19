"""Curated, concise Path of Exile 2 mechanics references.

Short reference notes for common mechanics. These are intentionally brief — the in-game
tooltips and PoB's Calcs breakdown remain authoritative for exact interactions.
"""

from __future__ import annotations

MECHANICS: dict[str, str] = {
    "resistances": (
        "Elemental resistances (fire/cold/lightning) reduce elemental damage taken; the cap is "
        "75% (raisable with +maximum resistance). The endgame area penalty is -60% to elemental "
        "resistances (smaller in earlier acts), so you need well over +100% from gear/tree to "
        "reach the 75% cap. Chaos resistance is separate and has no area penalty. 'Over-cap' "
        "(resistance above 75%) is a buffer against enemy penetration and resistance-reducing "
        "curses/exposure."
    ),
    "ailments": (
        "Ailments are debuffs caused by damage. Ignite (fire) burns over time; Shock (lightning) "
        "increases damage the enemy takes; Chill (cold) slows and Freeze locks; Bleed (physical) "
        "and Poison (chaos+physical) are stacking damage-over-time. Magnitude scales with the "
        "hit's size relative to the enemy's ailment threshold."
    ),
    "armour": (
        "Armour mitigates physical hits, with mitigation relative to the hit size — very effective "
        "against many small hits, much weaker against single large hits. It does not reduce "
        "damage-over-time."
    ),
    "evasion": (
        "Evasion gives a chance to avoid being hit by attacks (not spells, not damage-over-time). "
        "PoE uses an 'entropy' system, so evasion is consistent rather than streaky."
    ),
    "energy_shield": (
        "Energy Shield is a buffer depleted before Life; it starts recharging after a short delay "
        "without taking damage. Many builds use it as the main defensive layer (usually on "
        "intelligence gear)."
    ),
    "spirit": (
        "Spirit is a Path of Exile 2 resource used to reserve persistent skills — auras, heralds, "
        "persistent buffs, and some minions/meta-gems. More Spirit lets you run more reservations."
    ),
    "critical_strike": (
        "Critical strikes deal extra damage equal to your Critical Damage Bonus. Scaling crit "
        "needs both Critical Hit Chance and Critical Damage Bonus; some builds skip crit entirely "
        "(e.g. with Controlled Destruction)."
    ),
    "ehp": (
        "Effective HP (EHP) is total survivable damage: Life + Energy Shield + Ward scaled by your "
        "mitigation (armour, resistances, block, evasion). PoB's TotalEHP estimates this against a "
        "mixed damage profile — higher is tankier."
    ),
    "accuracy": (
        "Accuracy sets your chance to land attacks (spells always hit). Low accuracy means misses; "
        "attack builds want hit chance near 100%. It doesn't affect spells or damage-over-time."
    ),
    "recovery": (
        "Recovery comes from Life/ES/Mana regeneration, leech (a % of damage dealt returned over "
        "time, capped by a rate), and flasks. Sustain matters as much as raw EHP for survival."
    ),
}

_NOTE = "Concise reference — verify exact interactions in-game or via PoB's Calcs breakdown."


def explain(topic: str) -> dict:
    t = (topic or "").strip().lower().replace(" ", "_").replace("-", "_")
    if t in MECHANICS:
        return {"topic": t, "text": MECHANICS[t], "note": _NOTE}
    for key in MECHANICS:
        if t and (t in key or key in t):
            return {"topic": key, "text": MECHANICS[key], "note": _NOTE}
    return {"topic": topic, "found": False, "available_topics": sorted(MECHANICS)}


def topics() -> list[str]:
    return sorted(MECHANICS)
