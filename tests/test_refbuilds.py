"""Reference / calibration build library — pure-data tests (no engine needed)."""

from __future__ import annotations

from collections import Counter

from server.knowledge import refbuilds


def test_reference_library_loads():
    r = refbuilds.search(limit=50)
    assert r["totalAvailable"] >= 12, "expected a diverse bundled reference set"
    assert r["builds"]
    assert r["treeVersion"], (
        "reference data should be stamped with the tree version it was verified on"
    )


def test_reference_output_has_nothing_to_copy():
    # The anti-copy invariant: a reference record exposes verified numbers + archetype tags + the
    # scaling lever, but NO code/gear/passive list someone could paste into a build.
    forbidden = (
        "code",
        "xml",
        "gear",
        "items",
        "passives",
        "tree",
        "supports",
        "keystones",
        "nodes",
    )
    for b in refbuilds.search(limit=50)["builds"]:
        for key in forbidden:
            assert key not in b, f"reference record leaks copyable field {key!r}"
        v = b["verified"]
        assert v["TotalDPS"] is None or v["TotalDPS"] > 0


def test_reference_note_is_calibration_only():
    note = refbuilds.search()["note"].lower()
    assert "calibration" in note and "never" in note and "copy" in note


def test_search_filters_by_query():
    res = refbuilds.search("chronomancer", limit=50)["builds"]
    assert res and any((b.get("ascendancy") or "").lower() == "chronomancer" for b in res)
    spell = refbuilds.search("spell", limit=50)["builds"]
    assert spell and any("spell" in (b.get("delivery") or []) for b in spell)


def test_plus_levels_is_the_dominant_lever():
    # Headline finding: across verified high-end builds, "+levels to skills" is the #1 scaler.
    builds = refbuilds._data()["builds"]
    levers = Counter(b.get("dominantLever") for b in builds if b.get("dominantLever"))
    top, _ = levers.most_common(1)[0]
    assert top.startswith("+N to Level"), f"expected +levels dominant, got {top!r} ({levers})"


def test_benchmark_places_active_build_and_calibrates():
    weak = refbuilds.benchmark(total_dps=50_000, full_dps=0, ehp=8_000, delivery=["spell"])
    assert "calibration" in weak["note"].lower()
    assert weak["dps"]["placement"] == "BELOW the reference range"
    assert weak["dps"]["reference"] and weak["ehp"]["reference"]
    assert weak["archetypeDominantLevers"]
    strong = refbuilds.benchmark(total_dps=99_000_000, full_dps=0, ehp=999_999, delivery=["spell"])
    assert strong["dps"]["placement"] == "ABOVE the reference range"
