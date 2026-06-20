"""Pure-Python tests for skill-text normalization and lever-template filling (no engine needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.compute.skilltext import normalize_skill_text  # noqa: E402
from server.compute.solver import _apply_template  # noqa: E402


def test_slash_separated_becomes_one_gem_per_line():
    out = normalize_skill_text("Arc 20/20 1 / Lightning Penetration / Inspiration")
    assert out.splitlines() == [
        "Arc 20/20 1",
        "Lightning Penetration 20/20 1",
        "Inspiration 20/20 1",
    ]


def test_level_quality_slash_is_not_split():
    # "20/20" must survive — only the surrounded " / " separator is a gem boundary.
    assert "20/20" in normalize_skill_text("Fireball 20/20")
    assert normalize_skill_text("Fireball 20/20") == "Fireball 20/20  1"  # count appended


def test_mixed_separators_and_bare_names():
    out = normalize_skill_text("Arc, Rising Tempest | Inspiration")
    assert out.splitlines() == [
        "Arc 20/20 1",
        "Rising Tempest 20/20 1",
        "Inspiration 20/20 1",
    ]


def test_already_canonical_is_stable_idempotent():
    canonical = "Spark 20/0  1"
    assert normalize_skill_text(canonical) == canonical
    assert normalize_skill_text(normalize_skill_text(canonical)) == canonical


def test_apply_template_multiple_placeholders():
    # The crash case: two "{}" must both fill instead of raising "Replacement index out of range".
    assert _apply_template("Adds {} to {} Lightning Damage to Spells", 10) == (
        "Adds 10 to 10 Lightning Damage to Spells"
    )
    assert _apply_template("{}% increased Lightning Damage", 10) == "10% increased Lightning Damage"
    assert _apply_template("+{} to maximum Life", 25) == "+25 to maximum Life"
