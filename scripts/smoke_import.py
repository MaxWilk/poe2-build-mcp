"""M1 import smoke test: prove the PoB-code round-trip + import path.

Builds a known character in the engine, serializes it to PoB XML, runs it through the
import-code codec (the user-paste path), reloads it, and checks the stats are identical.

Run from the repo root:  python scripts/smoke_import.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from compute.engine import PobEngine  # noqa: E402
from compute.pob_code import decode_code, encode_code  # noqa: E402


def main() -> int:
    with PobEngine() as eng:
        # 1. Build a known character and grab its real PoB XML.
        eng.new_build()
        before = eng.paste_skill("Fireball 20/0  1")
        xml = eng.get_xml()
        assert "PathOfBuilding2" in xml, "unexpected serialized XML root"
        print(f"serialized XML : {len(xml)} chars, root <PathOfBuilding2> ok")

        # 2. Round-trip through the import-code codec.
        code = encode_code(xml)
        print(f"import code    : {len(code)} chars (url-safe base64)")
        xml2 = decode_code(code)
        assert xml2 == xml, "round-trip mismatch (encode -> decode)"
        print("round-trip     : XML identical after encode->decode  OK")

        # 3. Re-import the decoded XML into a fresh state; stats must survive.
        eng.new_build()
        after = eng.load_build_xml(xml2)
        dps_before = before["stats"].get("TotalDPS")
        dps_after = after["stats"].get("TotalDPS")
        print(f"main skill     : {after['mainSkill']}")
        print(f"TotalDPS       : before={dps_before}  after-import={dps_after}")
        assert dps_after, "imported build produced no DPS"
        assert abs(dps_after - dps_before) < 1e-6, "stats drifted across import"
        print("\nIMPORT SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
