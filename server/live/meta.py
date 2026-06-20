"""Live PoE2 build meta (ascendancy popularity) via poe.ninja's public build-index API.

This is a *usage snapshot* of logged top-ladder characters by ascendancy — popularity, NOT a
recommendation (popular != optimal). It covers ascendancy distribution only; poe.ninja's
per-skill/per-item breakdown lives behind a protobuf endpoint we don't consume. Read-only;
refreshes upstream roughly hourly. Degrades gracefully if poe.ninja is unreachable.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .. import paths

URL = "https://poe.ninja/poe2/api/data/build-index-state"
# poe.ninja's edge rejects some non-browser clients, so present a browser-like UA.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36 poe2-build-mcp"
    ),
    "Accept": "application/json",
    "Referer": "https://poe.ninja/poe2/builds",
}


class MetaError(RuntimeError):
    """Raised when the meta API can't be reached or returns an error."""


def _fetch() -> Any:
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001 - normalize to one error type
        raise MetaError(f"poe.ninja build-index request failed: {e}") from e


def _trend(v: Any) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return "flat"
    return "rising" if n > 0 else "falling" if n < 0 else "flat"


def _is_main_league(name: str) -> bool:
    """True for the main softcore challenge league (not HC/SSF/Standard/Ruthless)."""
    n = (name or "").lower()
    if n.startswith("hc ") or n.startswith("ssf "):
        return False
    return not any(k in n for k in ("hardcore", "ssf", "standard", "ruthless"))


def _select(leagues: list[dict], override: str | None) -> dict | None:
    if override:
        lo = override.lower()
        return next(
            (
                lb
                for lb in leagues
                if lo in ((lb.get("leagueName") or "").lower(), (lb.get("leagueUrl") or "").lower())
            ),
            None,
        )
    for lb in leagues:  # default: the main softcore challenge league
        if _is_main_league(lb.get("leagueName") or ""):
            return lb
    return leagues[0] if leagues else None


def shape(data: Any, league: str | None = None, limit: int = 15) -> dict[str, Any]:
    """Format raw build-index-state into an ascendancy-popularity summary (no network)."""
    leagues = (data or {}).get("leagueBuilds") or []
    available = [lb.get("leagueName") for lb in leagues]
    if not leagues:
        return {"ok": False, "error": "no league build data available"}
    chosen = _select(leagues, league)
    if chosen is None:
        return {"ok": False, "error": f"league {league!r} not found", "leaguesAvailable": available}
    stats = sorted(
        (chosen.get("statistics") or []), key=lambda s: s.get("percentage") or 0, reverse=True
    )
    return {
        "ok": True,
        "source": "poe.ninja",
        "kind": "ascendancy_popularity",
        "league": chosen.get("leagueName"),
        "sampleSize": chosen.get("total"),
        "ascendancies": [
            {
                "ascendancy": s.get("class"),
                "percentage": round(s.get("percentage") or 0, 2),
                "trend": _trend(s.get("trend")),
            }
            for s in stats[: max(1, limit)]
        ],
        "leaguesAvailable": available,
        "note": (
            "Popularity among logged top-ladder characters — NOT a recommendation. Popular is "
            "not the same as optimal or right for the player's goal. Use it as context only; "
            "this is ascendancy distribution ONLY (no skill/item/build data). For a build-level "
            "meta comparison, find one (web-search a pobb.in/pastebin link), load it with "
            "import_build, and compare numbers on the engine. Verify any build with the engine."
        ),
    }


def _cache_path():
    return paths.user_data_dir() / "meta_cache.json"


def _write_cache(data: Any) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "data": data,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _read_cache() -> dict | None:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def get_meta_builds(league: str | None = None, limit: int = 15) -> dict[str, Any]:
    """Ascendancy popularity for a league (default the current challenge league).

    On a successful fetch the snapshot is cached; if poe.ninja is later unreachable we fall back
    to that last-good snapshot (flagged `stale`) instead of returning nothing.
    """
    try:
        data = _fetch()
    except MetaError:
        cached = _read_cache()
        if cached and cached.get("data"):
            r = shape(cached["data"], league=league, limit=limit)
            if r.get("ok"):
                r["stale"] = True
                r["fetchedAt"] = cached.get("fetched_at")
                r["note"] = "poe.ninja unreachable — last cached snapshot (may be stale). " + r.get(
                    "note", ""
                )
            return r
        raise
    _write_cache(data)
    return shape(data, league=league, limit=limit)
