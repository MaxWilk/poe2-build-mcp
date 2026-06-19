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


def test_set_class_and_ascendancy(engine):
    engine.new_build()
    r = engine.set_class("Mercenary", "Witchhunter")
    assert r["ok"] and r["class"] == "Mercenary" and r["ascendancy"] == "Witchhunter"

    # a Witchhunter ascendancy node should now exist and be reachable
    nodes = engine.search_passives(node_type=None, limit=6000)["results"]
    wh = [n for n in nodes if (n.get("ascendancy") or "") == "Witchhunter" and n.get("pathDist")]
    assert wh, "no reachable Witchhunter ascendancy nodes after set_class"

    # optimize now paths from the correct class start
    op = engine.optimize_passives(metric="Life", points=5)
    assert op["finalValue"] > op["startValue"]


def test_set_class_unknown(engine):
    engine.new_build()
    assert engine.set_class("Notaclass")["ok"] is False


def test_set_level(engine):
    engine.new_build()
    base = engine.get_stats(["Life"])["stats"]["Life"]
    r = engine.set_level(90)
    assert r["ok"] and r["level"] == 90
    assert r["stats"]["Life"] > base  # higher level => more life (auto-leveling disabled)
