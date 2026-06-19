"""Passive-tree smoke test: search + allocate/deallocate with stat deltas.

Run from the repo root:  uv run python scripts/smoke_passives.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.main import (  # noqa: E402
    alloc_passive,
    dealloc_passive,
    get_engine,
    search_passives,
    set_skill,
)


def main() -> int:
    eng = get_engine()
    eng.new_build()
    set_skill("Fireball 20/0  1")

    keystones = search_passives(node_type="Keystone", limit=8)["results"]
    print("keystones:", [n["name"] for n in keystones][:8])
    assert keystones, "no keystones found"

    fire = search_passives(query="fire", node_type="Notable", limit=8)["results"]
    print("fire notables:", [n["name"] for n in fire][:8])

    # Allocate the nearest reachable notable and check we spend points + move stats.
    notables = search_passives(node_type="Notable", limit=600)["results"]
    reachable = [n for n in notables if n.get("pathDist")]
    assert reachable, "no reachable notables"
    target = min(reachable, key=lambda n: n["pathDist"])
    print(f"allocating: {target['name']} (id={target['id']}, pathDist={target['pathDist']})")
    print("   stats:", target.get("stats"))

    res = alloc_passive(target["id"])
    assert res.get("ok"), res
    print(f"alloc: pointsSpent={res['pointsSpent']} delta={res['statsDelta']}")
    assert res["pointsSpent"] >= 1, "expected to spend at least one point"
    assert res["statsDelta"], "expected some stat change from allocation"

    de = dealloc_passive(target["id"])
    assert de.get("ok"), de
    print(f"dealloc: pointsFreed={de['pointsFreed']}")
    assert de["pointsFreed"] >= 1, "expected to free points"

    print("\nPASSIVES SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
