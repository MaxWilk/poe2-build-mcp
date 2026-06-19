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
