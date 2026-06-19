"""One-off recon of the RePoE PoE2 data export (structure + URLs for the corpus pipeline)."""

from __future__ import annotations

import json
import re
import urllib.request

BASE = "https://repoe-fork.github.io/poe2/"
UA = {"User-Agent": "poe2-build-mcp-recon"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def list_via_index() -> list[str]:
    try:
        html = fetch(BASE).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print("index fetch failed:", e)
        return []
    return sorted(set(re.findall(r"([A-Za-z0-9_./-]+\.json)", html)))


def list_via_api() -> list[str]:
    for branch in ("master", "main", "gh-pages"):
        url = f"https://api.github.com/repos/repoe-fork/poe2/git/trees/{branch}?recursive=1"
        try:
            tree = json.loads(fetch(url))
            paths = [e["path"] for e in tree.get("tree", []) if e["path"].endswith(".json")]
            if paths:
                print(f"github API branch '{branch}': {len(paths)} json files")
                return sorted(paths)
        except Exception as e:  # noqa: BLE001
            print(f"api {branch}: {e}")
    return []


def inspect(name: str) -> None:
    url = BASE + name
    try:
        raw = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"\n=== {name}: FAILED {e}")
        return
    print(f"\n=== {name} : {len(raw):,} bytes ===")
    try:
        obj = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        print("  not JSON:", e)
        return
    if isinstance(obj, dict):
        keys = list(obj.keys())
        print(f"  dict, {len(keys)} keys; first key = {keys[0]!r}")
        print("  sample entry:", json.dumps(obj[keys[0]])[:500])
    elif isinstance(obj, list):
        print(f"  list, {len(obj)} items")
        print("  sample item:", json.dumps(obj[0])[:500])


def main() -> int:
    idx = list_via_index()
    print(f"index regex found {len(idx)} .json names")
    for f in idx[:60]:
        print("  ", f)
    if len(idx) < 5:
        print("\n-- trying github API --")
        for f in list_via_api()[:80]:
            print("  ", f)

    for name in (
        "base_items.min.json",
        "gems.min.json",
        "skill_gems.min.json",
        "mods.min.json",
        "stat_translations.min.json",
        "uniques.min.json",
    ):
        inspect(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
