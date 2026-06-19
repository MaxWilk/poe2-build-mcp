"""Passive-tree search + allocation tests."""

from __future__ import annotations


def test_keystones_listed(fireball):
    ks = fireball.search_passives(node_type="Keystone", limit=5)["results"]
    assert ks
    assert all(n["type"] == "Keystone" for n in ks)


def test_alloc_then_dealloc(fireball):
    notables = fireball.search_passives(node_type="Notable", limit=400)["results"]
    reachable = [n for n in notables if n.get("pathDist")]
    assert reachable, "no reachable notables"
    target = min(reachable, key=lambda n: n["pathDist"])

    res = fireball.alloc_passive(target["id"])
    assert res["ok"] and res["pointsSpent"] >= 1
    assert res["statsDelta"]

    de = fireball.dealloc_passive(target["id"])
    assert de["ok"] and de["pointsFreed"] >= 1


def test_optimize_improves_dps(fireball):
    res = fireball.optimize_passives(metric="TotalDPS", points=5)
    assert res["allocated"], "optimizer allocated nothing"
    assert res["finalValue"] > res["startValue"]
