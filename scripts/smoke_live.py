"""M4 live-ops smoke test (network: poe2scout prices + data-version check).

Run from the repo root:  uv run python scripts/smoke_live.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.live import prices, version  # noqa: E402


def main() -> int:
    leagues = prices.list_leagues()
    current = [leag for leag in leagues if leag["current"]]
    print(
        "leagues:",
        [leag["name"] for leag in leagues][:6],
        "| current:",
        [c["name"] for c in current],
    )
    assert current, "no current league reported"

    divine = prices.get_prices("divine", kind="currency", limit=3)
    print(f"prices ({divine['league']}, base={divine['base_currency']}):")
    for r in divine["results"]:
        print(f"   {r['name']}: {r['price']}")
    assert divine["results"], "no currency price results"

    mb = prices.get_prices("", kind="currency", limit=3)
    print("top currencies:", [(r["name"], round(r["price"], 1)) for r in mb["results"]])

    ver = version.check_data_version()
    print(
        "check_data_version:",
        {k: ver[k] for k in ("upstream_last_modified", "current_league", "recommendation")},
    )
    print(
        "local corpus counts:",
        ver["local"].get("counts"),
        "built_at:",
        ver["local"].get("built_at"),
    )

    # update_corpus download mode is a safe no-op until releases exist
    no = version.update_corpus(rebuild_from_source=False)
    print("update_corpus (download mode):", no.get("updated"), "-", no.get("reason"))
    assert no["updated"] is False

    print("\nLIVE SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
