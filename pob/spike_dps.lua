-- M0 spike (part 2): load a real skill and read a non-trivial DPS headless.
-- Run with working directory = <repo>/pob/PathOfBuilding-PoE2/src

package.path = "./?.lua;./?/init.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;" .. package.path

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

assert(pcall(dofile, "HeadlessWrapper.lua"))
assert(build, "build not initialised")

newBuild()

-- Bump character level so the numbers look like a real character (best-effort).
pcall(function()
	build.characterLevel = 90
	if build.controls and build.controls.characterLevel then
		build.controls.characterLevel:SetText("90")
	end
end)

-- Add a self-cast Fireball (level 20) the same way the test suite does.
build.skillsTab:PasteSocketGroup("Fireball 20/0  1")
runCallback("OnFrame")

-- Make sure socket group 1 / its first active skill is the main skill.
build.mainSocketGroup = 1
local sg = build.skillsTab.socketGroupList[1]
if sg then
	sg.mainActiveSkill = 1
	sg.mainActiveSkillCalcs = 1
end
build.calcsTab.input.skill_number = 1
build.buildFlag = true
build.modFlag = true
runCallback("OnFrame")

local out = build.calcsTab.mainOutput
local function show(label, k)
	print(string.format("    %-18s = %s", label, tostring(out[k])))
end

print("[spike] character level   = " .. tostring(build.characterLevel))
local main = build.skillsTab.socketGroupList[1]
local nm = main and main.displaySkillList and main.displaySkillList[main.mainActiveSkill]
	and main.displaySkillList[main.mainActiveSkill].activeEffect.grantedEffect.name
print("[spike] main skill        = " .. tostring(nm))
print("[spike] --- computed combat stats (Fireball 20, lvl 90) ---")
show("TotalDPS", "TotalDPS")
show("FullDPS", "FullDPS")
show("AverageDamage", "AverageDamage")
show("Speed (casts/s)", "Speed")
show("CritChance", "CritChance")
show("ManaCost", "ManaCost")
print("[spike] --- character pools ---")
show("Life", "Life")
show("Mana", "Mana")
show("EnergyShield", "EnergyShield")
show("TotalEHP", "TotalEHP")
print("[spike] DONE")
