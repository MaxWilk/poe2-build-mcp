# Packaging & self-update

## Self-contained bundle

[scripts/build_bundle.py](scripts/build_bundle.py) assembles a self-contained `.mcpb` and is
run per-OS by [.github/workflows/release.yml](.github/workflows/release.yml). A bundle contains:

- `server/` — the MCP server. `server/__init__.py` activates the vendored `lib/` as a *site*
  dir (prepended for precedence, `addsitedir` so `.pth` hooks like pywin32's native DLL setup run).
- `lib/` — vendored Python dependencies (per-OS; compiled wheels like `pydantic-core` and
  `pywin32` are platform-specific, which is why bundles are built on each OS).
- `pob/` — the PoB engine subset (`PathOfBuilding-PoE2/src`, `runtime/lua`, `pob_headless.lua`).
- `data/corpus.sqlite` + `data/VERSION` — the bundled seed corpus.
- `runtime/luajit/<platform>/luajit[.exe]` — LuaJIT, built from source in CI (the PoB-pinned
  commit). `server/paths.py` auto-detects it.

The Python side has been validated to run from the bundle with no repo/venv on the path; LuaJIT
is supplied per-OS by the release workflow. Bundles are large (~400 MB) because they embed PoB's
game data — updates ship as deltas via releases (below).

Build locally (LuaJIT optional; falls back to a system LuaJIT if not vendored):

```sh
uv run python scripts/build_bundle.py --version 2026.06.19
# -> dist/poe2-build-mcp-<platform>.mcpb
```

> The release workflow needs a first real run to shake out per-OS specifics (notably the
> Windows LuaJIT DLL set and macOS arm64 wheels) — CI is the source of truth for shipped bundles.

## Self-update

Updates are pulled from our own **validated GitHub releases** (engine bumps are gated by the
golden-test CI), never live upstream — see [server/live/update.py](server/live/update.py).

- A release publishes `update-manifest.json`, `corpus.sqlite`, and `pob-engine.zip`.
- The installed server checks `…/releases/latest/download/update-manifest.json` on startup
  (throttled, best-effort, in a background thread) and installs newer corpus + engine into a
  **writable user-data dir** (`%LOCALAPPDATA%` / `~/Library/Application Support` / `$XDG_DATA_HOME`).
- [server/paths.py](server/paths.py) prefers that user-data copy over the bundled seed, so the
  seed is always a working fallback and updates layer on top.
- Manual control: the `check_for_updates` and `apply_updates` tools; `update_corpus(rebuild_from_source=true)`
  rebuilds the corpus from RePoE locally. Set `POE2_MCP_NO_AUTOUPDATE=1` to disable auto-update,
  or `POE2_MCP_DATA` to relocate the user-data dir.

## Requirements at the host

The `.mcpb` manifest runs `python -m server.main` with `PYTHONPATH=${__dirname}`, so the host
needs a Python 3.11+ runtime. Everything else (deps, engine, corpus, LuaJIT) is inside the bundle.
