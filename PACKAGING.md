# Packaging poe2-build-mcp as an `.mcpb`

[manifest.json](manifest.json) declares the MCP server for the MCP Bundle (`.mcpb`, formerly
DXT) format so it can be installed into Claude Desktop. There are two distribution tiers; the
difference is entirely about how much of the runtime you bundle vs. require on the user's machine.

## Tier 1 — lean bundle (assumes local prerequisites)

Ships the Python server + corpus, but relies on the user already having Python 3.11+, the PoB
checkout, and LuaJIT. This is what `manifest.json` targets today.

Build:

```sh
# from the repo root, with the corpus built and the PoB checkout present (see README)
npx @anthropic-ai/mcpb pack        # validates manifest.json and produces poe2-build-mcp.mcpb
```

Prerequisites the user must have (the manifest's `user_config.luajit_path` covers the last one):
- Python 3.11+ with this project's dependencies (`uv sync`)
- `pob/PathOfBuilding-PoE2/` checked out at the commit in [pob/PINNED.md](pob/PINNED.md)
- LuaJIT 2.1 on PATH (or set via the install dialog)

## Tier 2 — self-contained bundle (release engineering)

A one-click bundle that needs nothing pre-installed. This is a per-OS release task, not
something buildable from a single dev machine, because it must vendor native binaries:

- **LuaJIT** binaries for each target (`runtime/luajit/{win-x64,mac-arm64,linux-x64}/`), built
  on/for each OS. Replace the pure-Lua `lua-utf8` shim in `pob/pob_headless.lua` with a real
  `luautf8` built against LuaJIT for correct non-ASCII handling.
- The **PoB checkout** (`pob/PathOfBuilding-PoE2/src` + `runtime/lua`) and the prebuilt
  **`data/corpus.sqlite`**, included in the bundle (they're git-ignored in source).
- A **Python runtime + deps** (e.g. a relocatable venv or the mcpb Python packing flow).
- `engine.py` already resolves LuaJIT via `POB_LUAJIT` → PATH → MSYS2 fallback; point
  `POB_LUAJIT` at the bundled binary in the manifest env for each platform.

Recommended: a CI matrix (win/mac/linux) that assembles each platform bundle, runs the golden
tests (`pytest`) against it, and attaches the `.mcpb` artifacts to a GitHub release. The same
release should publish `corpus.sqlite` + a manifest JSON so `update_corpus` can fetch updates
(see `server/live/version.py`).

## Corpus updates

`data/corpus.sqlite` is a build artifact, not source. It's produced by
`uv run python -m pipeline.build_corpus` and refreshed via the `update_corpus` tool
(`rebuild_from_source=true` today; release-download once Tier 2 publishing is set up).
