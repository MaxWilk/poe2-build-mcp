# poe2-build-mcp

An MCP server for **Path of Exile 2**: a queryable game corpus plus **Path-of-Building-faithful
calculations**, so an LLM can import your build, answer questions, and theorycraft against real
numbers (not invented ones).

See [PLAN.md](PLAN.md) for the full design and [CLAUDE.md](CLAUDE.md) for engineering conventions.

## Status

v1 is complete: **M0–M5** (headless engine, compute, corpus, build mutation, passives, live ops,
optimize) plus **self-update** and a **self-contained bundle** pipeline. **29 MCP tools**, a
golden-build pytest suite, and per-OS `.mcpb` builds via CI. The server auto-updates its engine
(from validated releases) and corpus into a writable user-data folder, preferring it over the
bundled seed — see [PACKAGING.md](PACKAGING.md).

**Working MCP tools today:**

*Build / compute (real Path of Building numbers):*
- `import_build(source)` — import a PoB **share code**, a **pobb.in/pastebin link**, or raw PoB XML
- `get_build_stats(keys?)` — computed stats (DPS, EHP, resistances, life/ES/mana, …)
- `set_skill(skill)` — set the main skill, e.g. `"Fireball 20/0  1"`
- `set_class(class_name, ascendancy?)` — set class + ascendancy from scratch (e.g. Mercenary/Witchhunter)
- `set_level(level)` — set character level (1–100)
- `set_config(options?, custom_mods?)` — combat config and/or extra modifiers
- `equip_item(raw)` — equip an item from raw PoB item text
- `evaluate_build(goals)` — pass/fail the build against numeric goals
- `compare_to(source)` — A/B the active build vs another, with deltas
- `search_passives(query?, node_type?)` / `get_passive(node)`
- `alloc_passive(node)` / `dealloc_passive(node)` — allocate/route by id or name, with deltas
- `optimize_passives(metric, points)` — greedy point allocation to maximize a stat
- `engine_health()` — headless engine status

*Corpus / knowledge (bundled SQLite + FTS; no engine needed):*
- `search_items(query, item_class?)` / `get_item(name_or_id)`
- `find_skills(query?, gem_type?, tag?, color?)` / `get_gem(name_or_id)`
- `search_mods(query, item_tag?, mod_type?)` / `reverse_lookup(stat)`
- `search_uniques(query, item_type?)` / `get_unique(name)`
- `list_ascendancies(character?)` / `corpus_info()`

*Live ops & self-update (network):*
- `get_prices(query, kind, league?)` — poe2scout currency/unique prices · `list_price_leagues()`
- `check_for_updates()` / `apply_updates()` — pull validated engine + corpus releases
- `check_data_version()` / `update_corpus(rebuild_from_source?)`

Next: an `optimize` helper (bounded search over the engine) and packaging into a one-click
`.mcpb`. See the roadmap in PLAN.md.

## How it works

Two layers behind one server (Python):
- **Compute** — a vendored [PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2)
  fork run headless under LuaJIT as a persistent JSON-RPC subprocess (loads game data once, answers many calls).
- **Knowledge** *(in progress)* — a bundled SQLite/FTS corpus built offline from RePoE/poe2db.

## Prerequisites (Windows)

- **Python 3.11+**
- **LuaJIT 2.1** — via MSYS2: `pacman -S mingw-w64-ucrt-x86_64-luajit`
  (auto-detected at `C:\msys64\ucrt64\bin\luajit.exe`; override with the `POB_LUAJIT` env var)
- **uv** — `python -m pip install uv`
- The **PoB-PoE2 working copy** (git-ignored; pinned in [pob/PINNED.md](pob/PINNED.md)):
  ```sh
  git clone --depth 1 --branch dev \
    https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git \
    pob/PathOfBuilding-PoE2
  ```

## Setup & verify

```sh
uv sync                                    # create venv, install deps
uv run python -m pipeline.build_corpus     # build data/corpus.sqlite from RePoE (network)
uv run python scripts/smoke_compute.py     # engine round-trip (ping/new_build/skill)
uv run python scripts/smoke_import.py      # PoB import-code round-trip
uv run pytest                              # golden-build suite (engine + corpus)
uv run python scripts/smoke_optimize.py    # greedy passive optimizer
uv run python scripts/smoke_live.py        # live prices + data-version check (network)
uv run python scripts/smoke_mcp_client.py  # full MCP protocol over stdio (all tool groups)
```

The `scripts/smoke_*.py` files cover each tool group individually; `pytest` is the pinned
golden-value regression suite (see `tests/`).

> Smoke scripts print to the console; on Windows run them with `PYTHONUTF8=1` to avoid
> code-page issues with some item/skill names. The MCP server itself is unaffected.

## Connect to Claude Desktop

Add to `claude_desktop_config.json` (adjust the `uv.exe` path and project dir):

```json
{
  "mcpServers": {
    "poe2-build": {
      "command": "C:\\Users\\<you>\\AppData\\Roaming\\Python\\Python312\\Scripts\\uv.exe",
      "args": ["run", "--directory", "W:\\GitHub\\poe2-build-mcp", "python", "-m", "server.main"]
    }
  }
}
```

The first tool call boots the engine (a few seconds to load game data); subsequent calls are fast.
Then ask, e.g.: *"Import this build code … what's my Fireball DPS and where can I push it?"*
