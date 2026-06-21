"""Build the bundled reference-build CALIBRATION library (offline / CI step).

Reads ``reference_builds_seed.txt`` (one PoB code per line) — a deliberately diverse set of
high-end community builds kept ONLY as calibration references (never templates) — runs each
through the pinned engine, and writes ``data/reference_builds.json`` with engine-VERIFIED stats,
the dominant scaling levers, and archetype tags. It stores NO raw PoB codes and NO step-by-step
gear/tree (so the runtime can't hand a build out to copy). Re-run on every PoB submodule bump so
the verified numbers track the engine:  ``uv run python -m pipeline.build_reference_builds``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.compute import solver  # noqa: E402
from server.compute.engine import PobEngine  # noqa: E402
from server.compute.pob_code import to_xml  # noqa: E402
from server.knowledge import db  # noqa: E402

SEED = ROOT / "pipeline" / "reference_builds_seed.txt"
OUT = ROOT / "data" / "reference_builds.json"

# One consistent lever set so the dominant scaler is comparable build-to-build.
LEVERS = [
    "+{} to Level of all Skills",
    "{}% increased Damage",
    "{}% more Damage",
    "Damage Penetrates {}% Elemental Resistances",
    "+{}% to Critical Damage Bonus",
    "{}% increased Critical Strike Chance",
    "{}% increased Attack Speed",
    "{}% increased Cast Speed",
    "+{} to maximum Life",
    "+{} to maximum Energy Shield",
]
_DMG = ("fire", "cold", "lightning", "chaos", "physical")
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


def _defense_identity(keystones: list[str], life: int, es: int, mana: int) -> str:
    k = set(keystones or [])
    if "Chaos Inoculation" in k:
        return "energy-shield / CI (chaos-immune, life=1)"
    if "Eldritch Battery" in k and "Mind Over Matter" in k:
        return "mana as EHP+damage (Eldritch Battery + Mind over Matter)"
    if "Eldritch Battery" in k:
        return "energy-shield routed to mana (Eldritch Battery)"
    if "Mind Over Matter" in k:
        return "life + mana buffer (Mind over Matter)"
    if es > max(life, 1) * 1.5:
        return "energy-shield"
    return "life / hybrid"


def main() -> None:
    codes = [
        ln.strip()
        for ln in SEED.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    eng = PobEngine()
    tree_v, data_v = eng.info.get("treeVersion"), eng.info.get("dataVersion")
    recs: list[dict] = []
    try:
        for code in codes:
            try:
                eng.load_build_xml(to_xml(code))
            except Exception as e:  # noqa: BLE001
                print(f"  skip (decode): {type(e).__name__}: {e}", file=sys.stderr)
                continue
            b = eng.get_build()
            d = eng.get_defenses()
            s = b.get("stats", {}) or {}
            skill = b.get("mainSkill")
            tags = ((db.get_gem(skill) or {}).get("tags") if skill else None) or []
            life, es, mana = (
                round(s.get("Life", 0)),
                round(s.get("EnergyShield", 0)),
                round(s.get("Mana", 0)),
            )
            res = d.get("resistances") or {}
            ele = [res.get("fire"), res.get("cold"), res.get("lightning")]
            dps, full = round(s.get("TotalDPS", 0)), round(s.get("FullDPS", 0))
            computable = dps > 1
            rec = {
                "class": b.get("class"),
                "ascendancy": b.get("ascendancy"),
                "mainSkill": skill,
                "damageTypes": [t for t in _DMG if t in tags],
                "delivery": [t for t in _DELIVERY if t in tags],
                "defenseIdentity": _defense_identity(b.get("keystones"), life, es, mana),
                "keystones": b.get("keystones") or [],
                "verified": {
                    "TotalDPS": dps if computable else None,
                    "FullDPS": full or None,
                    "Life": life,
                    "EnergyShield": es,
                    "Mana": mana,
                    "TotalEHP": round(d.get("totalEHP", 0)),
                    "resists": res,
                    "resistsCapped": all((x or 0) >= 73 for x in ele),
                    "chaosHandled": (res.get("chaos", 0) or 0) >= 75
                    or "Chaos Inoculation" in (b.get("keystones") or []),
                },
                "dpsComputable": computable,
            }
            if computable:
                rl = solver.rank_levers(eng, metric="TotalDPS", unit=10, levers=LEVERS)
                base = rl.get("baseline") or 1
                ranked = sorted(rl.get("levers", []), key=lambda x: -(x.get("gainPerUnit") or 0))
                rec["topLevers"] = [
                    {
                        "lever": x["lever"].replace("{}", "N"),
                        "pctPerUnit": round(100 * (x.get("gainPerUnit") or 0) / base, 2),
                    }
                    for x in ranked[:4]
                    if (x.get("gainPerUnit") or 0) > 0
                ]
                rec["dominantLever"] = rec["topLevers"][0]["lever"] if rec["topLevers"] else None
            recs.append(rec)
            print(f"  ok: {rec['ascendancy']:>20} / {skill}", file=sys.stderr)
    finally:
        eng.proc.terminate()

    payload = {
        "_note": (
            "Reference / CALIBRATION builds — engine-verified, NOT templates. Never copy, export, or "
            "recommend one of these wholesale when a user asks for a build. Use them only to (a) "
            "sanity-check that a build's numbers are in a sane endgame range and (b) see which lever an "
            "archetype actually scales on. The user's stated goal drives the build; these only calibrate it."
        ),
        "treeVersion": tree_v,
        "dataVersion": data_v,
        "count": len(recs),
        "builds": recs,
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(
        f"wrote {len(recs)} reference builds -> {OUT}  (tree {tree_v}, data {data_v})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
