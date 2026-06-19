"""Build the bundled PoE2 corpus (SQLite + FTS5) from the RePoE PoE2 data export.

Fetches a small set of RePoE JSON files (cached under data/raw/), normalizes them, and
writes data/corpus.sqlite with full-text search over item bases, skill/support gems, and
ascendancies. Mods + stat-translation resolution are a follow-up (M2.1).

Run:  uv run python -m pipeline.build_corpus  [--refresh]
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
DB_PATH = REPO_ROOT / "data" / "corpus.sqlite"
BASE = "https://repoe-fork.github.io/poe2/"
SOURCE_FILES = [
    "base_items.min.json",
    "skill_gems.min.json",
    "skills.min.json",
    "ascendancies.min.json",
    "mods.min.json",
]
# Uniques (with full readable mods) come from the vendored PoB data, not RePoE.
UNIQUES_DIR = REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src" / "Data" / "Uniques"
# Build-relevant mod domains (skip monster/area/heist/etc.).
MOD_DOMAINS = {"item", "flask"}

SCHEMA = """
CREATE TABLE items(
    id TEXT PRIMARY KEY, name TEXT, item_class TEXT, drop_level INTEGER, tags TEXT, raw TEXT);
CREATE VIRTUAL TABLE items_fts USING fts5(item_id UNINDEXED, name, item_class, tags);

CREATE TABLE gems(
    id TEXT PRIMARY KEY, name TEXT, color TEXT, gem_type TEXT, tags TEXT,
    grants TEXT, supports TEXT, description TEXT, types TEXT, raw TEXT);
CREATE VIRTUAL TABLE gems_fts USING fts5(gem_id UNINDEXED, name, tags, description);

CREATE TABLE ascendancies(id TEXT PRIMARY KEY, name TEXT, class TEXT, flavour TEXT, raw TEXT);

CREATE TABLE mods(
    id TEXT PRIMARY KEY, name TEXT, text TEXT, type TEXT, domain TEXT,
    required_level INTEGER, tags TEXT, stat_ids TEXT, groups TEXT, ranges TEXT);
CREATE VIRTUAL TABLE mods_fts USING fts5(mod_id UNINDEXED, name, text, tags, stat_ids);

CREATE TABLE uniques(
    id TEXT PRIMARY KEY, name TEXT, base TEXT, item_type TEXT, text TEXT, raw TEXT);
CREATE VIRTUAL TABLE uniques_fts USING fts5(unique_id UNINDEXED, name, base, text);

CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _seg(metadata_id: str) -> str:
    return metadata_id.rsplit("/", 1)[-1]


LINK_RE = re.compile(r"\[([^\]|]+)(?:\|[^\]]+)?\]")
CURLY_RE = re.compile(r"\{[^}]*\}")
BLOCK_RE = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)


def clean_text(t: str) -> str:
    """Strip PoE [display|link] markup, leaving the display text."""
    return LINK_RE.sub(r"\1", t or "")


def clean_mod_line(t: str) -> str:
    """Strip PoB {tags:...}/{variant:...} and [display|link] markup from an item line."""
    return clean_text(CURLY_RE.sub("", t or "")).strip()


def parse_uniques() -> list[dict]:
    """Parse PoB's Uniques/*.lua [[ ... ]] blocks into readable unique records."""
    out: list[dict] = []
    for path in sorted(UNIQUES_DIR.glob("*.lua")):
        item_type = path.stem
        for block in BLOCK_RE.findall(path.read_text("utf-8")):
            lines = [ln for ln in (x.rstrip() for x in block.strip("\n").split("\n")) if ln.strip()]
            if len(lines) < 2:
                continue
            name = clean_mod_line(lines[0])
            base = clean_mod_line(lines[1])
            text = "\n".join(clean_mod_line(ln) for ln in lines)
            out.append(
                {
                    "id": name,
                    "name": name,
                    "base": base,
                    "item_type": item_type,
                    "text": text,
                    "raw": block.strip("\n"),
                }
            )
    return out


