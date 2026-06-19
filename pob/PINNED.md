# Pinned PoB-PoE2 dependency

The compute layer drives the Path of Building Community **PoE2** fork headless.
This file records the exact upstream we build against so the working copy (which is
git-ignored, not committed) is reproducible. At CI-setup time this becomes a proper
git submodule pinned to the commit below.

| Field | Value |
|-------|-------|
| Repo | https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 |
| Branch | `dev` |
| Pinned commit | `a82a33b` (2026-06-13, "Merge branch 'master' into dev") |
| License | MIT |
| Game data | passive tree version `0_5` |

## Reproduce the working copy

```sh
git clone --depth 1 --branch dev \
  https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git \
  pob/PathOfBuilding-PoE2
```

## Runtime requirements (validated in M0 spike)

- **LuaJIT 2.1** — installed on this machine via MSYS2:
  `pacman -S mingw-w64-ucrt-x86_64-luajit` → `C:\msys64\ucrt64\bin\luajit.exe`
- **lua-utf8** — required by `src/Modules/Common.lua`. For now satisfied by a pure-Lua
  ASCII shim in `pob/pob_headless.lua` (`package.preload["lua-utf8"]`). v1 packaging
  should bundle a real `luautf8` built against LuaJIT for correct non-ASCII handling.
- Pure-Lua deps (`dkjson`, `xml`, `base64`, `sha1`, `lua-profiler`) ship in the fork's
  `runtime/lua/` and resolve via `package.path = "../runtime/lua/?.lua"` when run from `src/`.
- `lcurl` is patched out by `HeadlessWrapper.lua`; `Deflate`/`Inflate` are stubbed, so PoB
  import codes must be inflated in Python and fed as XML (matches PLAN.md).

## How headless is invoked

Run with working directory = `pob/PathOfBuilding-PoE2/src`, mirroring the fork's `.busted`
config (`directory=src`, `lpath=../runtime/lua/?.lua`, `helper=HeadlessWrapper.lua`).
`pob/pob_headless.lua` boots the engine and exposes a line-delimited JSON-RPC loop.
