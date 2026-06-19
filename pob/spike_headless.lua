-- M0 spike: prove the PoB-PoE2 calc engine runs headless under LuaJIT.
-- Must be run with the working directory set to <repo>/pob/PathOfBuilding-PoE2/src
-- (HeadlessWrapper.lua does dofile("Launch.lua") with relative paths, mirroring .busted).

-- Resolve runtime/lua deps (base64, dkjson, xml, sha1, ...) relative to src/.
package.path = "./?.lua;./?/init.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;" .. package.path

-- Pure-Lua stand-in for the lua-utf8 C module. ASCII-correct only, which is fine for the
-- spike (English build data). v1 will use a real luautf8 built against LuaJIT.
package.preload["lua-utf8"] = function()
	local u = {}
	for _, k in ipairs({ "find", "gmatch", "gsub", "match", "sub", "reverse",
		"len", "char", "byte", "upper", "lower", "rep", "format" }) do
		u[k] = string[k]
	end
	u.offset = function(s, n, i) return (i or 1) + (n or 0) end
	u.next = function(s, i)
		i = (i or 0) + 1
		if i > #s then return nil end
		return i, s:byte(i)
	end
	u.charpos = function(s, i) return i or 1 end
	u.width = function() return 1 end
	return u
end

print("[spike] LuaJIT: " .. tostring(_VERSION) .. " / " .. (jit and jit.version or "?"))
print("[spike] loading HeadlessWrapper.lua ...")
local ok, err = pcall(dofile, "HeadlessWrapper.lua")
if not ok then
	print("[spike] FAIL during HeadlessWrapper/Launch init:\n  " .. tostring(err))
	os.exit(1)
end
print("[spike] HeadlessWrapper loaded OK")

if not build then
	print("[spike] FAIL: global 'build' was not set")
	os.exit(1)
end

print("[spike] creating a fresh build ...")
newBuild()
runCallback("OnFrame")

local ct = build.calcsTab
print("[spike] calcsTab present: " .. tostring(ct ~= nil))
print("[spike] mainEnv present : " .. tostring(ct and ct.mainEnv ~= nil))
local out = (ct and ct.mainOutput) or {}

local function show(k)
	print(string.format("    %-16s = %s", k, tostring(out[k])))
end

print("[spike] sample stats on a fresh build:")
for _, k in ipairs({ "Str", "Dex", "Int", "Life", "Mana", "EnergyShield",
	"TotalDPS", "AverageDamage", "TotalEHP" }) do
	show(k)
end

print("[spike] DONE (engine booted and computed headless)")
