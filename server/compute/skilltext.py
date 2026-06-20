"""Normalize user-typed skill-gem text into Path of Building's strict paste format.

PoB's socket-group paste parser needs ONE GEM PER LINE in the form ``Name level/quality count``
and silently drops any line it can't match — so a natural inline list like
``Arc 20/20 1 / Lightning Penetration / Inspiration`` loses every support. This module makes the
forgiving forms work by (a) splitting the inline separators people actually type (`` / ``, `` | ``,
``, ``) onto their own lines — without touching the ``20/20`` level/quality slash, which has no
surrounding spaces — and (b) giving bare gem names a default ``20/20 1`` and countless gem lines a
trailing ``1`` (supports are fixed-effect in PoE2, so the level/quality is cosmetic).
"""

from __future__ import annotations

import re

_SEP_SLASH = re.compile(
    r"\s+/\s+"
)  # " / " gem separator; never matches the spaceless "20/20" slash
_SEP_PIPE = re.compile(r"\s*\|\s*")
_SEP_COMMA = re.compile(r"\s*,\s*")
_LQ = re.compile(r"\b\d+/\d+\b")  # a level/quality token
_BARE_NAME = re.compile(r"^[A-Za-z][A-Za-z'. ]*$")  # gem name only (letters/space/'/. , no digits)
_HEADER = re.compile(r"^(Label|Slot)\s*:", re.IGNORECASE)


def normalize_skill_text(text: str) -> str:
    """Return `text` reshaped into PoB's one-gem-per-line paste format (idempotent)."""
    if not text:
        return text
    t = _SEP_SLASH.sub("\n", text)
    t = _SEP_PIPE.sub("\n", t)
    t = _SEP_COMMA.sub("\n", t)
    out: list[str] = []
    for raw in t.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _HEADER.match(line):
            out.append(line)
            continue
        m = _LQ.search(line)
        if m:
            # Has level/quality; ensure a trailing instance count so PoB doesn't drop the line.
            if not re.search(r"\d", line[m.end() :]):
                line = line + "  1"
            out.append(line)
        elif _BARE_NAME.match(line):
            # A bare gem name (e.g. "Lightning Penetration") — give it the default L/Q + count.
            out.append(line + " 20/20 1")
        else:
            out.append(line)
    return "\n".join(out)
