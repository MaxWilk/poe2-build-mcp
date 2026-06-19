"""Self-update from our validated GitHub releases.

A release publishes ``update-manifest.json`` plus ``corpus.sqlite`` and ``pob-engine.zip``
(a golden-test-gated PoB snapshot). Updates install into the user-data dir, which is preferred
over the bundled seed (see paths.py). Per project policy, the engine only ever updates from
these pre-tested releases — never live upstream.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import paths
from ..knowledge import db

MANIFEST_URL = os.environ.get(
    "POE2_MCP_MANIFEST_URL",
    "https://github.com/MaxWilk/poe2-build-mcp/releases/latest/download/update-manifest.json",
)
CHECK_INTERVAL_SECONDS = 24 * 3600
UA = {"User-Agent": "poe2-build-mcp-updater/0.1"}


def _vkey(version: str) -> tuple[int, ...]:
    """Numeric version key so v0.10.0 > v0.2.0 (lexicographic compare would get this wrong)."""
    return tuple(int(n) for n in re.findall(r"\d+", version or "")) or (0,)


def _http(url: str, timeout: float = 60.0) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _bundle_version() -> str:
    f = paths.BUNDLE_ROOT / "data" / "VERSION"
    return f.read_text().strip() if f.exists() else "0"


def installed_version() -> str:
    f = paths.user_data_dir() / "installed.json"
    if f.exists():
        try:
            return json.loads(f.read_text()).get("version") or _bundle_version()
        except Exception:  # noqa: BLE001
            return _bundle_version()
    return _bundle_version()


def _fetch_manifest() -> dict | None:
    try:
        return json.loads(_http(MANIFEST_URL, timeout=15))
    except Exception:  # noqa: BLE001
        return None


def check_for_updates() -> dict[str, Any]:
    """Is a newer validated release (engine + corpus) available?"""
    current = installed_version()
    manifest = _fetch_manifest()
    if not manifest:
        return {
            "available": False,
            "current_version": current,
            "reason": "no release manifest reachable (no published release yet?)",
        }
    latest = str(manifest.get("version", "0"))
    return {
        "available": _vkey(latest) > _vkey(current),
        "current_version": current,
        "latest_version": latest,
        "pob_commit": manifest.get("pob_commit"),
    }


def _verify(blob: bytes, sha: str | None) -> bool:
    return (not sha) or hashlib.sha256(blob).hexdigest() == sha


def apply_updates(force: bool = False) -> dict[str, Any]:
    """Download + install the latest validated release into the user-data dir."""
    manifest = _fetch_manifest()
    if not manifest:
        return {"updated": False, "reason": "no release manifest reachable"}
    latest = str(manifest.get("version", "0"))
    current = installed_version()
    if not force and _vkey(latest) <= _vkey(current):
        return {"updated": False, "reason": "already up to date", "version": current}

    data_dir = paths.user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    corpus = manifest.get("corpus") or {}
    if corpus.get("url"):
        blob = _http(corpus["url"])
        if not _verify(blob, corpus.get("sha256")):
            return {"updated": False, "error": "corpus checksum mismatch"}
        db.reset()  # release the read handle before replacing the file
        tmp = data_dir / "corpus.sqlite.tmp"
        tmp.write_bytes(blob)
        os.replace(tmp, data_dir / "corpus.sqlite")

    engine = manifest.get("engine") or {}
    if engine.get("url"):
        blob = _http(engine["url"])
        if not _verify(blob, engine.get("sha256")):
            return {"updated": False, "error": "engine checksum mismatch"}
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "engine.zip"
            zpath.write_bytes(blob)
            extract = Path(td) / "x"
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(extract)
            src_pob = extract / "pob"
            dst_pob = data_dir / "pob"
            if src_pob.is_dir():
                if dst_pob.exists():
                    shutil.rmtree(dst_pob)
                shutil.move(str(src_pob), str(dst_pob))

    (data_dir / "installed.json").write_text(
        json.dumps({"version": latest, "pob_commit": manifest.get("pob_commit")})
    )
    return {"updated": True, "version": latest}


def auto_update(on_applied: Callable[[], None] | None = None) -> None:
    """Throttled, best-effort startup update. Safe to run in a daemon thread."""
    if os.environ.get("POE2_MCP_NO_AUTOUPDATE"):
        return
    try:
        marker = paths.user_data_dir() / "last_check"
        now = time.time()
        if marker.exists():
            try:
                if now - float(marker.read_text().strip()) < CHECK_INTERVAL_SECONDS:
                    return
            except Exception:  # noqa: BLE001
                pass
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(now))
        if check_for_updates().get("available"):
            res = apply_updates()
            if res.get("updated") and on_applied:
                on_applied()
    except Exception:  # noqa: BLE001 - auto-update must never break the server
        pass
