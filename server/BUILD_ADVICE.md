# Path of Exile 2 — durable build-optimization principles

Evergreen rules for making a PoE2 build stronger. These are *principles*, not a meta list —
they stay true as skills and items get rebalanced. **The engine computes your build's actual
numbers; this doc is how to reason about them.** Never quote a DPS/EHP/resist figure you didn't
get from a compute tool — use these rules to decide *what* to change, then verify the effect.

## The optimization loop

Always **create → validate → cost → present**. Make one change at a time, recompute on the
engine (`get_build_stats` / `get_defenses`), and keep it only if it improves the goal. Use
`compare_to` for A/B deltas. A build that fails `evaluate_build` is flagged, not recommended.
Optimization is finding the build's *weakest layer* and spending the cheapest points/currency to
raise it — not maximizing the number that's already highest.

**Min/maxing a complete build** is the same loop pointed at marginal gain: once defense is
complete and resists are capped, find where the *next* point/currency pays most rather than
guessing. `rank_levers` measures each candidate stat's real Δ on the current build and ranks
them, so you spend on the lever that actually moves the number (often penetration or attack/cast
speed over raw "increased" damage). Confirm the magnitude with `solve_for`, apply the real gear/
tree change, then re-verify defense — a min/maxed build never trades back below the "done" bar.

## What "done" looks like — targets, not vibes

A build is a **draft** until it clears this bar. Don't present one as finished until it does
(check with `get_defenses` + `evaluate_build`):

- **Resistances capped.** Fire/Cold/Lightning at 75% (over-cap is buffer); chaos positive. Non-negotiable.
- **A full gear set.** Every slot filled — weapon(s), helmet, body, gloves, boots, belt, amulet,
  two rings. A build with 2 of ~10 slots is a *skeleton*, not a build.
- **A real hit pool.** A meaningful Life and/or ES pool — thousands for endgame, not the few
  hundred a fresh character starts with.
- **Enough DPS for the target content.** "Enough" is relative: mapping needs far less than
  pinnacle bosses. The test is *time-to-kill on the content the player wants*, not a fixed number.
  If unsure, ask what content they're aiming at, or compare against a known-good reference build.
- **Sustain.** The build can actually use its skill (mana/spirit covered by pool + regen/leech),
  with recovery beyond flasks.

**Reality check:** a from-scratch build with one weapon, a couple of notables, uncapped resists,
and a few-hundred life pool is a skeleton that validates the *workflow* — it is **not** finished,
and it's typically *orders of magnitude* behind a min-maxed meta build (DPS and EHP). Say so
plainly; never present a skeleton as "done".

---

## Reaching endgame DPS (orders of magnitude, not increments)

Endgame content assumes very high DPS. If a build is far short, the fix is usually a **missing
core multiplier**, not more small increases. Work in this order:

1. **Find the DOMINANT multiplier and verify it with `rank_levers` — don't assume.** Archetypes
   scale on different things; measure, don't guess. For most single-target BOSS builds the dominant
   multiplier is **crit** (crit chance × crit multi can be **3–7×** — a real meta Comet build runs
   ~98% crit / 7× multi). Other big levers: "+levels to skills", "more" supports, ailment magnitude
   (shock far exceeds its 20% base), penetration/exposure. Put the dominant lever in *before*
   fine-tuning gear, and look the skill up if unsure (`explain_mechanic`/`lookup_mechanic`).
2. **Commit to crit unless you have a deliberate non-crit package.** Crit is usually the biggest
   single multiplier, so going non-crit (e.g. Controlled Destruction) *forgoes* it — only do that if
   a "more"-multiplier package makes up for the loss. Crit needs BOTH halves (chance + multi) and a
   *base*-crit source; "increased" crit does nothing from zero, and some supports zero base crit.
3. **Match the skill to the goal — boss vs farm are different skills.** A slow, high-crit nuke (e.g.
   *Comet*), often triggered by **Cast on Critical**, is the single-target BOSS engine; a fast
   multi-projectile (e.g. *Spark*) is the CLEAR/farm engine. Don't optimize the clear skill for boss
   DPS — the meta runs a different skill for each.
4. **Stack the build's defining resource.** For a crit caster that's crit + the hit's base damage +
   cast rate; for a mana-stacker it's ES/mana via **Eldritch Battery + Mind over Matter** (one stat
   becomes both damage *and* EHP). Mana/Archmage is ONE layer, **not automatically the master
   lever** — `rank_levers` tells you which actually moves *this* build.
5. **Don't skip jewels.** Real endgame builds run **8–10 jewels**, including unique/timeless ones
   (Voices, Megalomaniac, From Nothing, Time-Lost) that supply huge passive/notable density — that's
   often why a meta tree reads "over budget". `list_jewel_sockets` / `equip_jewel`.
