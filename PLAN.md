# poe2-build-mcp — v1 Plan

> A single, `.mcpb`-installable MCP server that gives an LLM (Claude) a comprehensive,
> queryable Path of Exile 2 game corpus **and** a Path-of-Building–faithful calculation
> engine, so it can answer build questions, import a user's PoB build, and create/tweak
> builds against natural-language descriptions and goals — with every number it states
> actually *computed*, not invented.

---

## Status — v1 functionally complete (2026-06)

M0–M5 are implemented and verified: 27 MCP tools (compute, passives, corpus, live ops,
optimize) with a golden-build pytest suite. `explain_mechanic` is intentionally deferred.
Remaining work is release packaging — a self-contained, multi-OS `.mcpb`; see
[PACKAGING.md](PACKAGING.md). Current usage and the full tool list are in [README.md](README.md).

---

## 1. Goal & "done" criteria

**Goal:** Make Claude a competent, *verifiable* PoE2 build-crafter.

The server is the **substrate** (queryable knowledge + a mutable, computable build sandbox +
validation + pricing). Claude is the **synthesis** (reading intent, assembling and judging
builds). We do not bake a "build-generator AI" into the server; we make Claude's reasoning
grounded and falsifiable.

**v1 is done when:**

- A user pastes a PoB code/link → Claude reports accurate stats and iterates on the build
  (passives / items / gems / config) with real deltas.
- Claude can **create a build from a description + goals**, then validate and cost it before
  presenting it.
- The corpus answers "what is / find me / why" queries offline and instantly.
- `get_prices`, `check_data_version`, and `update_corpus` work against live sources.
- Optional meta-awareness (`get_meta_builds`) answers "what's popular/strong" questions.
- It installs from one `.mcpb` on Windows / macOS / Linux.
- Compute numbers match the PoB-PoE2 GUI within rounding on a golden set of reference builds.

---

## 2. Architecture

Two engines behind one MCP server, fed by an offline pipeline.

```
                    ┌─────────────────────────────────────────────┐
   Claude  ◄─────►  │             MCP server (Python)              │
   (NL, tools)      │   tools + resources, one process            │
                    └───────────┬─────────────────┬───────────────┘
                                │                 │
              ┌─────────────────▼───┐       ┌─────▼─────────────────────┐
              │  KNOWLEDGE LAYER     │       │  COMPUTE LAYER            │
              │  bundled SQLite+FTS  │       │  headless PoB-PoE2         │
              │  (RePoE + poe2db)    │       │  LuaJIT, persistent stdio  │
              │  read-only, instant  │       │  JSON-RPC subprocess       │
              └──────────┬───────────┘       └─────────────┬─────────────┘
                         │                                 │ build XML in,
        ┌────────────────▼───────────────┐                │ output tables out
        │  OFFLINE refresh pipeline (CI)  │      loads game data ONCE,
        │  fetch RePoE + scrape poe2db    │      answers many calc calls
        │  → normalize → build DB         │
        │  → publish versioned artifact   │
        └─────────────────────────────────┘

  OPTIONAL live edges: poe.ninja prices · poe.ninja builds (meta) · corpus update
```

**Why the split:** the knowledge layer answers "what is / find me" instantly and offline;
the compute layer answers "for *this* build, what's the number" by driving the real PoB
engine. Heavy/fragile scraping lives in CI, never in the user's process.

### Design principles

1. **The engine is the source of truth for numbers.** Server code and answers never
   hand-compute or guess game math; if PoB can't model it, we say so.
2. **Substrate, not a baked-in build AI.** The server exposes composable primitives;
   creative synthesis is Claude's job.
3. **Offline-first knowledge.** The corpus is bundled and deterministic; live calls are
   reserved for genuinely volatile data (prices, meta, version checks).
4. **Generated builds are always verified.** Workflow norm:
   `create → validate → cost → present`. Nothing is recommended unvalidated.

---

## 3. Tech choices

| Concern          | Choice                                                                 | Why |
|------------------|------------------------------------------------------------------------|-----|
| Server language  | **Python 3.11+**, official `mcp` SDK (FastMCP style)                    | Mature MCP SDK; best fit for the data pipeline; matches prior art |
| Dep management   | **uv**                                                                  | Fast, reproducible, lockfile-based |
| Knowledge store  | **SQLite + FTS5**, bundled read-only file                              | Fast, offline, zero-setup, great full-text search |
| Compute engine   | **Vendored PoB-PoE2 (pinned tag) driven headless via LuaJIT**, run as a persistent stdio JSON-RPC subprocess | Faithful numbers; load game data once, answer many calls |
| Build import     | Decode PoB code in **Python** (base64url → zlib inflate → XML); also accept `pobb.in` / paste links | No Lua zlib dependency needed |
| Prices & meta    | **poe.ninja** PoE2 economy + builds endpoints (league-scoped)           | Stable, no auth, good coverage; trade API deferred |
| Corpus refresh   | **Offline CI pipeline** publishes a versioned DB artifact; runtime *downloads* it | Keeps fragile scraping out of the user's process |
| Packaging        | `.mcpb` with per-OS LuaJIT binaries bundled                            | One-click install |

