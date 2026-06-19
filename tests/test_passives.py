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


def test_search_passives_ascendancy_and_partial(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Witchhunter")
    # ascendancy name is now searchable -> returns that ascendancy's nodes
    asc = engine.search_passives(query="Witchhunter")["results"]
    assert asc and all(n.get("ascendancy") == "Witchhunter" for n in asc)
    # multi-word/conceptual query returns ranked partial matches (used to AND to []):
    multi = engine.search_passives(query="explode on death fire damage", limit=10)["results"]
    assert multi


def test_search_passives_reachable_first(fireball):
    # with no query, browse mode ranks reachable nodes (lowest pathDist) first
    res = fireball.search_passives(node_type="Notable", limit=50)["results"]
    dists = [n["pathDist"] for n in res if n.get("pathDist") is not None]
    assert dists == sorted(dists)


def test_set_class_unknown_lists_valid_options(engine):
    engine.new_build()
    bad_cls = engine.set_class("Notaclass")
    assert bad_cls["ok"] is False
    # the error must help the model self-correct by naming the real classes
    assert "Valid classes" in bad_cls["error"] and "Witch" in bad_cls["error"]

    bad_asc = engine.set_class("Witch", "Witchhunter")  # Witchhunter belongs to Mercenary
    assert bad_asc["ok"] is False
    assert "Valid ascendancies" in bad_asc["error"]


def test_set_level(engine):
    engine.new_build()
    base = engine.get_stats(["Life"])["stats"]["Life"]
    r = engine.set_level(90)
    assert r["ok"] and r["level"] == 90
    assert r["stats"]["Life"] > base  # higher level => more life (auto-leveling disabled)


def test_get_build_readback(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Witchhunter")
    engine.set_level(90)
    engine.paste_skill("Detonate Living 20/0  1")
    b = engine.get_build()
    assert b["class"] == "Mercenary" and b["ascendancy"] == "Witchhunter" and b["level"] == 90
    assert b["mainSkill"] == "Detonate Living"


def test_list_config_options(engine):
    opts = engine.list_config_options(query="boss")["options"]
    assert any(o["var"] == "enemyIsBoss" for o in opts)


def test_equip_then_unequip(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    engine.add_item("Rarity: Rare\nR\nRuby Ring\n+50 to maximum Life")
    assert "Ring 1" in engine.get_build()["gear"]
    engine.unequip_item("Ring 1")
    assert "Ring 1" not in engine.get_build()["gear"]


def test_get_defenses(engine):
    engine.new_build()
    engine.set_class("Mercenary", "Witchhunter")
    engine.set_level(90)
    engine.paste_skill("Detonate Living 20/0  1")
    d = engine.get_defenses()
    assert d["life"] and d.get("note")
    assert set(d["resistances"]) == {"fire", "cold", "lightning", "chaos"}
    # The note must report the *actual* penalty (config default -60), not a hard-coded guess.
    # PoB nets that against a +10% elemental baseline, so a fresh elemental resist = penalty + 10.
    assert d["resistPenalty"] == -60
    assert d["resistances"]["fire"] == d["resistPenalty"] + 10


def test_points_available_scales_with_level(engine):
    engine.new_build()
    engine.set_level(90)
    a90 = engine.get_build()["pointsAvailable"]
    engine.set_level(20)
    a20 = engine.get_build()["pointsAvailable"]
    assert a90 > a20 > 0


def test_attack_skill_no_weapon_warning(engine):
    engine.new_build()
    engine.set_class("Monk", "Martial Artist")
    r = engine.paste_skill("Tempest Flurry 20/0  1")  # attack skill, no weapon
    assert r.get("warning") and "weapon" in r["warning"].lower()
    engine.add_item("Rarity: Rare\nX\nSteelpoint Quarterstaff\n120% increased Physical Damage")
    assert engine.get_stats(["TotalDPS"]).get("warning") is None  # cleared once armed


def test_optimize_balanced_raises_offense_and_defense(engine):
    engine.new_build()
    engine.set_class("Monk", "Martial Artist")
    engine.set_level(90)
    engine.paste_skill("Tempest Flurry 20/0  1")
    engine.add_item("Rarity: Rare\nX\nSteelpoint Quarterstaff\n120% increased Physical Damage")
    r = engine.optimize_passives(metric="balanced", points=12)
    assert r["finalDPS"] > r["startDPS"] and r["finalEHP"] > r["startEHP"]


def test_engine_reports_tree_version(engine):
    # the ready frame surfaces the passive-tree data version (used by engine_health)
    assert engine.info.get("treeVersion")


def test_engine_health_reports_versions():
    from server.main import engine_health

    h = engine_health()
    assert h["pong"] is True
    assert h["serverVersion"] and h["dataSource"] in {"bundled", "user-data"}
    assert h["treeVersion"]