6. **Re-verify defense after each big swing.** Resists drift and silently break caps when you
   reshuffle gear for damage — re-check `get_defenses` every time.

A useful sanity check: realistic gear should reach high six figures on a strong archetype; if the
engine shows far less, suspect either a missing core multiplier (above) or that a mechanic isn't
being modeled — note the latter rather than trusting the low number.

**Measure the right number, with the fight realistic.** For multi-projectile/overlap skills (e.g.
Spark) read **FullDPS** (PoB's combined figure), not the per-hit `TotalDPS` — and compare builds
like-for-like (FullDPS↔FullDPS, never one's TotalDPS vs another's FullDPS). The engine's enemy
conditions are **off by default**, so a bare stat read understates a real fight: use
`apply_combat_profile` to switch on the shock/curse/charges/boss-tier the build actually maintains
before judging DPS (turn off any it can't sustain — they'd inflate the number). The mana *pool*
isn't automatically the master lever: real meta million-DPS builds (Comet/Cast-on-Critical for
bossing, crit Spark for farm) run only ~6–8k mana and get most of their damage from **crit + the
hit + chase jewels**, not pool size — let `rank_levers` find what actually moves *this* build.
**To chase a specific meta build, import its PoB** (`import_build`) and read its keystones, crit,
skill (incl. trigger like Cast on Critical), and jewels — then build to that archetype and verify
each layer on the engine; `compare_to` shows the per-stat gap. When the build looks done, gate it
with `pinnacle_readiness` (resists + chaos + EHP + DPS) — note real ~1M-DPS builds run only
~17–20k EHP and survive on Mageblood + charms + dodge, so breadth/recovery beats a huge pool.

## Defense: the survival checklist

Survivability is **layered**: avoidance × mitigation × hit-pool × recovery, plus ailment and
stun protection. A weakness in any one layer is what actually kills you, so breadth beats
over-stacking one stat.

1. **Cap elemental resistances at 75% — this is non-negotiable.** Maps are balanced around it.
   Uncapped resist isn't "less reduction," it's *more damage taken*: at 50% fire res you take
   **twice** the fire damage of someone at 75%. The campaign applies a stacking area penalty
   (−10% per act, ending around −60% at endgame), so you must gear ~+125–150% elemental res to
   sit at the cap. **Chaos resistance** has its own 75% cap, no area penalty, and matters more
   in the endgame — get it positive, ideally capped.
2. **Run at least one mitigation/avoidance layer, and know its weakness:**
   - **Armour** reduces hit damage on a curve — roughly `reduction = Armour / (Armour + 12 ×
     hit)`, capping near 90%. It's excellent against many small hits and **weak against single
     big hits** (a hit large enough relative to your armour barely gets reduced). Don't rely on
     armour alone to survive one-shots.
   - **Evasion** gives a chance to avoid **strikes and projectiles** (mostly attacks). It does
     little against spells and AoE. It's entropy-based, so it's consistent against many hits but
     never a guarantee against the one that matters.
   - **Energy Shield** is an extra hit pool that **recharges** after a short delay without
     damage — great when you can avoid sustained damage. Caveats: **chaos damage removes ES at
     2× rate**, **bleed and poison bypass ES entirely**, and **stun ignores ES by default**
     (scale stun threshold if you go heavy ES). Evasion+ES is a strong hybrid: evasion buys the
     downtime ES needs to recharge.
3. **Build a real hit pool (EHP).** Avoidance and mitigation only matter if a pool sits behind
   them. Don't glass-cannon. Life scales with level and Strength (+2 Life per Strength); ES
   layers on top. `Chaos Inoculation` (Life → 1, immune to chaos) only makes sense once ES is
   the overwhelming majority of your effective HP.