def fetch_all(refresh: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name in SOURCE_FILES:
        dest = RAW_DIR / name
        if dest.exists() and not refresh:
            continue
        print(f"fetching {name} ...")
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "poe2-build-mcp/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())


def _load(name: str) -> dict:
    return json.loads((RAW_DIR / name).read_text("utf-8"))


def build() -> dict[str, int]:
    base_items = _load("base_items.min.json")
    skill_gems = _load("skill_gems.min.json")
    skills = _load("skills.min.json")
    ascendancies = _load("ascendancies.min.json")
    mods_data = _load("mods.min.json")

    # Resolve recommended_supports metadata ids -> human display names (ids vary Gem/Gems).
    gem_name_by_seg = {_seg(k): g["base_item"]["display_name"] for k, g in skill_gems.items()}

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    cur = con.cursor()

    n_items = 0
    for mid, it in base_items.items():
        name = it.get("name") or _seg(mid)
        item_class = it.get("item_class", "") or ""
        tags = it.get("tags") or []
        cur.execute(
            "INSERT INTO items(id,name,item_class,drop_level,tags,raw) VALUES(?,?,?,?,?,?)",
            (mid, name, item_class, it.get("drop_level"), json.dumps(tags), json.dumps(it)),
        )
        cur.execute(
            "INSERT INTO items_fts(item_id,name,item_class,tags) VALUES(?,?,?,?)",
            (mid, name, item_class, " ".join(tags)),
        )
        n_items += 1

    n_gems = 0
    for mid, g in skill_gems.items():
        name = g["base_item"]["display_name"]
        tags = g.get("tags") or []
        grants = g.get("grants_skills") or []
        supports = [
            gem_name_by_seg.get(_seg(s), _seg(s)) for s in (g.get("recommended_supports") or [])
        ]
        desc: str = ""
        types: list[str] = []
        for sid in grants:
            sk = skills.get(sid)
            if sk and sk.get("active_skill"):
                active = sk["active_skill"]
                desc = active.get("description") or desc
                types = active.get("types") or types
                if desc:
                    break
        cur.execute(
            "INSERT INTO gems(id,name,color,gem_type,tags,grants,supports,description,types,raw) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                name,
                g.get("color"),
                g.get("gem_type"),
                json.dumps(tags),
                json.dumps(grants),
                json.dumps(supports),
                desc,
                json.dumps(types),
                json.dumps(g),
            ),
        )
        cur.execute(
            "INSERT INTO gems_fts(gem_id,name,tags,description) VALUES(?,?,?,?)",
            (mid, name, " ".join(tags), desc),
        )
        n_gems += 1

    n_asc = 0
    for aid, a in ascendancies.items():
        asc_name = a.get("name") or ""
        if a.get("disabled") or asc_name.startswith("["):  # skip dev/unused placeholders
            continue
        # "character" is a big list of metadata paths; the plain class name is the lone
        # entry that isn't a Metadata/ path (e.g. "Druid").
        chars = a.get("character")
        cls = None
        if isinstance(chars, list):
            cls = next(
                (c for c in chars if isinstance(c, str) and not c.startswith("Metadata/")), None
            )
        elif isinstance(chars, str):
            cls = chars
        slim = {
            "name": a.get("name"),
            "class": cls,
            "flavour": a.get("flavour_text"),
            "class_number": a.get("class_number"),
        }
        cur.execute(
            "INSERT INTO ascendancies(id,name,class,flavour,raw) VALUES(?,?,?,?,?)",
            (aid, a.get("name"), cls, a.get("flavour_text"), json.dumps(slim)),
        )
        n_asc += 1

    n_mods = 0
    for mid, m in mods_data.items():
        if m.get("domain") not in MOD_DOMAINS:
            continue
        text = clean_text(m.get("text") or "")
        if not text:
            continue
        tags = sorted(
            {w["tag"] for w in (m.get("spawn_weights") or []) if w.get("weight") and w.get("tag")}
        )
        stats = m.get("stats") or []
        stat_ids = [s.get("id") for s in stats if s.get("id")]
        ranges = [
            {"id": s.get("id"), "min": s.get("min"), "max": s.get("max")}
            for s in stats
            if s.get("id")
        ]
        cur.execute(
            "INSERT INTO mods(id,name,text,type,domain,required_level,tags,stat_ids,groups,ranges) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                m.get("name"),
                text,
                m.get("generation_type"),
                m.get("domain"),
                m.get("required_level"),
                json.dumps(tags),
                json.dumps(stat_ids),
                json.dumps(m.get("groups") or []),
                json.dumps(ranges),
            ),
        )
        cur.execute(
            "INSERT INTO mods_fts(mod_id,name,text,tags,stat_ids) VALUES(?,?,?,?,?)",
            (mid, m.get("name") or "", text, " ".join(tags), " ".join(stat_ids)),
        )
        n_mods += 1

    n_uniques = 0
    seen_uniques: set[str] = set()
    for u in parse_uniques():
        if u["name"] in seen_uniques:
            continue
        seen_uniques.add(u["name"])
        cur.execute(
            "INSERT INTO uniques(id,name,base,item_type,text,raw) VALUES(?,?,?,?,?,?)",
            (u["id"], u["name"], u["base"], u["item_type"], u["text"], u["raw"]),
        )
        cur.execute(
            "INSERT INTO uniques_fts(unique_id,name,base,text) VALUES(?,?,?,?)",
            (u["id"], u["name"], u["base"], u["text"]),
        )
        n_uniques += 1

    counts = {
        "items": n_items,
        "gems": n_gems,
        "ascendancies": n_asc,
        "mods": n_mods,
        "uniques": n_uniques,
    }
    for key, value in {
        "source": BASE,
        "schema_version": "3",
        "counts": json.dumps(counts),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }.items():
        cur.execute("INSERT INTO meta(key,value) VALUES(?,?)", (key, value))

    con.commit()
    con.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    refresh = "--refresh" in (argv or sys.argv[1:])
    fetch_all(refresh=refresh)
    counts = build()
    print(f"built {DB_PATH}")
    print("counts:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
