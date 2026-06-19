"""Golden-value tests for the headless calculation engine + import codec.

Values are pinned to the PoB-PoE2 commit in pob/PINNED.md; if you bump the submodule and
these drift, re-verify against the GUI and update them in the same commit.
"""

from __future__ import annotations

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


def test_blank_luajit_override_is_ignored(monkeypatch):
    # A manifest user-config left blank arrives as a non-existent path (e.g. the literal
    # "${user_config.luajit_path}"); it must not shadow the bundled/system LuaJIT.
    monkeypatch.setenv("POB_LUAJIT", "${user_config.luajit_path}")
    eng = PobEngine()
    try:
        assert eng.ping()["pong"] is True
    finally:
        eng.close()