---

## 4. Repository layout

```
poe2-build-mcp/
  manifest.json              # .mcpb manifest (entrypoint, perms, metadata)
  server/
    main.py                  # MCP entrypoint; registers tools + resources
    knowledge/               # SQLite access + search/lookup tools
    compute/                 # PoB RPC client, build-session manager
    live/                    # prices, meta builds, version check, corpus updater
    models.py                # shared typed models
  pob/
    PathOfBuilding-PoE2/     # git submodule, pinned @ release tag
    pob_headless.lua         # our headless shim + JSON-RPC loop
  runtime/luajit/            # luajit binaries: win-x64, mac-arm64, linux-x64
  data/
    corpus.sqlite            # bundled prebuilt artifact (built by pipeline)
    schema.sql
  pipeline/                  # OFFLINE (CI) — not on the runtime path
    fetch_repoe.py  scrape_poe2db.py  normalize.py  build_db.py  publish.py
  tests/
    golden_builds/           # reference XML + expected output snapshots
    ...
  docs/
  CLAUDE.md
  PLAN.md
```

---

## 5. Knowledge corpus

**Sources:** RePoE-fork PoE2 JSON as the backbone (schema-validated), poe2db.tw scraped
*only at build time* to fill gaps / freshen. Internal stat IDs are resolved to
human-readable text via RePoE `stat_translations` during the build, so query results are
readable, never raw codes.

**Tables:** `items` (bases + uniques), `mods` (affix / tier / domain / tags), `gems` +
`gem_levels`, `passives` (nodes / notables / keystones / ascendancy), `ascendancies`,
`stats`, `stat_translations`, `mechanics_docs`, plus FTS5 virtual tables. A `meta` table
stamps **game version + corpus build date + schema version**.

---

## 6. Refresh & update mechanism

Two stages, deliberately splitting heavy work from the runtime.

**Stage A — CI pipeline (offline):** fetch RePoE → scrape poe2db for gaps → normalize →
build `corpus.sqlite` → compress → publish as a **GitHub release asset** with a
`manifest.json` (latest version, download URL, SHA-256, target game patch, min-server-version).

**Stage B — runtime tools:**

- `check_data_version` → local corpus version + the game patch it targets, the latest
  published corpus version (from the release manifest), the **current live game patch**
  (best-effort, detected from poe2db / patch notes), and a recommendation
  (`up_to_date` / `update_available` / `behind_live_patch`).
- `update_corpus` → downloads the latest published DB, **verifies checksum**, atomic-swaps
  the SQLite file, hot-reloads. Advanced opt-in `rebuild_from_source=true` runs the scraper
  locally for power users when no release exists yet (heavier, clearly labeled).

Normal users only ever pull a vetted artifact; nobody scrapes in-process.

---

## 7. Compute layer

Persistent subprocess: `luajit pob_headless.lua --stdio`, newline-delimited JSON-RPC. Python
holds a **build session** (current XML state) and mutates it via RPC.

**RPC methods:** `new_build(class, ascendancy)`, `load_build(xml)`, `get_stats(filter?)`,
`alloc/dealloc(nodes)`, `pathfind(target)`, `set_item(slot, item)`, `set_gem(group, gem)`,
`set_skill(skill)`, `set_config(table)`, `validate()`, `snapshot()/restore()` (for A/B).
`optimize` is orchestrated server-side in Python by repeatedly calling these.

**Import flow:** PoB code → Python decodes to XML → `load_build` → summary stats. Links
(`pobb.in`, pastebin) are fetched to raw XML first.

**Build-from-scratch flow:** `new_build` → incremental `set_skill` / `edit_passives` /
`set_item` → `validate` → `get_stats` → `get_prices`.

---

## 8. Tool & resource catalog (v1)

**Knowledge / discovery**
- `search_items`, `get_item` — bases & uniques by name, slot, class, or "has mod X"
- `search_mods` — modifiers by stat / affix / tier / domain
- `get_gem`, `find_supports_for` — gem stats per level, tags, legal support attachment
- `find_skills` — skills by damage type / tag / archetype
- `find_scaling` — given a stat or tag, the passives / uniques / gems that scale it
- `search_passives`, `get_passive`, `list_ascendancies`, `get_ascendancy`
- `reverse_lookup` — stat → sources
- `explain_mechanic` — curated, sourced mechanics docs

**Build / compute**
- `import_build` — PoB code / link / raw XML → build handle + summary
- `new_build` — create an empty build skeleton (class / ascendancy)
- `get_build_stats` — DPS variants, EHP, resistances, life / ES / mana, crit, mitigation
- `edit_passives` — alloc / dealloc / pathfind, returns stat delta
- `set_item`, `swap_gem` / `set_skill`, `set_config`
- `compare_builds` — A/B two states
- `validate_build` — surface unsupported mods, failed attribute reqs, missing links
- `evaluate_build(goals)` — pass/fail vs named targets (e.g. `boss_dps >= 500k`,
  `life >= 5000`, `all_res capped`, `budget <= 10div`); composes stats + prices + validation
