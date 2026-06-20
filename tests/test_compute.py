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
    assert r["ok"] is False and "does not affect" in r["error"]


def test_blank_luajit_override_is_ignored(monkeypatch):
    # A manifest user-config left blank arrives as a non-existent path (e.g. the literal
    # "${user_config.luajit_path}"); it must not shadow the bundled/system LuaJIT.
    monkeypatch.setenv("POB_LUAJIT", "${user_config.luajit_path}")
    eng = PobEngine()
    try:
        assert eng.ping()["pong"] is True
    finally:
        eng.close()
