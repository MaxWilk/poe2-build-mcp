-- pob_headless.lua — stdio JSON-RPC bridge to the PoB-PoE2 calculation engine.
--
-- Run with the working directory set to <repo>/pob/PathOfBuilding-PoE2/src
-- (mirrors the fork's .busted: directory=src, lpath=../runtime/lua, helper=HeadlessWrapper).
--
-- Protocol: one JSON object per line on stdin, one JSON object per line on stdout.
--   request : {"id": <n>, "method": "<name>", "params": {...}}
--   response: {"id": <n>, "ok": true,  "result": {...}}
--          or {"id": <n>, "ok": false, "error": "<message>"}
-- A startup frame {"ready": true, ...} is emitted once the engine has initialised.
-- All engine chatter is routed to stderr so stdout carries only JSON-RPC frames.

package.path = "./?.lua;./?/init.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;" .. package.path

-- Pure-Lua stand-in for the lua-utf8 C module (ASCII-correct; see pob/PINNED.md).
package.preload["lua-utf8"] = function()
	local u = {}
	for _, k in ipairs({ "find", "gmatch", "gsub", "match", "sub", "reverse",
		"len", "char", "byte", "upper", "lower", "rep", "format" }) do
		u[k] = string[k]
	end
	u.offset = function(s, n, i) return (i or 1) + (n or 0) end
	u.next = function(s, i)
		i = (i or 0) + 1; if i > #s then return nil end; return i, s:byte(i)
	end
	u.charpos = function(s, i) return i or 1 end
	u.width = function() return 1 end
	return u
end

-- Clean RPC frames go to the real stdout; everything else is pushed to stderr.
local _stdout = io.stdout
local function emit(line)
	_stdout:write(line); _stdout:write("\n"); _stdout:flush()
end
_G.print = function(...)
	local n = select("#", ...)
	local parts = {}
	for i = 1, n do parts[i] = tostring((select(i, ...))) end
	io.stderr:write(table.concat(parts, "\t")); io.stderr:write("\n")
end
io.write = function(...) io.stderr:write(...); return io.stderr end

local json = require("dkjson")

-- Boot the engine (its prints now land on stderr).
local booted, bootErr = pcall(dofile, "HeadlessWrapper.lua")
if not booted or not build then
	emit(json.encode({ ready = false, error = "engine init failed: " .. tostring(bootErr) }))
	os.exit(1)
end

-- ---------------------------------------------------------------------------
-- helpers
-- ---------------------------------------------------------------------------
local DEFAULT_STATS = {
	"TotalDPS", "FullDPS", "CombinedDPS", "AverageDamage", "Speed", "HitChance",
	"CritChance", "CritMultiplier", "ManaCost", "Life", "Mana", "EnergyShield",
	"TotalEHP", "Ward", "Armour", "Evasion", "Str", "Dex", "Int", "ProjectileCount",
}

local function collectStats(keys)
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local res = {}
	local list = (type(keys) == "table") and keys or DEFAULT_STATS
	for _, k in ipairs(list) do
		local v = out[k]
		local t = type(v)
		if t == "number" or t == "string" or t == "boolean" then
			res[k] = v
		end
	end
	return res
end

-- Normal passive points available at the current level: 1 per level past 1, plus the
-- cumulative quest points unlocked by that level (mirrors PoB's EstimatePlayerProgress).
local function availablePoints()
	local level = build.characterLevel or 1
	local qp = 0
	for _, act in ipairs(build.acts or {}) do
		if level >= (act.level or 1) then
			qp = act.questPoints or qp
		end
	end
	return math.max(0, level - 1 + qp)
end

local function mainSkillName()
	local sg = build.skillsTab.socketGroupList[build.mainSocketGroup or 1]
	if sg and sg.displaySkillList and sg.mainActiveSkill then
		local s = sg.displaySkillList[sg.mainActiveSkill]
		if s and s.activeEffect and s.activeEffect.grantedEffect then
			return s.activeEffect.grantedEffect.name
		end
	end
	return nil
end

-- An Attack skill computes ~no damage without a weapon; flag it so a 0-DPS result from a fresh
-- attack build isn't mistaken for a bug (a common confusion when building from scratch).
local function attackWeaponWarning()
	local sg = build.skillsTab.socketGroupList[build.mainSocketGroup or 1]
	if not (sg and sg.displaySkillList and sg.mainActiveSkill) then
		return nil
	end
	local s = sg.displaySkillList[sg.mainActiveSkill]
	local ge = s and s.activeEffect and s.activeEffect.grantedEffect
	local attackType = (SkillType and SkillType.Attack) or 1
	if not (ge and ge.skillTypes and ge.skillTypes[attackType]) then
		return nil
	end
	local slot = build.itemsTab.slots["Weapon 1"]
	if slot and slot.selItemId and slot.selItemId ~= 0 then
		return nil
	end
	return "Main skill is an Attack but no weapon is equipped (Weapon 1) — its DPS is ~0 until "
		.. "you equip a weapon (equip_item)."
end

local function mainActiveSkill()
	local sg = build.skillsTab.socketGroupList[build.mainSocketGroup or 1]
	if sg and sg.displaySkillList and sg.mainActiveSkill then
		return sg.displaySkillList[sg.mainActiveSkill]
	end
	return nil
end

-- True if the active skill's grantedEffect carries a given SkillType (by name, resilient to enum
-- number changes; degrades to false if the enum/type is absent so we never false-positive).
local function hasType(ge, name)
	if not (ge and ge.skillTypes and type(SkillType) == "table" and SkillType[name]) then
		return false
	end
	return ge.skillTypes[SkillType[name]] and true or false
end

-- Diagnose a ~0-DPS result so an uncomputable pattern isn't mistaken for a bug (or a real build).
-- Returns the most specific applicable note, or nil. Drives off the skill's SkillTypes + the
-- actual output, not a hardcoded skill list, so it stays correct as PoB changes. Fires only when
-- DPS is ~0 (a weak-but-computable build still returns its real number).
local function damageDiagnostic()
	local w = attackWeaponWarning() -- most specific: attack with no weapon
	if w then
		return w
	end
	local act = mainActiveSkill()
	local ge = act and act.activeEffect and act.activeEffect.grantedEffect
	if not ge then
		return nil
	end
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local dps = tonumber(out.TotalDPS) or tonumber(out.CombinedDPS) or 0
	if dps > 0 then
		return nil
	end
	local isDamage = hasType(ge, "Damage") or hasType(ge, "DamageOverTime")
	-- explicitly undamageable minions (e.g. the ravens) — engine can't credit player-facing DPS
	if hasType(ge, "MinionsAreUndamagable") then
		return "Main skill summons undamageable minions — the engine can't compute their "
			.. "player-facing DPS. Validate kill speed in-game."
	end
	-- buff/reservation/aura/herald that isn't itself a damage skill: ~0 DPS by design
	if
		not isDamage
		and (
			hasType(ge, "Buff")
			or hasType(ge, "HasReservation")
			or hasType(ge, "Aura")
			or hasType(ge, "Herald")
		)
	then
		return "Main skill is a buff/reservation effect, not a direct hit — the engine reports "
			.. "~0 DPS by design. Its impact comes from what it empowers; validate in-game."
	end
	-- minion skill with no computed DPS
	if hasType(ge, "Minion") then
		return "Main skill is a minion skill but the engine computes ~0 player-facing DPS "
			.. "(common for undamageable/utility minions). Validate kill speed in-game."
	end
	-- generic: a damaging skill that still computes ~0 is usually an uncomputable pattern
	if isDamage or hasType(ge, "Attack") or hasType(ge, "Spell") then
		return "Main skill computes ~0 DPS. If it's a reservation buff, an undamageable minion, "
			.. "or %-of-life / corpse detonation, that layer isn't engine-modelled — validate "
			.. "in-game rather than trusting the 0."
	end
	return nil
end

-- Skills whose effect PoB-PoE2 does not model, so their contribution is missing from the computed
-- DPS (the real in-game number is higher). Surfaced so the figure isn't read as the whole story.
local UNMODELED_SKILLS = {
	["Mana Tempest"] = "Mana Tempest is in this build but the engine does NOT model its empower "
		.. "(more damage to mana-spending spells), so the real in-game DPS is higher than shown. "
		.. "Approximate it with a custom 'more spell damage' mod if you need an estimate.",
}

local function engineLimitationNote()
	for _, sg in ipairs(build.skillsTab.socketGroupList or {}) do
		for _, g in ipairs(sg.gemList or {}) do
			local nm = g.nameSpec
			if (not nm or nm == "") and g.gemData and g.gemData.grantedEffect then
				nm = g.gemData.grantedEffect.name
			end
			if nm and UNMODELED_SKILLS[nm] then
				return UNMODELED_SKILLS[nm]
			end
		end
	end
	return nil
end

-- Standard {mainSkill, stats} response, with a warning attached when one applies.
local function statResult(keys)
	local r = { mainSkill = mainSkillName(), stats = collectStats(keys) }
	local w = damageDiagnostic()
	if w then
		r.warning = w
	end
	local el = engineLimitationNote()
	if el then
		r.engineNote = el
	end
	-- Clarify multi-projectile DPS WITHOUT implying shotgunning: PoE2 generally does NOT let
	-- multiple projectiles from one use stack on a single target, so projectile count is clear/
	-- coverage (and ailment/secondary feed), not a single-target multiplier.
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local proj = tonumber(out.ProjectileCount) or 0
	if proj > 1 and (tonumber(out.TotalDPS) or 0) > 0 then
		r.dpsNote = "This skill fires "
			.. proj
			.. " projectiles. TotalDPS is the single-target figure — PoE2 generally does NOT allow "
			.. "shotgunning, so do NOT multiply it by projectile count for boss DPS. Extra "
			.. "projectiles add clear/coverage (and can feed ailments/secondary effects). A few "
			.. "skills do let projectiles overlap on one target — confirm in-game before assuming."
	end
	return r
end

-- PoB's paste parser REQUIRES a trailing instance count on every gem line ("Name L/Q  count"),
-- so a support written "Controlled Destruction 20/20" is silently dropped. Tolerate that by
-- appending "  1" to any gem line that has level/quality but no count.
local function normalizeSkillText(text)
	local lines = {}
	for line in tostring(text or ""):gmatch("([^\r\n]+)") do
		if line:match("^%s*[%a':][%a':' ]* %d+/%d+%s*%u*%s*$") then
			line = line:gsub("%s*$", "") .. "  1"
		end
		lines[#lines + 1] = line
	end
	return table.concat(lines, "\n")
end

local function selectMainSocketGroup(index)
	index = index or 1
	build.mainSocketGroup = index
	local sg = build.skillsTab.socketGroupList[index]
	if sg then
		sg.mainActiveSkill = 1
		sg.mainActiveSkillCalcs = 1
	end
	if build.calcsTab and build.calcsTab.input then
		build.calcsTab.input.skill_number = index
	end
	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
end

-- ---------------------------------------------------------------------------
-- methods
-- ---------------------------------------------------------------------------
local methods = {}

function methods.ping()
	return { pong = true, jit = jit and jit.version }
end

function methods.new_build()
	newBuild(); runCallback("OnFrame")
	return { stats = collectStats() }
end

-- Set the character class and (optionally) ascendancy, re-rooting the passive tree at that
-- class's start so search/alloc/optimize work for the right class.
function methods.set_class(p)
	assert(p and p.class, "set_class requires params.class")
	local spec = build.spec
	local tree = spec.tree

	local classId = tree.classNameMap[p.class]
	if not classId then
		local want = tostring(p.class):lower()
		for name, id in pairs(tree.classNameMap) do
			if name:lower() == want then
				classId = id
				break
			end
		end
	end
	if not classId then
		local valid = {}
		for name in pairs(tree.classNameMap) do
			valid[#valid + 1] = name
		end
		table.sort(valid)
		return {
			ok = false,
			error = "unknown class '" .. tostring(p.class) .. "'. Valid classes: "
				.. table.concat(valid, ", "),
		}
	end
	spec:SelectClass(classId)

	if p.ascendancy and p.ascendancy ~= "" then
		local want = tostring(p.ascendancy):lower()
		local found
		for aid, asc in pairs(tree.classes[classId].classes) do
			if asc.name and asc.name:lower() == want then
				spec:SelectAscendClass(aid)
				found = asc.name
				break
			end
		end
		if not found then
			local valid = {}
			for _, asc in pairs(tree.classes[classId].classes) do
				if asc.name and asc.name ~= "" and asc.name ~= "None" then
					valid[#valid + 1] = asc.name
				end
			end
			table.sort(valid)
			return {
				ok = false,
				error = "unknown ascendancy '"
					.. tostring(p.ascendancy)
					.. "' for class "
					.. tostring(p.class)
					.. ". Valid ascendancies: "
					.. table.concat(valid, ", "),
			}
		end
	end

	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
	return {
		ok = true,
		class = spec.curClassName,
		ascendancy = spec.curAscendClassName,
		stats = collectStats(p.keys),
	}
end

-- Set the character level (1-100). Disables auto-leveling so the value sticks.
function methods.set_level(p)
	local lvl = tonumber(p and p.level)
	if not lvl then
		return { ok = false, error = "set_level requires numeric params.level" }
	end
	lvl = math.max(1, math.min(100, math.floor(lvl)))
	build.characterLevelAutoMode = false
	build.characterLevel = lvl
	if build.controls and build.controls.characterLevel then
		build.controls.characterLevel:SetText(tostring(lvl))
	end
	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
	return { ok = true, level = build.characterLevel, stats = collectStats(p.keys) }
end

function methods.load_build_xml(p)
	assert(p and p.xml, "load_build_xml requires params.xml")
	loadBuildFromXML(p.xml, p.name or "imported")
	runCallback("OnFrame")
	return { mainSkill = mainSkillName(), stats = collectStats(p.keys) }
end

-- Set the build's MAIN skill from PoB's paste format ("Fireball 20/0  1", one gem per line). This
-- REPLACES the current main socket group (auras/buffs added via add_skill_group are separate groups
-- and are preserved) so repeated calls don't pile up stale groups. On a parse failure it rolls the
-- build back and reports, rather than silently leaving a broken/"phantom" main skill.
function methods.paste_skill(p)
	assert(p and p.text, "paste_skill requires params.text")
	local list = build.skillsTab.socketGroupList
	local snapshot = build:SaveDB("code")
	local prevMain = build.mainSocketGroup
	local before = #list
	build.skillsTab:PasteSocketGroup(normalizeSkillText(p.text))
	if #list <= before then
		-- Nothing parsed: don't repoint main at a stale group (the old corruption). Restore + report.
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			error = "no gem could be parsed from the skill text. Use PoB paste format with ONE GEM "
				.. "PER LINE — 'Name level/quality count' (e.g. 'Arc 20/20 1') — the main skill "
				.. "first and each support on its own line. ' / ', '|' or ',' between gems also work.",
			mainSkill = mainSkillName(),
		}
	end
	-- The new group was appended at the end. Make it main and REMOVE the previous main group so
	-- set_skill replaces rather than accumulates (aura/buff groups are untouched).
	local newIndex = #list
	if prevMain and prevMain >= 1 and prevMain <= before and prevMain ~= newIndex then
		table.remove(list, prevMain)
		if newIndex > prevMain then
			newIndex = newIndex - 1
		end
	end
	if build.skillsTab.controls and build.skillsTab.controls.groupList then
		build.skillsTab.controls.groupList.selIndex = newIndex
		build.skillsTab.controls.groupList.selValue = list[newIndex]
	end
	selectMainSocketGroup(newIndex)
	-- A syntactically valid but unrecognized gem name parses into a group with no real skill (it
	-- would read ~0 DPS). Don't leave the build in that state — restore + report.
	if not mainSkillName() then
		loadBuildFromXML(snapshot)
		runCallback("OnFrame")
		return {
			ok = false,
			error = "the main gem name wasn't recognized as a skill — check spelling with "
				.. "find_skills. Build left unchanged.",
			mainSkill = mainSkillName(),
		}
	end
	return statResult(p.keys)
end

-- Add an ENABLED secondary socket group (an aura/herald/buff like Wrath or Archmage, or a second
-- skill) WITHOUT changing the main skill, so its buff/reservation applies to the active build.
-- This is how caster damage layers (auras, Archmage mana-stacking) get modelled.
function methods.add_skill_group(p)
	assert(p and p.text, "add_skill_group requires params.text")
	local prevMain = build.mainSocketGroup or 1
	build.skillsTab:PasteSocketGroup(normalizeSkillText(p.text))
	runCallback("OnFrame")
	-- keep the existing main skill; the new group stays enabled and applies its effect
	selectMainSocketGroup(prevMain)
	return statResult(p.keys)
end

function methods.set_main_socket_group(p)
	selectMainSocketGroup(p and p.index or 1)
	return statResult(p and p.keys)
end

function methods.get_stats(p)
	return statResult(p and p.keys)
end

-- Serialize the current build to PoB XML (same payload PoB compresses into a share code).
function methods.get_xml()
	return { xml = build:SaveDB("code") }
end

-- Standard PoB enemy elemental resistance per boss tier (matches PoB's GUI placeholders, which
-- headless otherwise ignores — leaving bosses at 0% resistance, which overstates non-penetration
-- DPS and hides the value of penetration/exposure).
local BOSS_ELE_RES = { Boss = 30, Pinnacle = 50, Uber = 50 }

-- Set combat/config options (configTab.input keys) and/or raw custom mods, then recompute.
function methods.set_config(p)
	p = p or {}
	local opts = (type(p.options) == "table") and p.options or {}
	for k, v in pairs(opts) do
		build.configTab.input[k] = v
	end
	-- When the caller sets the boss tier, apply that tier's standard enemy resistances so boss DPS
	-- is realistic (PoB only sets these as GUI placeholders). Explicit enemy*Resist in the same
	-- call wins; "None" clears them back to 0.
	local appliedRes
	if opts.enemyIsBoss ~= nil then
		local ele = BOSS_ELE_RES[opts.enemyIsBoss] or 0
		local ci = build.configTab.input
		if opts.enemyLightningResist == nil then
			ci.enemyLightningResist = ele
		end
		if opts.enemyColdResist == nil then
			ci.enemyColdResist = ele
		end
		if opts.enemyFireResist == nil then
			ci.enemyFireResist = ele
		end
		if opts.enemyChaosResist == nil then
			ci.enemyChaosResist = 0
		end
		appliedRes = ele
	end
	if type(p.customMods) == "string" then
		build.configTab.input.customMods = p.customMods
	end
	build.configTab:BuildModList()
	runCallback("OnFrame")
	local r = { stats = collectStats(p.keys) }
	if appliedRes ~= nil then
		r.enemyResist = {
			fire = build.configTab.input.enemyFireResist,
			cold = build.configTab.input.enemyColdResist,
			lightning = build.configTab.input.enemyLightningResist,
			chaos = build.configTab.input.enemyChaosResist,
			note = "Enemy resistances set to the "
				.. tostring(opts.enemyIsBoss)
				.. " tier (penetration/exposure now matter). Override via enemy*Resist.",
		}
	end
	return r
end

-- Parse raw PoB item text and place it in a slot (REPLACING what's there). Returns ok, slotOrErr.
-- PoB's parser throws (e.g. "attempt to index local 'item'") on an unrecognized base/malformed
-- block; we pcall it so callers get a message, not a raw traceback.
local function equipItemRaw(raw, slot)
	local items = build.itemsTab.items
	local before = {}
	for id in pairs(items) do
		before[id] = true
	end
	local ok, err = pcall(function()
		build.itemsTab:CreateDisplayItemFromRaw(raw)
		build.itemsTab:AddDisplayItem(true) -- add without auto-equip; we place it explicitly
	end)
	if not ok then
		return false, "parse error: " .. tostring(err)
	end
	local newItem
	for id, it in pairs(items) do
		if not before[id] then
			newItem = it
			break
		end
	end
	if not newItem then
		return false, "item not created (unrecognized base type?)"
	end
	local sl = slot or newItem:GetPrimarySlot()
	local sc = build.itemsTab.slots[sl]
	if not sc then
		return false, "unknown slot: " .. tostring(sl)
	end
	sc:SetSelItemId(newItem.id) -- replaces any existing item in the slot
	build.buildFlag = true
	build.modFlag = true
	return true, sl
end

-- Equip an item from raw PoB item text, REPLACING whatever is in the target slot.
-- p.slot optionally forces a slot (e.g. "Ring 2", "Weapon 2"); otherwise the item's primary slot.
function methods.add_item(p)
	assert(p and p.raw, "add_item requires params.raw")
	local ok, slotOrErr = equipItemRaw(p.raw, p.slot)
	if not ok then
		return {
			ok = false,
			error = "could not equip — check the BASE TYPE is a real PoE2 base on its own line "
				.. "directly under the name, and the block is well-formed (Rarity / name / base, "
				.. "then mods). For attack weapons an unbound base has no attack rate and breaks "
				.. "DPS. ("
				.. slotOrErr
				.. ")",
		}
	end
	runCallback("OnFrame")
	return { ok = true, slot = slotOrErr, stats = collectStats(p.keys) }
end

-- Batch-evaluate many candidate items in one slot, returning each one's requested stats. Used by
-- the gear optimizer to score crafted candidates in a single round-trip. Restores the build after.
function methods.eval_items(p)
	assert(p and p.slot and type(p.items) == "table", "eval_items requires slot + items[]")
	local keys = p.keys or { "TotalDPS" }
	local snapshot = build:SaveDB("code")
	local out = {}
	for i, raw in ipairs(p.items) do
		local ok = equipItemRaw(raw, p.slot)
		if ok then
			runCallback("OnFrame")
			out[i] = collectStats(keys)
		else
			out[i] = false -- candidate failed to parse/equip
		end
	end
	loadBuildFromXML(snapshot)
	runCallback("OnFrame")
	return { results = out }
end

-- Clear an equipment slot (e.g. "Ring 2", "Body Armour").
function methods.unequip_item(p)
	local slot = p and p.slot
	local sc = slot and build.itemsTab.slots[slot]
	if not sc then
		return { ok = false, error = "unknown slot: " .. tostring(slot) }
	end
	sc:SetSelItemId(0)
	build.buildFlag = true
	runCallback("OnFrame")
	return { ok = true, slot = slot, stats = collectStats(p.keys) }
end

-- Full read-back of the active build (so callers can see what they've assembled).
function methods.get_build()
	local spec = build.spec
	local notables, keystones, asc = {}, {}, {}
	for _, node in pairs(spec.allocNodes) do
		if node.ascendancyName then
			if node.type == "Notable" then
				table.insert(asc, node.name)
			end
		elseif node.type == "Keystone" then
			table.insert(keystones, node.name)
		elseif node.type == "Notable" then
			table.insert(notables, node.name)
		end
	end
	table.sort(notables)
	table.sort(keystones)
	table.sort(asc)

	local gems = {}
	local sg = build.skillsTab.socketGroupList[build.mainSocketGroup or 1]
	if sg and sg.gemList then
		for _, g in ipairs(sg.gemList) do
			local nm = g.nameSpec
			if (not nm or nm == "") and g.gemData and g.gemData.grantedEffect then
				nm = g.gemData.grantedEffect.name
			end
			if nm and nm ~= "" then
				table.insert(gems, { name = nm, level = g.level, quality = g.quality })
			end
		end
	end

	local gear = {}
	for slotName, slot in pairs(build.itemsTab.slots) do
		local id = slot.selItemId
		if id and id ~= 0 and build.itemsTab.items[id] then
			local it = build.itemsTab.items[id]
			gear[slotName] = { name = it.title, base = it.baseName }
		end
	end

	local used = spec:CountAllocNodes()
	local avail = availablePoints()
	local unspent = math.max(0, avail - used)
	local r = {
		class = spec.curClassName,
		ascendancy = spec.curAscendClassName,
		level = build.characterLevel,
		mainSkill = mainSkillName(),
		mainSkillGroup = gems,
		notables = notables,
		keystones = keystones,
		ascendancyNotables = asc,
		gear = gear,
		customMods = (build.configTab and build.configTab.input.customMods) or "",
		pointsUsed = used,
		pointsAvailable = avail,
		unspentPoints = unspent,
		skillGroupCount = #(build.skillsTab.socketGroupList or {}),
		stats = collectStats(),
	}
	-- An export with many unspent points reads to users as "missing" tree/campaign points; flag
	-- it so the assistant spends them (or explains why they're parked).
	if unspent > 3 then
		r.pointsNote = unspent
			.. " passive points are unspent (available "
			.. avail
			.. ", used "
			.. used
			.. "). Allocate them (optimize_passives / alloc_passive) or tell the user why "
			.. "they're parked — an export with unspent points looks incomplete."
	end
	return r
end

-- Enumerate PoB configuration options usable with set_config (filterable).
function methods.list_config_options(p)
	p = p or {}
	local q = tostring(p.query or ""):lower()
	local limit = p.limit or 60
	local varList = LoadModule("Modules/ConfigOptions")
	local out = {}
	for _, v in ipairs(varList) do
		if type(v) == "table" and v.var then
			local label = (v.label or ""):gsub("%^x%x%x%x%x%x%x", ""):gsub("%^%d", "")
			if q == "" or label:lower():find(q, 1, true) or v.var:lower():find(q, 1, true) then
				local entry = { var = v.var, type = v.type, label = label }
				if v.list then
					local vals = {}
					for _, o in ipairs(v.list) do
						table.insert(vals, o.val)
					end
					entry.values = vals
				end
				table.insert(out, entry)
				if #out >= limit then
					break
				end
			end
		end
	end
	return { count = #out, options = out }
end

-- Defensive summary. Elemental resists include PoB's area resistance penalty; the note
-- reports the *actual* penalty currently applied (default is Endgame -60% when unset).
function methods.get_defenses()
	local o = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local function n(k)
		return type(o[k]) == "number" and o[k] or nil
	end
	-- PoB applies configInput.resistancePenalty as a BASE to each elemental resist,
	-- falling back to -60 (Endgame) when the config is unset (see CalcSetup.lua).
	local cfg = (build.configTab and build.configTab.input) or {}
	local penalty = cfg.resistancePenalty or -60
	return {
		life = n("Life"),
		energyShield = n("EnergyShield"),
		mana = n("Mana"),
		ward = n("Ward"),
		armour = n("Armour"),
		evasion = n("Evasion"),
		blockChance = n("BlockChance"),
		spellBlockChance = n("SpellBlockChance"),
		resistances = {
			fire = n("FireResist"),
			cold = n("ColdResist"),
			lightning = n("LightningResist"),
			chaos = n("ChaosResist"),
		},
		resistOverCap = {
			fire = n("FireResistOverCap"),
			cold = n("ColdResistOverCap"),
			lightning = n("LightningResistOverCap"),
		},
		resistPenalty = penalty,
		totalEHP = n("TotalEHP"),
		note = ("Elemental resistances are shown net of PoB's configured area penalty "
			.. "(resistancePenalty = %d%%; PoB's Endgame default is -60%%, earlier acts smaller). "
			.. "The cap is 75%% — raise resists toward it with gear/tree; over-cap buffers "
			.. "penetration and curses. Adjust with set_config({resistancePenalty = -60})."):format(
			penalty
		),
	}
end

-- ---------------------------------------------------------------------------
-- passive tree
-- ---------------------------------------------------------------------------
local function nodeSummary(n)
	return {
		id = n.id,
		name = n.name,
		type = n.type,
		stats = n.sd,
		alloc = n.alloc or false,
		pathDist = n.pathDist,
		ascendancy = n.ascendancyName,
	}
end

local function findNode(key)
	local spec = build.spec
	if not spec or key == nil then return nil end
	if spec.nodes[key] then return spec.nodes[key] end
	if type(key) == "string" then
		local asnum = tonumber(key)
		if asnum and spec.nodes[asnum] then return spec.nodes[asnum] end
		local lname = key:lower()
		local best
		for _, node in pairs(spec.nodes) do
			if node.name and node.name:lower() == lname then
				if node.alloc then return node end
				if node.path and (not best or (node.pathDist or 1e9) < (best.pathDist or 1e9)) then
					best = node
				elseif not best then
					best = node
				end
			end
		end
		return best
	end
	return nil
end

local function statSnapshot()
	local out = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local snap = {}
	for _, k in ipairs(DEFAULT_STATS) do
		if type(out[k]) == "number" then snap[k] = out[k] end
	end
	return snap
end

local function statDelta(before)
	local snap = statSnapshot()
	local delta = {}
	for k, v in pairs(snap) do
		local d = v - (before[k] or 0)
		if math.abs(d) > 1e-9 then delta[k] = d end
	end
	return delta
end

function methods.search_passives(p)
	p = p or {}
	local terms = {}
	for t in tostring(p.query or ""):lower():gmatch("%w+") do
		terms[#terms + 1] = t
	end
	local wantType = p.node_type
	local limit = p.limit or 30
	-- Rank by how many query terms match (name + ascendancy + stat text), so multi-word and
	-- conceptual queries return the best partial matches instead of nothing. No query => browse.
	local scored = {}
	for _, node in pairs(build.spec.nodes) do
		if node.name and node.type ~= "ClassStart" and node.type ~= "AscendClassStart" then
			if (not wantType) or node.type == wantType then
				local hay = node.name:lower()
				if node.ascendancyName then
					hay = hay .. " " .. node.ascendancyName:lower()
				end
				if node.sd then
					hay = hay .. " " .. table.concat(node.sd, " "):lower()
				end
				local score = 0
				for _, t in ipairs(terms) do
					if hay:find(t, 1, true) then
						score = score + 1
					end
				end
				if #terms == 0 or score > 0 then
					scored[#scored + 1] = { node = node, score = score }
				end
			end
		end
	end
	-- most matched terms first, then reachable (lowest pathDist), then name for a stable order
	table.sort(scored, function(a, b)
		if a.score ~= b.score then
			return a.score > b.score
		end
		local pa, pb = a.node.pathDist or 1e9, b.node.pathDist or 1e9
		if pa ~= pb then
			return pa < pb
		end
		return (a.node.name or "") < (b.node.name or "")
	end)
	local res = {}
	for i = 1, math.min(limit, #scored) do
		res[#res + 1] = nodeSummary(scored[i].node)
	end
	return { results = res }
end

function methods.get_passive(p)
	local n = findNode(p and p.node)
	if not n then return { found = false } end
	local s = nodeSummary(n)
	s.found = true
	return s
end

function methods.alloc_passive(p)
	local n = findNode(p and p.node)
	if not n then return { ok = false, error = "node not found" } end
	if n.alloc then return { ok = true, already = true, node = nodeSummary(n) } end
	if not n.path then return { ok = false, error = "node not reachable from current tree" } end
	local before = statSnapshot()
	local used = build.spec:CountAllocNodes()
	build.spec:AllocNode(n, nil)
	build.buildFlag = true
	runCallback("OnFrame")
	local usedAfter = build.spec:CountAllocNodes()
	local r = {
		ok = true,
		node = nodeSummary(n),
		pointsSpent = usedAfter - used,
		statsDelta = statDelta(before),
	}
	-- Warn if this pushed the tree past the level's point budget (the build is now invalid until
	-- you free points or level up) — otherwise over-allocation is silent.
	local avail = availablePoints()
	if usedAfter > avail then
		r.warning = "Tree is over budget: "
			.. usedAfter
			.. " points allocated but only "
			.. avail
			.. " available at level "
			.. (build.characterLevel or 0)
			.. ". Free "
			.. (usedAfter - avail)
			.. " (dealloc_passive) or raise the level before exporting."
	end
	return r
end

function methods.dealloc_passive(p)
	local n = findNode(p and p.node)
	if not n then return { ok = false, error = "node not found" } end
	if not n.alloc then return { ok = false, error = "node not allocated" } end
	local before = statSnapshot()
	local used = build.spec:CountAllocNodes()
	build.spec:DeallocNode(n)
	build.buildFlag = true
	runCallback("OnFrame")
	local usedAfter = build.spec:CountAllocNodes()
	return {
		ok = true,
		node = nodeSummary(n),
		pointsFreed = used - usedAfter,
		statsDelta = statDelta(before),
	}
end

-- Greedy passive optimizer: repeatedly allocate the reachable node (+ its path) that most
-- improves the goal, using PoB's what-if calculator to score candidates without committing.
-- Supports a single `metric` (absolute gain), `goals` = {metric=weight} (weighted *relative*
-- gain — generalizes the "balanced" DPS+EHP mode), and `require` = nodes to allocate first.
function methods.optimize_passives(p)
	p = p or {}
	local metric = p.metric or "TotalDPS"
	local balanced = (metric == "balanced" or metric == "DPS+EHP")
	-- weighted goals: explicit p.goals, else balanced => equal-weight DPS+EHP, else single-metric.
	local goals = (type(p.goals) == "table") and p.goals or nil
	if not goals and balanced then
		goals = { TotalDPS = 1, TotalEHP = 1 }
	end
	local budget = p.points
	if not budget or budget <= 0 then
		budget = math.max(0, availablePoints() - build.spec:CountAllocNodes())
	end
	local cap = p.candidates or 50
	local spec = build.spec
	local chosen = {}

	-- metrics we will report start/final for
	local mo0 = build.calcsTab.mainOutput
	local reportKeys = {}
	if goals then
		for m in pairs(goals) do
			reportKeys[#reportKeys + 1] = m
		end
	else
		reportKeys[1] = metric
	end
	local startVals = {}
	for _, m in ipairs(reportKeys) do
		startVals[m] = (mo0[m]) or 0
	end

	-- `require`: allocate the named nodes (+ shortest path) before optimizing, so they're included.
	local requiredSpent = 0
	if type(p.require) == "table" then
		for _, ref in ipairs(p.require) do
			local n = findNode(ref)
			if n and not n.alloc and n.path then
				local u0 = spec:CountAllocNodes()
				spec:AllocNode(n, nil)
				build.buildFlag = true
				runCallback("OnFrame")
				local spent = spec:CountAllocNodes() - u0
				requiredSpent = requiredSpent + spent
				chosen[#chosen + 1] = { name = n.name, id = n.id, cost = spent, required = true }
			end
		end
		budget = math.max(0, budget - requiredSpent)
	end

	-- weighted relative gain across goals (so DPS in thousands and CritChance 0-100 combine), or
	-- plain absolute gain for a single metric.
	local function scoreGain(calcBase, out)
		if goals then
			local g = 0
			for m, w in pairs(goals) do
				local b = (calcBase[m]) or 0
				local v = (out[m]) or 0
				if b > 0 then
					g = g + w * (v - b) / b
				else
					g = g + w * (v - b) * 1e-4 -- base 0 (e.g. crit on a non-crit build): tiny nudge
				end
			end
			return g
		end
		return ((out[metric]) or 0) - ((calcBase[metric]) or 0)
	end

	-- One greedy pass over a single node type until nothing helps or the budget runs out.
	local function greedyPass(nodeType, budgetLeft)
		local spent = 0
		while budgetLeft > 0 do
			local calcFunc, calcBase = build.calcsTab:GetMiscCalculator(build)
			local cands = {}
			for _, node in pairs(spec.nodes) do
				if
					not node.alloc
					and node.path
					and node.type == nodeType
					and node.pathDist
					and node.pathDist <= budgetLeft
				then
					cands[#cands + 1] = node
				end
			end
			-- Stable total order (pathDist, then id) so the greedy is deterministic — `pairs` order
			-- is unspecified and otherwise drifts between LuaJIT builds/platforms (local vs CI).
			table.sort(cands, function(a, b)
				local pa, pb = a.pathDist or 1e9, b.pathDist or 1e9
				if pa ~= pb then
					return pa < pb
				end
				return (a.id or 0) < (b.id or 0)
			end)

			local best, bestGain, bestCost
			for i = 1, math.min(#cands, cap) do
				local node = cands[i]
				local pathNodes = {}
				for _, pn in ipairs(node.path) do
					pathNodes[pn] = true
				end
				pathNodes[node] = true
				local gain = scoreGain(calcBase, calcFunc({ addNodes = pathNodes }))
				if gain > 0 and (not best or gain > bestGain) then
					best, bestGain, bestCost = node, gain, node.pathDist
				end
			end

			if not best then
				break
			end
			spec:AllocNode(best, nil)
			build.buildFlag = true
			runCallback("OnFrame")
			chosen[#chosen + 1] =
				{ name = best.name, id = best.id, cost = bestCost, gain = bestGain, type = nodeType }
			spent = spent + bestCost
			budgetLeft = budgetLeft - bestCost
		end
		return spent
	end

	local nodeType = p.node_type or "Notable"
	local used = greedyPass(nodeType, budget)
	budget = budget - used
	-- If filling the default (Notables), spend leftover budget on small (Normal) nodes too, so the
	-- tree isn't left point-starved — the common cause of "missing points" in exports.
	local smallUsed = 0
	if budget > 0 and nodeType == "Notable" then
		smallUsed = greedyPass("Normal", budget)
		used = used + smallUsed
		budget = budget - smallUsed
	end
	used = used + requiredSpent

	local mo1 = build.calcsTab.mainOutput
	local result = {
		metric = p.goals and "weighted" or metric,
		pointsUsed = used,
		pointsRemaining = math.max(0, budget),
		smallNodePoints = smallUsed,
		requiredPoints = requiredSpent,
		allocated = chosen,
	}
	if budget > 5 then
		result.note = budget
			.. " points still unspent — no remaining notable or small node improved the goal from "
			.. "here. Try different goals/weights, a different node_type, or alloc_passive toward a "
			.. "specific cluster; otherwise they're parked for later gear/scaling (say so)."
	end
	-- start/final for every reported metric
	local metricsOut = {}
	for _, m in ipairs(reportKeys) do
		metricsOut[m] = { start = startVals[m], final = (mo1[m]) or startVals[m] }
	end
	result.metrics = metricsOut
	-- back-compat fields
	if goals and goals.TotalDPS and goals.TotalEHP then
		result.startDPS, result.finalDPS = startVals.TotalDPS, (mo1.TotalDPS) or startVals.TotalDPS
		result.startEHP, result.finalEHP = startVals.TotalEHP, (mo1.TotalEHP) or startVals.TotalEHP
	elseif not goals then
		result.startValue = startVals[metric]
		result.finalValue = (mo1[metric]) or startVals[metric]
	end
	return result
end

-- ---------------------------------------------------------------------------
-- RPC loop
-- ---------------------------------------------------------------------------
emit(json.encode({ ready = true, jit = jit and jit.version, treeVersion = latestTreeVersion }))

for line in io.lines() do
	line = line:gsub("[\r\n]+$", "")
	if #line > 0 then
		local req = json.decode(line)
		local id = req and req.id
		local fn = req and methods[req.method]
		if not req then
			emit(json.encode({ ok = false, error = "malformed request" }))
		elseif not fn then
			emit(json.encode({ id = id, ok = false, error = "unknown method: " .. tostring(req.method) }))
		else
			local ok, result = pcall(fn, req.params or {})
			if ok then
				emit(json.encode({ id = id, ok = true, result = result }))
			else
				emit(json.encode({ id = id, ok = false, error = tostring(result) }))
			end
		end
	end
end
