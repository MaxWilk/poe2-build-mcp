"""M3 smoke test: config, item, evaluate, and compare tools.

Run from the repo root:  uv run python scripts/smoke_m3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.compute.pob_code import encode_code  # noqa: E402
from server.main import (  # noqa: E402
    compare_to,
    equip_item,
    evaluate_build,
    get_build_stats,
    get_engine,
    set_config,
    set_skill,
)


def main() -> int:
    eng = get_engine()
    eng.new_build()

    r0 = set_skill("Fireball 20/0  1")
    dps0 = r0["stats"]["TotalDPS"]
    print(f"set_skill Fireball : TotalDPS={dps0}")

    # custom mods must measurably increase damage
    r1 = set_config(custom_mods="100% increased Fire Damage")
    dps1 = r1["stats"]["TotalDPS"]
    print(f"+100% Fire Damage  : TotalDPS={dps1}")
    assert dps1 > dps0, "custom mod did not increase DPS"

    # named config option (boss) — just exercise the path
    rb = set_config(options={"enemyIsBoss": "Boss"})
    print(f"enemyIsBoss=Boss   : TotalDPS={rb['stats']['TotalDPS']} (effective vs boss may differ)")

    # equip an item base; assert the call succeeds and returns stats
    ri = equip_item("New Item\nElementalist Robe")
    print(
        f"equip Robe         : EnergyShield={ri['stats'].get('EnergyShield')} Life={ri['stats'].get('Life')}"
    )
    assert "TotalDPS" in ri["stats"], "equip_item returned no stats"

    # evaluate against goals
    ev = evaluate_build({"TotalDPS": {"min": 1}, "Life": {"min": 1}})
    print(f"evaluate_build     : pass={ev['pass']}")
    assert ev["pass"], f"evaluation unexpectedly failed: {ev}"

    # compare current build to itself -> deltas ~0, and current build restored afterwards
    code_self = encode_code(eng.get_xml())
    cmp = compare_to(code_self, keys=["TotalDPS", "Life", "EnergyShield"])
    max_delta = max((abs(v) for v in cmp["delta"].values()), default=0.0)
    print(f"compare_to self    : max|delta|={max_delta}")
    assert max_delta < 1e-6, f"self-compare should be ~0, got {cmp['delta']}"

    restored = get_build_stats(["TotalDPS"])["stats"]["TotalDPS"]
    print(f"restored TotalDPS  : {restored}")
    assert abs(restored - ri["stats"]["TotalDPS"]) < 1e-6, "build not restored after compare"

    print("\nM3 SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
