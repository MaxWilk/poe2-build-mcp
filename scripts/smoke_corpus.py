"""M2 corpus smoke test (run after `uv run python -m pipeline.build_corpus`).

Run from the repo root:  uv run python scripts/smoke_corpus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.knowledge import db  # noqa: E402


def main() -> int:
    print("corpus_info:", db.corpus_info())

    fb = db.get_gem("Fireball")
    assert fb and fb["name"] == "Fireball", "Fireball gem not found in corpus"
    print(
        "get_gem Fireball:",
        fb["color"],
        fb["gem_type"],
        fb["tags"][:5],
        "| supports:",
        fb["supports"][:3],
    )

    assert db.find_skills("fire", gem_type="active", limit=5), "no fire actives"
    assert db.find_skills(gem_type="support", limit=3), "no supports"
    assert db.search_items("ring", limit=5), "no rings"
    assert db.list_ascendancies(), "no ascendancies"

    # mods
    life = db.search_mods("maximum life", item_tag="ring", mod_type="prefix", limit=5)
    print("search_mods 'maximum life' on ring (prefix):")
    for m in life[:5]:
        print(f"   {m['type']:<6} {m['name']!r}: {m['text']}")
    assert life, "no life prefixes on ring"

    # reverse lookup across mods/gems/uniques
    rl = db.reverse_lookup("increased fire damage", limit=6)
    print("reverse_lookup 'increased fire damage':", {k: len(v) for k, v in rl.items()})
    assert rl["mods"] or rl["gems"], "reverse_lookup found nothing"

    # uniques
    rings = db.search_uniques("", item_type="ring", limit=5)
    print("unique rings:", [u["name"] for u in rings])
    assert rings, "no unique rings"
    u = db.get_unique(rings[0]["name"])
    assert u and u["text"], "get_unique returned no text"
    print(f"get_unique {u['name']} ({u['base']}):")
    print("   " + u["text"].replace("\n", "\n   "))

    print("\nCORPUS SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
