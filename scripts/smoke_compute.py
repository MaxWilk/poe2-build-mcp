"""M1 smoke test: drive the headless PoB engine through the Python client.

Run from the repo root:  python scripts/smoke_compute.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from compute.engine import PobEngine  # noqa: E402


def main() -> int:
    with PobEngine(show_engine_logs=False) as eng:
        print("ready frame :", eng.info)
        print("ping        :", eng.ping())

        nb = eng.new_build()
        print("new build   : Life=%s Mana=%s" % (nb["stats"].get("Life"), nb["stats"].get("Mana")))

        res = eng.paste_skill("Fireball 20/0  1")
        s = res["stats"]
        print("main skill  :", res["mainSkill"])
        for k in ("TotalDPS", "AverageDamage", "Speed", "CritChance", "ManaCost", "Life", "Mana"):
            print(f"  {k:<14} = {s.get(k)}")

        # A second, different skill on the SAME long-lived process (proves reuse).
        res2 = eng.paste_skill("Spark 20/0  1")
        print("re-query    :", res2["mainSkill"], "TotalDPS=", res2["stats"].get("TotalDPS"))

        assert s.get("TotalDPS"), "expected a non-zero Fireball TotalDPS"
        print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
