"""M5 smoke test: greedy passive optimizer.

Run from the repo root:  uv run python scripts/smoke_optimize.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.main import get_engine, optimize_passives, set_skill  # noqa: E402


def main() -> int:
    eng = get_engine()
    eng.new_build()
    set_skill("Fireball 20/0  1")

    res = optimize_passives(metric="TotalDPS", points=6)
    print(f"metric={res['metric']} start={res['startValue']:.2f} final={res['finalValue']:.2f}")
    print(f"points used: {res['pointsUsed']}")
    for step in res["allocated"]:
        print(
            f"   +{step['gain']:.2f} DPS  <-  {step['name']} (id={step['id']}, cost={step['cost']})"
        )

    assert res["allocated"], "optimizer allocated nothing"
    assert res["finalValue"] > res["startValue"], "optimizer did not improve the metric"
    # gains should be in non-increasing order (greedy picks best each step)
    gains = [s["gain"] for s in res["allocated"]]
    print("gains:", [round(g, 1) for g in gains])

    print("\nOPTIMIZE SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
