# Build Optimizer — design spec (`optimize_build`)

The automated, holistic whole-build optimizer. It does the **synthesis** the greedy per-slot tools
can't: commit an archetype's dominant multiplier as a *structure* across tree + gear + jewels +
supports, search the commitment space on the engine, and return a complete, verified build.

## Why

Greedy per-slot/per-node optimizers are each locally optimal but **myopic** — they won't over-commit
to a multiplier (crit, +levels) before it pays off, because per-slot it looks marginal (a ring can't
roll crit chance; +1 crit on one piece is nothing). So a from-scratch build caps ~100k even though
the same chassis computes **1.48M** the moment the levers are present, and the reference set has a
*verified, real* Lightning Spear at **1.67M**. The gap is synthesis, and it's a **search problem**:
an automated optimizer can run thousands of engine evals/min and over-commit deliberately; an
LLM-in-the-loop can't (it's slow, drifts, and — demonstrated this session — breaks its own build).

## Goal / non-goals

- **Goal:** from a goal (class/ascendancy/skill already set + target metric + EHP floor), assemble a
  complete, **engine-verified** build that pushes to the *gear-quality ceiling* for that archetype.
- **Non-goals:** it does NOT bypass the inherent limits — perfect gear needs the crafting-system
  modeling (essences/runes/corruptions/meta-crafts); the 1M *trigger* meta needs the upstream PoB
  calc. It reaches the gear-quality ceiling, not the world record from rares. It stays **transparent**
  (reports what it committed + a benchmark) — not a black box — and every number comes from PoB.

## Core idea: archetype-seeded **commit-and-max**

1. **Seed** the dominant levers from the reference set (`benchmark_build`): the build's archetype's
   `topLevers` (e.g. Lightning Spear → `+levels`, `more Damage`, `crit damage`, `attack speed`) plus
   the verified DPS/EHP **range** (what "good" looks like). This grounds the search — no blind flailing.
2. For each dominant lever, build the version that **maximally commits** it across *every* source it
   can come from, evaluated as the **whole build**. This over-commits — exactly what greedy won't —
   and the engine says whether it paid off.
3. Keep the best build subject to the defensive constraints; polish; verify.

## The `commit_and_max(lever)` primitive (the crux)

Returns `(build_state, FullDPS, EHP)`. Iterate to convergence (2-3 passes — later passes see the
committed base and commit *more*, breaking the per-slot chicken-egg):

1. **Tree** — `optimize_passives(reset=True, require=[lever's key clusters + jewel sockets], goals
   biased to the lever)`. (Uses the new `reset`/`require` so jewel sockets get planned in cleanly.)
2. **Gear** — `plan_gear(goals weighted to the lever's stats + TotalDPS, auto_base, min_ehp=floor)`.
3. **Jewels** — `optimize_jewel(goals biased to the lever)` → fill **every** allocated socket.
4. **Supports** — `optimize_supports` (engine-measured on the now-committed build).
5. **Profile** — `apply_combat_profile(tier)` so conditional levers (shock/charges/pen) count.

The commitment lives in stacking ONE lever across tree+gear+jewels+supports *together* and judging
the global result — not per slot.

### Lever profiles (the small new config that drives it)

Each dominant lever maps to *how* to commit it. Reference `topLevers` → a profile:

| Lever | Tree (`require` query) | Gear/jewel goal stats | Notes |
|---|---|---|---|
| crit | crit clusters (`search_passives "critical"`) + jewel sockets | `CritChance`, `CritMultiplier` | needs jewels + flat crit, not just "increased" |
| crit damage | crit-damage clusters | `CritMultiplier` | |
| +levels | — (gear/gem side) | gear `+to Level` mods (TotalDPS picks them) | also max gem level/quality; surface +levels uniques |
| more / increased damage | damage clusters | `TotalDPS` | |
| attack/cast speed | speed clusters | `TotalDPS` (speed shows in DPS) | + charges via profile |
| penetration / exposure | pen clusters | `TotalDPS` vs the boss-res profile | pen support already in `optimize_supports` |

## Outer search

1. Identify dominant levers + the verified target range (reference set).
2. Run `commit_and_max` for **each** dominant lever, plus a **balanced/all-damage** pass.
3. *(v2)* **Unique pass:** try the top `relevant_uniques` per slot (equip + measure), keep improvements.
4. Keep the build with the best **objective** (below).
5. **Polish:** `rank_levers` → push the top remaining marginal lever a notch; re-verify defenses.

## Objective + hard constraints

Maximize **FullDPS** (or `TotalDPS` per the skill's overlap reality) **subject to**:
- elemental resists capped (75) + chaos handled — enforced by `plan_gear`;
- `TotalEHP >= min_ehp` (default ~20k pinnacle, or the goal's value) — enforced by `plan_gear(min_ehp)`;
- skill castable (mana/spirit sustain) — a final gate.

A candidate that breaks a constraint is rejected (or repaired by re-running `plan_gear` defensively).

## Reuse vs new

**Reuses (all built + verified this session — low risk):** `optimize_passives` (reset/require/goals),
`plan_gear` (auto_base/min_ehp/goals), `optimize_jewel`, `optimize_supports`, `apply_combat_profile`,
`relevant_uniques`, `benchmark_build`/`refbuilds`, `rank_levers`, the engine.
**New:** the orchestration only — `commit_and_max`, the lever profiles, the outer search, the
objective/constraint enforcement, and the transparent output. **Most of the work is composing tested
primitives.**

## Where it plugs in

- New module: `server/compute/buildopt.py`.
- New MCP tool: `optimize_build(metric="FullDPS", min_ehp=20000, levers=None, tier="Pinnacle",
  try_uniques=False, passes=3)` — registered in `main.py`. `levers=None` auto-seeds from the reference
  set; pass explicit levers to force an archetype.
- **Returns (transparent):** the assembled build (export code) + the levers it committed and each
  one's DPS contribution + the `benchmark_build` placement vs the reference range + the defensive
  summary + a note: *"best found (engine-verified), not a global optimum; reaches the gear-quality
  ceiling — perfect gear needs crafting-system modeling, the 1M trigger meta needs upstream PoB."*

## Cost / performance

~1–3k engine evals (`commit_and_max` ≈ 50–200 evals × ~5 levers × 2–3 passes) ≈ **1–3 min** — a heavy,
explicit call. The engine (single LuaJIT subprocess) is the bottleneck; a later optimization is
parallel engine instances. MVP is sequential.

## Risks + honesty

- **Heuristic / local optima** — report "best found, not global."
- **Inherent ceilings** — reaches gear-quality, not 1M-from-rares (crafting system) or the trigger
  meta (upstream). State it in the output.
- **Transparency** — full build + lever breakdown + benchmark, so the LLM/user can verify and tweak.
- **Engine truth preserved** — every number from PoB; the optimizer never invents one (invariant #1).

## Phasing

- **MVP:** `commit_and_max` over the reference-seeded dominant levers + defensive constraints +
  transparent output. (Pure orchestration of tested primitives.)
- **v2:** unique pass (build-defining uniques) + jewel-socket valuation (socket-vs-node) + lever pairs.
- **v3:** multi-archetype search for an open-ended goal + parallel engine instances for speed.
