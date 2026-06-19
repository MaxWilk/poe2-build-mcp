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
	"TotalEHP", "Ward", "Armour", "Evasion", "Str", "Dex", "Int",
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
		return { ok = false, error = "unknown class: " .. tostring(p.class) }
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
			return {
				ok = false,
				error = "unknown ascendancy '"
					.. tostring(p.ascendancy)
					.. "' for class "
					.. tostring(p.class),
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

-- Add a socket group from PoB's paste format, e.g. "Fireball 20/0  1".
function methods.paste_skill(p)
	assert(p and p.text, "paste_skill requires params.text")
	build.skillsTab:PasteSocketGroup(p.text)
	runCallback("OnFrame")
	selectMainSocketGroup(p.socketGroup or #build.skillsTab.socketGroupList)
	return { mainSkill = mainSkillName(), stats = collectStats(p.keys) }
end

function methods.set_main_socket_group(p)
	selectMainSocketGroup(p and p.index or 1)
	return { mainSkill = mainSkillName(), stats = collectStats(p and p.keys) }
end

function methods.get_stats(p)
	return { mainSkill = mainSkillName(), stats = collectStats(p and p.keys) }
end

-- Serialize the current build to PoB XML (same payload PoB compresses into a share code).
function methods.get_xml()
	return { xml = build:SaveDB("code") }
end

-- Set combat/config options (configTab.input keys) and/or raw custom mods, then recompute.
function methods.set_config(p)
	p = p or {}
	if type(p.options) == "table" then
		for k, v in pairs(p.options) do
			build.configTab.input[k] = v
		end
	end
	if type(p.customMods) == "string" then
		build.configTab.input.customMods = p.customMods
	end
	build.configTab:BuildModList()
	runCallback("OnFrame")
	return { stats = collectStats(p.keys) }
end

-- Equip an item from raw PoB item text, REPLACING whatever is in the target slot.
-- p.slot optionally forces a slot (e.g. "Ring 2", "Weapon 2"); otherwise the item's primary slot.
function methods.add_item(p)
	assert(p and p.raw, "add_item requires params.raw")
	local items = build.itemsTab.items
	local before = {}
	for id in pairs(items) do
		before[id] = true
	end
	build.itemsTab:CreateDisplayItemFromRaw(p.raw)
	build.itemsTab:AddDisplayItem(true) -- add without auto-equip; we place it explicitly
	local newItem
	for id, it in pairs(items) do
		if not before[id] then
			newItem = it
			break
		end
	end
	if not newItem then
		return { ok = false, error = "item not created (unrecognized base type?)" }
	end
	local slot = p.slot or newItem:GetPrimarySlot()
	local slotControl = build.itemsTab.slots[slot]
	if not slotControl then
		return { ok = false, error = "unknown slot: " .. tostring(slot) }
	end
	slotControl:SetSelItemId(newItem.id) -- replaces any existing item in the slot
	build.buildFlag = true
	build.modFlag = true
	runCallback("OnFrame")
	return { ok = true, slot = slot, stats = collectStats(p.keys) }
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

	return {
		class = spec.curClassName,
		ascendancy = spec.curAscendClassName,
		level = build.characterLevel,
		mainSkill = mainSkillName(),
		mainSkillGroup = gems,
		notables = notables,
		keystones = keystones,
		ascendancyNotables = asc,
		gear = gear,
		pointsUsed = spec:CountAllocNodes(),
		pointsAvailable = availablePoints(),
		stats = collectStats(),
	}
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

-- Defensive summary (resists include PoB's default Endgame -60% penalty; cap is 75%).
function methods.get_defenses()
	local o = (build.calcsTab and build.calcsTab.mainOutput) or {}
	local function n(k)
		return type(o[k]) == "number" and o[k] or nil
	end
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
		totalEHP = n("TotalEHP"),
		note = "Resistances include PoB's default Endgame -60% elemental resistance penalty; "
			.. "the cap is 75%. A fresh character starts at -60% and gear/tree bring it up.",
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
	local res = {}
	for _, node in pairs(build.spec.nodes) do
		if node.name and node.type ~= "ClassStart" and node.type ~= "AscendClassStart" then
			if (not wantType) or node.type == wantType then
				local hay = node.name:lower()
				if node.sd then
					hay = hay .. " " .. table.concat(node.sd, " "):lower()
				end
				local ok = true
				for _, t in ipairs(terms) do
					if not hay:find(t, 1, true) then
						ok = false
						break
					end
				end
				if ok then
					res[#res + 1] = nodeSummary(node)
					if #res >= limit then break end
				end
			end
		end
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
	return {
		ok = true,
		node = nodeSummary(n),
		pointsSpent = usedAfter - used,
		statsDelta = statDelta(before),
	}
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
-- improves `metric`, using PoB's what-if calculator to score candidates without committing.
function methods.optimize_passives(p)
	p = p or {}
	local metric = p.metric or "TotalDPS"
	-- points <= 0 means "use the remaining budget at this level" (level-aware optimize).
	local budget = p.points
	if not budget or budget <= 0 then
		budget = math.max(0, availablePoints() - build.spec:CountAllocNodes())
	end
	local cap = p.candidates or 50
	local nodeType = p.node_type or "Notable"
	local spec = build.spec
	local startValue = (build.calcsTab.mainOutput[metric]) or 0
	local chosen = {}
	local used = 0

	while budget > 0 do
		local calcFunc, calcBase = build.calcsTab:GetMiscCalculator(build)
		local baseVal = (calcBase[metric]) or 0

		local cands = {}
		for _, node in pairs(spec.nodes) do
			if
				not node.alloc
				and node.path
				and node.type == nodeType
				and node.pathDist
				and node.pathDist <= budget
			then
				cands[#cands + 1] = node
			end
		end
		table.sort(cands, function(a, b)
			return (a.pathDist or 1e9) < (b.pathDist or 1e9)
		end)

		local best, bestGain, bestCost
		for i = 1, math.min(#cands, cap) do
			local node = cands[i]
			local pathNodes = {}
			for _, pn in ipairs(node.path) do
				pathNodes[pn] = true
			end
			pathNodes[node] = true
			local out = calcFunc({ addNodes = pathNodes })
			local gain = ((out[metric]) or 0) - baseVal
			if gain > 0 and (not best or gain > bestGain) then
				best, bestGain, bestCost = node, gain, node.pathDist
			end
		end

		if not best then break end
		spec:AllocNode(best, nil)
		build.buildFlag = true
		runCallback("OnFrame")
		chosen[#chosen + 1] = { name = best.name, id = best.id, cost = bestCost, gain = bestGain }
		used = used + bestCost
		budget = budget - bestCost
	end

	return {
		metric = metric,
		startValue = startValue,
		finalValue = (build.calcsTab.mainOutput[metric]) or startValue,
		pointsUsed = used,
		allocated = chosen,
	}
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
