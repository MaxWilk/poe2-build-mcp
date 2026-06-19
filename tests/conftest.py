"""Shared pytest fixtures.

The headless engine is expensive to start, so it's session-scoped and reused. The
`fireball` fixture resets to a known build (level-20 Fireball) before each test that needs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.compute.engine import PobEngine  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    eng = PobEngine()
    yield eng
    eng.close()


@pytest.fixture()
def fireball(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    return engine
