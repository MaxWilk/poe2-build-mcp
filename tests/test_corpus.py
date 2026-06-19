"""Corpus query tests. Skipped if the corpus DB hasn't been built."""

from __future__ import annotations

import pytest

from server.knowledge import db

pytestmark = pytest.mark.skipif(
    not db.db_path().exists(),
    reason="corpus not built (run: uv run python -m pipeline.build_corpus)",
)


def test_counts():
    counts = db.corpus_info()["counts"]
    assert counts["items"] > 5000
    assert counts["gems"] > 1000
    assert counts["mods"] > 5000
    assert counts["uniques"] > 300


def test_get_gem_fireball():
    g = db.get_gem("Fireball")
    assert g and g["gem_type"] == "active"
    assert "fire" in g["tags"]
    assert g["supports"]


def test_find_skills_by_tag():
    minions = db.find_skills(tag="minion", limit=5)
    assert minions


def test_search_mods_life_on_ring():
    mods = db.search_mods("maximum life", item_tag="ring", mod_type="prefix", limit=5)
    assert mods
    assert all(m["type"] == "prefix" for m in mods)
    assert any("life" in m["text"].lower() for m in mods)


def test_reverse_lookup():
    rl = db.reverse_lookup("increased fire damage", limit=5)
    assert rl["mods"] or rl["gems"]


def test_get_unique():
    u = db.get_unique("Andvarius")
    assert u and "Gold Ring" in u["base"]
    assert "Rarity" in u["text"]