4. **Have recovery, not just a pool.** Keep life flasks upgraded, then add a sustained source:
   regen, leech, or recoup (repays a portion of a hit over 8s). ES wants faster recharge *start*
   and recharge *rate* (or convert life regen via Zealot's Oath).
5. **Defend against ailments — they're a top killer.** Capped resistances reduce the chance and
   magnitude; **ailment threshold** (scales with your pool) reduces it further; charms cleanse.
   Watch **shock** (you take ~20% more damage), **freeze** (you can't act), and **bleed**
   (physical DoT, *doubled while moving*).
6. **Use your active defense.** The **dodge roll** is your strongest tool — i-frames against
   strikes and projectiles (but **not** AoE). Good positioning and rolling beats raw stats.
7. **Priority order when you're short:** ① cap resistances → ② ailment defense → ③ life pool +
   recovery → ④ your main mitigation layer (armour/evasion/ES) → ⑤ supplementary (block, damage
   shifting). For *damage-taken reduction*, "reduced" (additive) is stronger than "less"
   (multiplicative).

Use `get_defenses` to read resist over-cap and EHP; the weakest of the layers above is almost
always the right place to spend next.

---

## Offense: the damage checklist

Damage is computed in this order — knowing it tells you what's worth buying:
**base → added flat → increased (additive) → more (multiplicative) → enemy mitigation
(resistance / penetration), applied last.**

1. **"More" beats "increased."** Increased modifiers add together (two +20% = ×1.4); "more"
   modifiers each multiply (two 20% more = ×1.44). Your biggest "more" multipliers come from
   **support gems** — picking the right supports is usually your largest single damage lever
   (`find_supports_for`).
2. **Stack flat added damage early.** It sits at the bottom of the order, so every increased /
   more / crit / speed multiplier on top scales it. Early flat damage compounds as your
   multipliers grow.
3. **Mix your scaling layers.** Added + increased + more + crit + speed + penetration multiply
   together; spreading investment across several layers vastly outperforms over-investing one
   (e.g. dumping everything into "increased" hits hard diminishing returns).
4. **Crit needs both halves.** Base critical damage bonus is +100% (a crit deals ~2×). Crit
   chance and crit damage are useless without each other — balance them, don't stack one.
5. **Match the enemy's resistance and lower it.** Damage is reduced by enemy resistance last, so
   **penetration** and **exposure** (−% enemy resistance) are effectively "more" damage. Pick a
   damage type and commit; don't split across types.
6. **Respect conversion.** When a skill converts damage (e.g. physical → cold), **only modifiers
   for the final type apply.** Scaling the pre-conversion type is wasted.
7. **Hit rate is damage.** Attack/cast speed multiplies DPS directly — just budget the resource
   (mana) cost. It won't show in a single-hit tooltip; check `TotalDPS`.
8. **Read the skill's tags.** Only modifiers matching a skill's tags (Spell/Attack/Projectile/
   element/…) affect it. Off-tag stats do nothing.
9. **Gem level and quality** are cheap, durable damage — spells gain flat damage per level,
   attacks scale better with weapon damage.

---

## Spirit, links, and budget

**Spirit** is a separate resource that pays for *persistent* effects — auras/buffs, minions,
and meta/trigger gems. Treat it like a budget: spend it on the persistent effects with the
highest impact for your build, and scale it with +Spirit gear (sceptres, amulets, body armour)
when you need more reservation. Don't leave a big chunk of spirit unspent.

---

## Design patterns of strong builds

Structural patterns strong builds share — stated as durable design, **not** as any current pick
(no specific skill/item/ascendancy is "the answer"). Use them to shape a build, then verify on
the engine.

- **Defense is *completed*, not partial.** Strong builds reach a full defensive baseline before
  chasing more damage: resistances capped, a real hit pool, every gear slot used. A build with
  uncapped resists or a few-hundred pool is unfinished, however high its tooltip DPS.
- **Commit to one damage type and scale it multiplicatively.** Pick a single damage type (often a
  single ailment too) and stack it rather than splitting across types. Support gems are the
  *backbone* — most of the damage comes from the multiplicative ("more") supports on the main
  skill; gear and tree add flat/increased on top.
- **Crit is all-or-nothing.** If a build goes crit, it commits to *both* crit chance and crit
  damage (plus a crit support) — half-invested crit is wasted. Builds that don't commit scale
  hit/ailment damage instead. Pick one lane.
- **Pick one defensive archetype and let it reshape the build.** Life, energy shield, or a hybrid
  — the choice changes which stats matter. An ES-only identity (e.g. a keystone that sets life to
  1 in exchange for chaos immunity) makes life *and* chaos resistance irrelevant; an evasion/ES
  hybrid wants recharge uptime; an armour/life build wants flat life and big-hit mitigation.
  Choose, then stop paying for stats your archetype doesn't use.
- **Use every slot.** Complete builds fill gear *and* jewels, and cover ailments with charms — not
  just resistances. Empty slots and missing ailment coverage are unfinished work.
- **Solve "tax" stats on suffixes; spend prefixes on the payoff.** Resistances and attributes are
  typically suffixes, so prefixes can carry the build's defining stats (life/ES, added damage —
  the things that scale it).

None of these prescribe *what* to play — they describe what *coherent* looks like. The skill,
items, and ascendancy are the player's call; these are the structural discipline that turns any
of those choices into a working build.

## Common red flags (cheap wins hiding here)

- Uncapped elemental resistance, or negative chaos resistance.
- A single defensive layer and nothing else (e.g. big life pool, zero mitigation/avoidance).
- No recovery beyond flasks.
- No ailment-threshold or charm coverage for shock/freeze/bleed.
- Damage split across two types, or scaling a pre-conversion damage type.
- Over-investing "increased" damage while owning no "more" multipliers (supports).
- A high tooltip hit with low attack/cast speed (low sustained DPS).

When you spot one of these, it's usually the highest-return change available — propose it, then
**verify the delta on the engine** before recommending it.
