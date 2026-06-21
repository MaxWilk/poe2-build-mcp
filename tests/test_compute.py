"""Golden-value tests for the headless calculation engine + import codec.

Values are pinned to the PoB-PoE2 commit in pob/PINNED.md; if you bump the submodule and
these drift, re-verify against the GUI and update them in the same commit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.compute.engine import PobEngine
from server.compute.pob_code import decode_code, encode_code

FIREBALL_DPS = 124.833
FIREBALL_AVG = 149.8


def test_ping(engine):
    assert engine.ping()["pong"] is True


def test_fireball_golden(fireball):
    s = fireball.get_stats(["TotalDPS", "AverageDamage", "Speed"])["stats"]
    assert s["TotalDPS"] == pytest.approx(FIREBALL_DPS, rel=1e-3)
    assert s["AverageDamage"] == pytest.approx(FIREBALL_AVG, rel=1e-3)
    assert s["Speed"] == pytest.approx(0.8333, rel=1e-2)


def test_import_code_roundtrip(fireball):
    xml = fireball.get_xml()
    assert "PathOfBuilding2" in xml
    assert decode_code(encode_code(xml)) == xml


def test_import_reproduces_stats(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    xml = engine.get_xml()
    engine.new_build()
    res = engine.load_build_xml(xml)
    assert res["mainSkill"] == "Fireball"
    assert res["stats"]["TotalDPS"] == pytest.approx(FIREBALL_DPS, rel=1e-3)


def test_custom_mod_increases_dps(fireball):
    before = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    after = fireball.set_config(custom_mods="100% increased Fire Damage")["stats"]["TotalDPS"]
    assert after > before


def test_equip_item_returns_stats(fireball):
    res = fireball.add_item("New Item\nElementalist Robe")
    assert "TotalDPS" in res["stats"]


def test_equip_replaces_slot(fireball):
    craft = "Rarity: Rare\nWand\nAttuned Wand\n{}% increased Cast Speed".format
    fireball.add_item(craft(10))
    s1 = fireball.get_stats(["Speed"])["stats"]["Speed"]
    fireball.add_item(craft(25))  # same slot -> must replace, not be ignored
    s2 = fireball.get_stats(["Speed"])["stats"]["Speed"]
    assert s2 > s1


def test_import_code_fixture(engine):
    # A real build serialized through the actual codec; locks the import + codec + engine path.
    code = (Path(__file__).parent / "fixtures" / "witchhunter_detonate.pobcode").read_text().strip()
    engine.new_build()
    r = engine.load_build_code(code)
    assert r["mainSkill"] == "Detonate Living"
    b = engine.get_build()
    assert b["class"] == "Mercenary" and b["level"] == 90


def test_import_build_rejects_garbage():
    from server.main import import_build

    r = import_build("@@@ not a valid build @@@")
    assert r.get("ok") is False and "error" in r


def test_solve_for_reaches_target(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = solver.solve_for(fireball, "TotalDPS", base * 2, "increased fire damage")
    assert r["ok"] and r.get("reachable")
    assert r["requiredMagnitude"] > 0
    assert r["achievedValue"] >= base * 2 * 0.98  # within bisection tolerance
    # the build must be restored — no lingering custom mod from probing
    assert fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_damage_diagnostic_flags_buff_skill(engine):
    # A reservation/buff skill computes ~0 DPS by design; the diagnostic must say so (not silence).
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Plague Bearer 20/20  1")
    r = engine.get_stats(["TotalDPS"])
    assert (r["stats"].get("TotalDPS") or 0) == 0
    assert r.get("warning") and "buff/reservation" in r["warning"]


def _spark_caster(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n+5 to Level of all Lightning Spell Skills\n"
        "Adds 1 to 85 Lightning Damage to Spells\n112% increased Spell Damage"
    )


def test_paste_tolerates_missing_count(engine):
    # Supports written without the trailing count must not be silently dropped (#4).
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20\nLightning Penetration 20/20")
    names = [g["name"] for g in engine.get_build()["mainSkillGroup"]]
    assert "Controlled Destruction" in names and "Lightning Penetration" in names


def test_multiprojectile_dps_note(engine):
    # TotalDPS is per-projectile; a multi-projectile skill gets ProjectileCount + a dpsNote (#2).
    _spark_caster(engine)
    r = engine.paste_skill("Spark 20/20  1")
    assert (r["stats"].get("ProjectileCount") or 0) > 1
    assert r.get("dpsNote") and "projectile" in r["dpsNote"].lower()


def test_support_level_does_not_change_dps(engine):
    # PoE2 supports are fixed-effect (don't scale with gem level); level field is cosmetic (#3).
    _spark_caster(engine)
    lvl1 = engine.paste_skill("Spark 20/20  1\nControlled Destruction 1/20  1")["stats"]["TotalDPS"]
    _spark_caster(engine)
    lvl20 = engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")["stats"][
        "TotalDPS"
    ]
    assert lvl1 == pytest.approx(lvl20, rel=1e-6)


def test_add_skill_group_applies_aura_without_changing_main(engine):
    # A second enabled group (Archmage) must buff the main skill, not replace it (#1).
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    engine.set_config(custom_mods="+2000 to maximum Mana")
    before = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    engine.add_skill_group("Archmage 20/20  1")
    after = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    assert engine.get_build()["mainSkill"] == "Spark"  # main unchanged
    assert after > before * 1.2  # Archmage's mana-based damage applied


def test_optimize_passives_spends_more_via_small_pass(engine):
    # After the Notables pass plateaus, a second small/travel-node pass spends leftover budget the
    # old single pass stranded (#5). The greedy is deterministic now (stable candidate ordering),
    # so this is stable; remaining points on a gear-less skeleton are legitimately unplaceable.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    r = engine.optimize_passives(metric="balanced", points=0)
    assert r["smallNodePoints"] >= 1  # the small-node pass placed points Notables-only would strand
    assert r["pointsUsed"] >= 60  # a solid majority of the build's worthwhile nodes


def test_optimize_passives_is_deterministic(engine):
    # Stable candidate ordering -> identical allocation across runs (no pairs()-order drift). (#5)
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    first = engine.optimize_passives(metric="balanced", points=0)["pointsUsed"]
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")
    second = engine.optimize_passives(metric="balanced", points=0)["pointsUsed"]
    assert first == second


def test_eval_items_batches_and_restores(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    engine.add_item("Rarity: Rare\nOrig\nDueling Wand\n20% increased Spell Damage", slot="Weapon 1")
    base = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    cands = [
        "Rarity: Rare\nA\nDueling Wand\n150% increased Spell Damage",
        "Rarity: Rare\nB\nDueling Wand\n+5 to Level of all Lightning Spell Skills",
    ]
    res = engine.eval_items("Weapon 1", cands, keys=["TotalDPS"])["results"]
    assert all(r and r["TotalDPS"] > 0 for r in res)
    # build restored to the original item, not the last candidate
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_optimize_passives_weighted_goals(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item("Rarity: Rare\nW\nDueling Wand\n100% increased Spell Damage")
    engine.paste_skill("Spark 20/20  1")
    r = engine.optimize_passives(goals={"TotalDPS": 0.5, "Life": 0.5}, points=40)
    assert r["metric"] == "weighted"
    m = r["metrics"]
    assert (
        m["Life"]["final"] >= m["Life"]["start"] and m["TotalDPS"]["final"] > m["TotalDPS"]["start"]
    )


def test_optimize_passives_require_forces_node(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    r = engine.optimize_passives(metric="TotalDPS", points=20, require=["Eldritch Battery"])
    assert any(a.get("required") and a["name"] == "Eldritch Battery" for a in r["allocated"])
    assert r.get("requiredPoints", 0) > 0


def test_optimize_item_improves_and_is_valid(engine):
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nBasic\nDueling Wand\n20% increased Spell Damage", slot="Weapon 1"
    )
    engine.paste_skill("Spark 20/20  1\nControlled Destruction 20/20  1")  # non-crit
    base = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = itemopt.optimize_item(engine, "Weapon 1", metric="TotalDPS", rolls="max", thorough=True)
    assert r["ok"] and r["metricAfter"] > r["metricBefore"]
    assert len(r["affixes"]) <= 6  # respects 3 prefix / 3 suffix
    # build-aware: a non-crit lightning build's max-DPS wand uses a Lightning mod
    assert any("Lightning" in a for a in r["affixes"])
    # probing is restored
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_optimize_item_on_empty_weapon_slot_for_attack_skill(engine):
    # Regression: a from-scratch attack build optimizes the WEAPON slot first, before any weapon is
    # equipped. The skill is then uncomputable (DPS ~0) and the engine returns stats=[] (an empty Lua
    # table serializes to JSON [], not {}), which crashed optimize_item with "'list' object has no
    # attribute 'get'". It must instead craft a weapon and make DPS computable.
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")  # attack, no weapon -> uncomputable
    assert isinstance(
        engine.get_stats(["TotalDPS"])["stats"], dict
    )  # not [] even when uncomputable
    r = itemopt.optimize_item(engine, "Weapon 1", base="Grand Spear", metric="TotalDPS")
    assert r["ok"]
    assert r["metricBefore"] is None  # no weapon -> nothing to measure before
    assert isinstance(r["metricAfter"], (int, float)) and r["metricAfter"] > 0
    assert r["affixes"]  # crafted a real spear


def test_optimize_item_warns_when_it_breaks_resist_cap(engine):
    # Regression: the break check uses resistMissing (gap below the real per-element cap), NOT the
    # floored *ResistOverCap. PoB floors over-cap at 0, so the old "over-cap goes negative" check was
    # dead and the "drops resistance below cap" warning never fired.
    from server import scaffold
    from server.compute import itemopt

    engine.new_build()
    engine.set_class("Huntress", "Amazon")
    engine.set_level(95)
    engine.paste_skill("Lightning Spear 20/20  1")
    engine.add_item(
        "Rarity: Rare\nX\nGrand Spear\n--------\nAdds 40 to 80 Lightning Damage", slot="Weapon 1"
    )
    scaffold.scaffold_gear(engine, pool="life", target_resist=75)
    assert engine.get_defenses()["resistMissing"] == {"fire": 0, "cold": 0, "lightning": 0}
    # a max-DPS amulet carries no resistances, so replacing the scaffold amulet must break a cap
    r = itemopt.optimize_item(engine, "Amulet", metric="TotalDPS")
    assert any("below cap" in w for w in r["warnings"])


def test_new_build_resets(engine):
    # new_build clears gear/skills so a from-scratch build doesn't inherit a prior one's state.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.paste_skill("Spark 20/20  1")
    engine.add_item("Rarity: Rare\nW\nDueling Wand\n100% increased Spell Damage", slot="Weapon 1")
    engine.new_build()
    b = engine.get_build()
    assert not b.get("gear") and not b.get("mainSkill")


def test_boss_tier_sets_enemy_resistance(engine):
    # Setting the boss tier applies that tier's enemy elemental resistance (PoB only sets it as a
    # GUI placeholder otherwise); harder tiers => lower computed DPS for an elemental skill.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\n+5 to Level of all Lightning Spell Skills\n"
        "Adds 1 to 85 Lightning Damage to Spells\n100% increased Spell Damage"
    )
    engine.paste_skill("Spark 20/20  1")
    r = engine.set_config(options={"enemyIsBoss": "Boss"})
    assert r.get("enemyResist", {}).get("lightning") == 30
    boss = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    engine.set_config(options={"enemyIsBoss": "Pinnacle"})  # 50% res
    pinn = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    assert pinn < boss  # a tankier tier computes lower DPS


def test_alloc_passive_warns_over_budget(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    engine.optimize_passives(metric="balanced", points=0)
    engine.set_level(40)  # filled tree now exceeds the smaller budget
    cand = [
        n
        for n in engine.search_passives(query="", node_type="Notable", limit=300)["results"]
        if not n.get("alloc") and (n.get("pathDist") or 99) <= 2
    ]
    a = engine.alloc_passive(cand[0]["id"])
    assert a.get("warning") and "over budget" in a["warning"]


def test_unmodeled_skill_surfaced(engine):
    # Mana Tempest's empower isn't modeled by PoB; the engine must say so (DPS understated).
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    engine.add_skill_group("Mana Tempest 20/20  1")
    r = engine.get_stats(["TotalDPS"])
    assert r.get("engineNote") and "Mana Tempest" in r["engineNote"]


def test_equip_bad_base_returns_error_not_crash(engine):
    # An unrecognized base must not surface a raw Lua traceback (#7).
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    r = engine.add_item(
        "Rarity: Rare\nPhantom String\nNot A Real Bow Base\nAdds 50 to 90 Physical Damage"
    )
    assert r.get("ok") is False and "base" in (r.get("error") or "").lower()


def test_attack_rate_binds_to_weapon(engine):
    # Regression for the friend's frozen-Speed report: a bow attack's Speed responds to +attack
    # speed (the weapon's rate binds to the skill). #1-3 were a broken-weapon downstream effect.
    engine.new_build()
    engine.set_class("Ranger", "Deadeye")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nB\nFanatic Bow\nAdds 40 to 75 Physical Damage\n38% increased Attack Speed",
        slot="Weapon 1",
    )
    engine.paste_skill("Ice Shot 20/20  1")
    base = engine.get_stats(["Speed"])["stats"]["Speed"]
    fast = engine.set_config(custom_mods="100% increased Attack Speed")["stats"]["Speed"]
    assert base > 0 and fast == pytest.approx(base * 2, rel=0.05)


def test_multiprojectile_note_frames_shotgun_as_per_skill(engine):
    # The dpsNote must NOT claim PoE2 "has no shotgunning" (false — overlap is per-skill) and must
    # NOT tell users to multiply TotalDPS by projectile count. It should frame overlap as per-skill
    # and tell the reader to verify. (#4-5 wrong-advice regression guard.)
    _spark_caster(engine)
    r = engine.paste_skill("Spark 20/20  1")
    note = (r.get("dpsNote") or "").lower()
    assert note  # Spark fires many projectiles -> note present
    assert "multiple of this" not in note  # not the old "effective DPS is a multiple" advice
    assert "no shotgun" not in note  # must NOT claim PoE2 has no shotgunning
    assert "per-skill" in note  # frames overlap/shotgun as per-skill
    assert "verify" in note  # tells the reader to verify, not assume


def test_solver_levers(engine):
    from server.compute import solver

    # #6: no "increased increased" double-prefix; named levers expand correctly
    assert solver._template_for("increased projectile damage") == "{}% increased Projectile Damage"
    assert "{0}" in solver._template_for("added cold damage")
    assert "Critical Damage Bonus" in solver._template_for("critical strike multiplier")
    names = solver.list_levers()["levers"]
    assert "increased projectile damage" in names and len(names) > 20


def test_damage_diagnostic_silent_when_computable(engine):
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    engine.paste_skill("Fireball 20/20  1")
    r = engine.get_stats(["TotalDPS"])
    assert (r["stats"].get("TotalDPS") or 0) > 0
    assert not r.get("warning")  # a computable build gets no false positive


def test_get_build_surfaces_unspent_points(engine):
    engine.new_build()
    engine.set_class("Witch", "Infernalist")
    engine.set_level(90)
    b = engine.get_build()
    assert b["pointsAvailable"] == 113  # 89 (level-1) + 24 campaign quest points
    assert b["unspentPoints"] == b["pointsAvailable"] - b["pointsUsed"]
    assert "pointsNote" in b  # a fresh tree flags its many unspent points


def test_rank_levers_marginal_gain(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = solver.rank_levers(fireball, metric="TotalDPS", unit=10)
    assert r["ok"] and r["levers"]
    gains = [lv["gain"] for lv in r["levers"]]
    assert gains == sorted(gains, reverse=True)  # ranked high -> low
    by = {lv["lever"]: lv["gain"] for lv in r["levers"]}
    # a damage lever helps DPS more than a pure-life lever
    assert by["{}% increased Damage"] > by["+{} to maximum Life"]
    # probing is restored
    assert fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(base, rel=1e-6)


def test_solve_for_already_met(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = solver.solve_for(fireball, "TotalDPS", base * 0.5, "increased fire damage")
    assert r["ok"] and r["alreadyMet"] and r["requiredMagnitude"] == 0.0


def test_solve_for_noop_lever_detected(fireball):
    from server.compute import solver

    base = fireball.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    # cold damage does nothing for a pure-fire Fireball — must be flagged, not "unreachable"
    r = solver.solve_for(fireball, "TotalDPS", base * 2, "increased cold damage")
    assert r["ok"] is False and "does not move" in r["error"]


def test_set_skill_accepts_inline_separators(engine):
    # The natural " / " (and ",") form must apply EVERY support, not just the first gem (the silent
    # support-drop / "Elemental Storm" corruption bug). Bare support names are tolerated too.
    _spark_caster(engine)
    r = engine.paste_skill("Spark 20/20 1 / Controlled Destruction / Lightning Penetration")
    names = [g["name"] for g in engine.get_build()["mainSkillGroup"]]
    assert r["mainSkill"] == "Spark"
    assert "Controlled Destruction" in names and "Lightning Penetration" in names


def test_set_skill_replaces_main_group(engine):
    # set_skill REPLACES the main group (no pile-up) yet preserves aura groups from add_skill_group.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20 1")
    engine.add_skill_group("Archmage 20/20 1")
    n_after_aura = engine.get_build()["skillGroupCount"]
    for _ in range(3):
        engine.paste_skill("Spark 20/20 1 / Controlled Destruction")
    b = engine.get_build()
    assert b["skillGroupCount"] == n_after_aura  # repeated calls did not accumulate stale groups
    assert b["mainSkill"] == "Spark"


def test_set_skill_unknown_gem_leaves_build_unchanged(engine):
    # A bogus gem name must not silently corrupt the main skill — roll back + report (#set_skill).
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20 1")
    before = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    r = engine.paste_skill("Notaskill Foobar 20/20 1")
    assert r.get("ok") is False
    after = engine.get_build()
    assert after["mainSkill"] == "Spark"  # unchanged
    assert engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"] == pytest.approx(before, rel=1e-6)


def test_set_skill_recovers_after_bad_input(engine):
    # The exact failure path from the test session: a bad paste must not wedge set_skill — a
    # subsequent good paste recovers the main skill with all supports.
    _spark_caster(engine)
    engine.paste_skill("Spark 20/20 1")
    engine.paste_skill("Notaskill 20/20 1")  # rejected, build unchanged
    r = engine.paste_skill("Spark 20/20 1 / Controlled Destruction / Lightning Penetration")
    names = [g["name"] for g in engine.get_build()["mainSkillGroup"]]
    assert r["mainSkill"] == "Spark"
    assert "Controlled Destruction" in names and "Lightning Penetration" in names


def test_jewel_sockets_and_equip(engine):
    # list_jewel_sockets enumerates tree sockets; equip_jewel into an ALLOCATED socket applies its
    # mods (mana rises), and auto-pick fails cleanly when nothing is allocated.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    socks = engine.list_jewel_sockets()["sockets"]
    assert socks and all({"socket", "allocated", "filled"} <= set(s) for s in socks)
    # nothing allocated yet -> auto-pick reports cleanly instead of wasting the jewel
    assert engine.equip_jewel("Rarity: Rare\nTJ\nSapphire\n+50 to maximum Mana")["ok"] is False
    sid = socks[0]["socket"]
    assert engine.call("alloc_passive", node=sid).get("ok")
    mana0 = engine.get_stats(["Mana"])["stats"]["Mana"]
    r = engine.equip_jewel("Rarity: Rare\nTJ\nSapphire\n+50 to maximum Mana", socket=sid)
    assert r["ok"] and not r.get("warning")
    assert engine.get_stats(["Mana"])["stats"]["Mana"] > mana0  # jewel's mana applied


def test_equip_jewel_warns_on_unallocated_socket(engine):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.paste_skill("Spark 20/20  1")
    sid = engine.list_jewel_sockets()["sockets"][0]["socket"]  # unallocated
    r = engine.equip_jewel("Rarity: Rare\nTJ\nSapphire\n+50 to maximum Mana", socket=sid)
    assert r["ok"] and r.get("warning") and "not allocated" in r["warning"].lower()


def test_add_skill_group_in_full_dps_aggregates(engine):
    # A second DAMAGE skill flagged in_full_dps aggregates into FullDPS (clear+boss); without the
    # flag (auras) it would not. Here a second Spark roughly doubles FullDPS over one skill.
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(90)
    engine.add_item(
        "Rarity: Rare\nW\nDueling Wand\nAdds 1 to 85 Lightning Damage to Spells\n"
        "100% increased Spell Damage"
    )
    engine.paste_skill("Spark 20/20  1")
    total = engine.get_stats(["TotalDPS"])["stats"]["TotalDPS"]
    engine.add_skill_group("Spark 20/20  1", include_in_full_dps=True)
    full = engine.get_stats(["FullDPS"])["stats"]["FullDPS"]
    assert full > total * 1.5  # the second damage skill aggregated into FullDPS


def test_set_skill_computes_full_dps(engine):
    # FullDPS is off by default in PoB (only summed for groups flagged "include in Full DPS").
    # set_skill now flags the main group, so FullDPS is computed — equal to TotalDPS for a single
    # skill, and the basis for an apples-to-apples comparison against imported multi-skill builds.
    _spark_caster(engine)
    s = engine.paste_skill("Spark 20/20  1")["stats"]
    assert (s.get("FullDPS") or 0) > 0
    assert s["FullDPS"] == pytest.approx(s["TotalDPS"], rel=1e-2)


def test_rank_levers_tolerates_multi_placeholder(fireball):
    # A lever template with TWO "{}" (e.g. "Adds {} to {} ... Damage") must not crash (#rank_levers).
    from server.compute import solver

    r = solver.rank_levers(
        fireball,
        metric="TotalDPS",
        unit=10,
        levers=["Adds {} to {} Fire Damage to Spells", "{}% increased Fire Damage"],
    )
    assert r["ok"] and len(r["levers"]) == 2


def test_blank_luajit_override_is_ignored(monkeypatch):
    # A manifest user-config left blank arrives as a non-existent path (e.g. the literal
    # "${user_config.luajit_path}"); it must not shadow the bundled/system LuaJIT.
    monkeypatch.setenv("POB_LUAJIT", "${user_config.luajit_path}")
    eng = PobEngine()
    try:
        assert eng.ping()["pong"] is True
    finally:
        eng.close()
