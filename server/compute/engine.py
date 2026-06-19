"""Python client for the headless PoB-PoE2 calculation engine.

Spawns LuaJIT running ``pob/pob_headless.lua`` as a long-lived subprocess and talks to
it over a line-delimited JSON-RPC protocol on stdin/stdout. The engine loads its (large)
game data exactly once at startup, then answers many calls cheaply — which is why it's a
persistent process rather than a per-call invocation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from .. import paths

_LUAJIT_FALLBACKS = (
    r"C:\msys64\ucrt64\bin\luajit.exe",
    r"C:\msys64\mingw64\bin\luajit.exe",
)


class PobEngineError(RuntimeError):
    """Raised when the engine fails to start or returns an error for a call."""


def _find_luajit() -> str:
    override = os.environ.get("POB_LUAJIT")
    if override:
        return override
    bundled = paths.bundled_luajit()
    if bundled:
        return str(bundled)
    found = shutil.which("luajit")
    if found:
        return found
    for cand in _LUAJIT_FALLBACKS:
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("luajit not found on PATH; set the POB_LUAJIT environment variable.")


class PobEngine:
    """A long-lived headless PoB engine process."""

    def __init__(
        self,
        luajit: str | None = None,
        src_dir: str | os.PathLike[str] | None = None,
        script: str | os.PathLike[str] | None = None,
        show_engine_logs: bool = False,
    ) -> None:
        self.luajit = luajit or _find_luajit()
        self.src_dir = Path(src_dir) if src_dir else paths.pob_src_dir()
        self.script = Path(script) if script else paths.pob_headless_script()
        if not self.src_dir.is_dir():
            raise FileNotFoundError(f"PoB src dir not found: {self.src_dir}")
        if not self.script.is_file():
            raise FileNotFoundError(f"headless script not found: {self.script}")

        stderr = None if show_engine_logs else subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [self.luajit, str(self.script)],
            cwd=str(self.src_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._next_id = 0
        self._lock = threading.Lock()
        ready = self._read_frame()
        if not ready.get("ready"):
            raise PobEngineError(f"engine failed to initialise: {ready}")
        self.info: dict[str, Any] = ready

    # -- low-level I/O -------------------------------------------------------
    def _read_frame(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if line == "":
                code = self.proc.poll()
                raise PobEngineError(f"engine exited (code={code}) before responding")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                # Defensive: skip any stray non-JSON line on stdout.
                continue

    def call(self, method: str, **params: Any) -> Any:
        if self.proc.poll() is not None:
            raise PobEngineError(f"engine is not running (code={self.proc.returncode})")
        assert self.proc.stdin is not None
        # One request/response pair must not interleave with another.
        with self._lock:
            self._next_id += 1
            request = {"id": self._next_id, "method": method, "params": params}
            self.proc.stdin.write(json.dumps(request) + "\n")
            self.proc.stdin.flush()
            resp = self._read_frame()
        if not resp.get("ok"):
            raise PobEngineError(resp.get("error", "unknown engine error"))
        return resp["result"]

    # -- convenience wrappers ------------------------------------------------
    def ping(self) -> dict[str, Any]:
        return self.call("ping")

    def new_build(self) -> dict[str, Any]:
        return self.call("new_build")

    def load_build_xml(self, xml: str, name: str = "imported") -> dict[str, Any]:
        return self.call("load_build_xml", xml=xml, name=name)

    def paste_skill(self, text: str) -> dict[str, Any]:
        return self.call("paste_skill", text=text)

    def get_stats(self, keys: list[str] | None = None) -> dict[str, Any]:
        return self.call("get_stats", keys=keys)

    def set_config(
        self,
        options: dict[str, Any] | None = None,
        custom_mods: str | None = None,
        keys: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if options:
            params["options"] = options
        if custom_mods is not None:
            params["customMods"] = custom_mods
        if keys is not None:
            params["keys"] = keys
        return self.call("set_config", **params)

    def add_item(self, raw: str, keys: list[str] | None = None) -> dict[str, Any]:
        return self.call("add_item", raw=raw, keys=keys)

    def search_passives(
        self, query: str = "", node_type: str | None = None, limit: int = 30
    ) -> dict[str, Any]:
        return self.call("search_passives", query=query, node_type=node_type, limit=limit)

    def get_passive(self, node: str | int) -> dict[str, Any]:
        return self.call("get_passive", node=node)

    def alloc_passive(self, node: str | int) -> dict[str, Any]:
        return self.call("alloc_passive", node=node)

    def dealloc_passive(self, node: str | int) -> dict[str, Any]:
        return self.call("dealloc_passive", node=node)

    def optimize_passives(
        self,
        metric: str = "TotalDPS",
        points: int = 3,
        node_type: str = "Notable",
        candidates: int = 50,
    ) -> dict[str, Any]:
        return self.call(
            "optimize_passives",
            metric=metric,
            points=points,
            node_type=node_type,
            candidates=candidates,
        )

    def get_xml(self) -> str:
        return self.call("get_xml")["xml"]

    def load_build_code(self, code: str, name: str = "imported") -> dict[str, Any]:
        """Import a PoB share code (inflated to XML in Python, then loaded)."""
        from .pob_code import decode_code

        return self.load_build_xml(decode_code(code), name=name)

    def load_build_link(self, url: str, name: str = "imported") -> dict[str, Any]:
        """Import a pobb.in / pastebin build link (network)."""
        from .pob_code import to_xml

        return self.load_build_xml(to_xml(url), name=name)

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def __enter__(self) -> "PobEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
