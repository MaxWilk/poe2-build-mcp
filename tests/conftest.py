"""Shared pytest fixtures.

The headless engine is expensive to start, so it's session-scoped and reused. The
`fireball` fixture resets to a known build (level-20 Fireball) before each test that needs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from server.compute import engine as _engine_mod  # noqa: E402
from server.compute.engine import PobEngine  # noqa: E402

# Engine-backed tests need the LuaJIT binary + PoB. CI/release install it; the scheduled data-refresh
# job (rebuilds the corpus but NOT the engine — it uses dev-branch PoB for fresh data, which would
# drift golden values) does not. So when LuaJIT is absent, SKIP the engine tests instead of erroring,
# letting that job still gate on the corpus/knowledge/pipeline tests it actually validates.
_DIRECT_ENGINE_TESTS = {
    "test_blank_luajit_override_is_ignored",
    "test_engine_health_reports_versions",
}


def _luajit_available() -> bool:
    try:
        _engine_mod._find_luajit()
        return True
    except Exception:  # noqa: BLE001 — FileNotFoundError when no binary on PATH/bundle
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _luajit_available():
        return
    skip = pytest.mark.skip(reason="LuaJIT/PoB engine unavailable (e.g. data-refresh CI)")
    for item in items:
        needs_engine = bool({"engine", "fireball"} & set(getattr(item, "fixturenames", ())))
        if needs_engine or item.name in _DIRECT_ENGINE_TESTS:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def engine():
    # Pin the engine to the REPO shim — paths.pob_headless_script() otherwise prefers an installed
    # user-data copy, which would shadow repo edits and make the suite test stale code.
    eng = PobEngine(script=_REPO_ROOT / "pob" / "pob_headless.lua")
    yield eng
    eng.close()


@pytest.fixture()
def fireball(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    return engine
