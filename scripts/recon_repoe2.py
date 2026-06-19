"""Recon pass 2: field shapes for skill_gems, skills, ascendancies."""

from __future__ import annotations

import json
import urllib.request

BASE = "https://repoe-fork.github.io/poe2/"
UA = {"User-Agent": "recon"}


def fetch(u: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
        return r.read()


def dump(name: str, n: int = 2) -> dict:
    obj = json.loads(fetch(BASE + name))
    print(f"\n=== {name}: {type(obj).__name__}, size={len(obj)} ===")
    items = list(obj.items()) if isinstance(obj, dict) else list(enumerate(obj))
    for k, v in items[:n]:
        if isinstance(v, dict):
            print(f"  key={k!r} fields={list(v.keys())}")
            print("   ", json.dumps(v)[:600])
    return obj


def main() -> int:
    dump("skill_gems.min.json")
    dump("skills.min.json")
    dump("ascendancies.min.json")
    # how many active vs support gems
    gems = json.loads(fetch(BASE + "skill_gems.min.json"))
    from collections import Counter

    print("\ngem_type counts:", Counter(g.get("gem_type") for g in gems.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