- `optimize` — bounded greedy/beam search over the engine (best-effort)

**Live ops**
- `get_prices` — poe.ninja economy, league-scoped
- `get_meta_builds` — poe.ninja builds: popular skills / ascendancies / gearing per league
  (community data, freshness-dependent)
- `check_data_version`, `update_corpus`

**Resources**
- `mechanics/*` explainer docs
- `corpus://meta` — current data version

---

## 9. Capabilities & honest limits

**Does well**
- Faithful, computed numbers (DPS / EHP / defenses) via the real PoB engine.
- Deeply queryable corpus for "what is / find me / why".
- Conversational build iteration with real deltas.
- Build creation from a description, made *verifiable* (create → validate → cost → present).
- Evaluative questions answered by *computing* alternatives, not guessing.
- Meta-aware build questions via poe.ninja builds.

**Won't do (by design or constraint)**
- **No in-game overlay / automation / live screen reading** — out of scope and against GGG ToS.
- **Data lag is structural** — corpus is as current as its last refresh; unsupported content
  is flagged, never faked.
- **`optimize` is heuristic**, not a proven global optimum.
- **Inherits PoB's blind spots** — `validate_build` flags what the engine can't model.
- **Prices & meta are best-effort**, volatile, league-scoped.
- Produces *sound, goal-satisfying* builds; "feel" / guaranteed meta-viability remain human calls.

---

## 10. Milestones

| #  | Milestone                       | Deliverable / gate |
|----|---------------------------------|--------------------|
| **M0** | **Headless PoB-PoE2 spike**  | Script loads 4 archetype reference builds (spell / attack / DoT / minion); outputs match GUI. **Go/no-go gate.** |
| M1 | Compute service                 | Headless PoB wrapped as JSON-RPC subprocess + Python client; `new_build`, `import_build`, `get_build_stats` end-to-end |
| M2 | Corpus pipeline + knowledge     | CI builds `corpus.sqlite`; search / discovery / explain tools live *(parallel with M1 — independent)* |
| M3 | Build mutation & creation       | `edit_passives`, `set_item`, `swap_gem`, `set_config`, `compare_builds`, `validate_build`, `evaluate_build` |
| M4 | Live ops                        | `get_prices`, `get_meta_builds`, `check_data_version`, `update_corpus` |
| M5 | `optimize`                      | Bounded greedy/beam search over the engine |
| M6 | Package & ship                  | `.mcpb` manifest, per-OS binaries, docs, CI test matrix → **v1** |

M0 gates M1 / M3 / M5. M2 and M4 are independent of the spike and ship value regardless.

---

## 11. Risks & mitigations

- **Headless spike fails (🔴)** → fall back to bridging a running PoB; M2 / M4 still ship.
  *This is why M0 is first.*
- **PoB fork churn** → pin to a release tag; engine bumps are deliberate, gated by golden tests.
- **Cross-platform LuaJIT packaging** → bundle prebuilt binaries for 3 targets; CI verifies
  each boots headless.
- **Scraping fragility** → build-time only, schema-validated, parser tests; failures break CI,
  never the user.
- **poe.ninja coverage / league param** → league configurable; degrade gracefully.
- **Data licensing gray area** → operate within established community-tool norms; credit
  sources; no redistribution claims beyond derived data.
- **EA patch cadence** → the M4 update path is the answer; `check_data_version` makes
  staleness visible.

---

## 12. Testing

- **Golden builds** — reference XML + expected `output` snapshots; CI fails on drift (catches
  our bugs *and* engine bumps).
- **Corpus** — JSON-schema validation on ingest; FTS query tests.
- **Tools** — per-tool smoke tests; import round-trip tests.
- **CI matrix** — boot the headless engine on each OS target.

---

## 13. Decisions locked for v1

- **OS targets:** win-x64, mac-arm64, linux-x64. (mac-x64 optional, added if demand.)
- **Pricing/meta source:** poe.ninja; default league = current challenge league, configurable.
- **PoB vendoring:** git submodule pinned to a release tag.
- **`optimize`:** ship a simple greedy version in v1.
- **Meta-awareness (`get_meta_builds`):** included in v1.
- **Language / tooling:** Python 3.11+, `uv`, `mcp` SDK; Lua via bundled LuaJIT.

**Still flexible:** trade-API pricing (deferred), mac-x64 target, refresh cadence.

---

## 14. Out of scope for v1

GGG OAuth / character import, in-game overlay or automation, a global optimizer, PoE1,
party / aura-from-allies modeling beyond PoB defaults, trade-API live pricing.

---

## 15. Immediate next steps

1. Scaffold the repo (server skeleton, submodule, uv project, CI stub).
2. **Execute M0** — the headless PoB-PoE2 spike. Everything in the compute layer rides on it.
3. In parallel, start M2 (corpus pipeline) since it's independent of the spike.
