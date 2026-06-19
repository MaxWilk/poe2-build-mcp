"""Read-only access to the bundled PoE2 corpus (SQLite + FTS5).

This layer is independent of the calculation engine: it answers "what is / find me"
queries straight from the bundled database, no PoB process required.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .. import paths

_con: sqlite3.Connection | None = None


def db_path() -> Path:
    """Active corpus DB path: the auto-updated user copy if present, else the bundled seed."""
    return paths.corpus_path()


def _conn() -> sqlite3.Connection:
    global _con
    if _con is None:
        p = db_path()
        if not p.exists():
            raise FileNotFoundError(
                f"corpus DB not found at {p}. Build it with: uv run python -m pipeline.build_corpus"
            )
        _con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)
        _con.row_factory = sqlite3.Row
    return _con


def reset() -> None:
    """Drop the cached connection so a freshly-built/updated corpus is picked up."""
    global _con
    if _con is not None:
        _con.close()
        _con = None


def _match(text: str) -> str:
    """Turn free text into an FTS5 prefix-AND query (safe against punctuation)."""
    terms = re.findall(r"\w+", text.lower())
    return " ".join(f"{t}*" for t in terms) if terms else '""'


def _match_cols(text: str, cols: tuple[str, ...]) -> str:
    """FTS5 prefix-AND query restricted to specific columns.

    Mod rows index readable name/text plus internal stat-id tokens; scoping a stat-text query
    to {name text} stops it matching unrelated mods via their stat ids (e.g. "physical damage"
    hitting an Armour mod whose stat id contains "physical_damage_reduction").
    """
    terms = re.findall(r"\w+", text.lower())
    if not terms:
        return '""'
    inner = " ".join(f"{t}*" for t in terms)
    return "{" + " ".join(cols) + "} : (" + inner + ")"


def corpus_info() -> dict[str, Any]:
    con = _conn()
    meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    if "counts" in meta:
        meta["counts"] = json.loads(meta["counts"])
    return meta


def search_items(query: str = "", item_class: str | None = None, limit: int = 20) -> list[dict]:
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT i.id, i.name, i.item_class, i.drop_level, i.tags "
            "FROM items_fts f JOIN items i ON i.id = f.item_id WHERE items_fts MATCH ? "
        )
        params.append(_match(query))
    else:
        sql = "SELECT i.id, i.name, i.item_class, i.drop_level, i.tags FROM items i WHERE 1=1 "
    if item_class:
        sql += "AND i.item_class = ? "
        params.append(item_class)
    sql += "LIMIT ?"
    params.append(limit)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "item_class": r["item_class"],
            "drop_level": r["drop_level"],
            "tags": json.loads(r["tags"]),
        }
        for r in con.execute(sql, params)
    ]


def get_item(name_or_id: str) -> dict | None:
    con = _conn()
    row = con.execute(
        "SELECT raw FROM items WHERE id = ? OR lower(name) = lower(?) LIMIT 1",
        (name_or_id, name_or_id),
    ).fetchone()
    return json.loads(row["raw"]) if row else None


def find_skills(
    query: str = "",
    gem_type: str | None = None,
    tag: str | None = None,
    color: str | None = None,
    limit: int = 30,
) -> list[dict]:
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT g.id, g.name, g.color, g.gem_type, g.tags, g.supports, g.description "
            "FROM gems_fts f JOIN gems g ON g.id = f.gem_id WHERE gems_fts MATCH ? "
        )
        params.append(_match(query))
    else:
        sql = (
            "SELECT g.id, g.name, g.color, g.gem_type, g.tags, g.supports, g.description "
            "FROM gems g WHERE 1=1 "
        )
    if gem_type:
        sql += "AND g.gem_type = ? "
        params.append(gem_type)
    if color:
        sql += "AND g.color = ? "
        params.append(color)
    if tag:
        sql += "AND g.tags LIKE ? "
        params.append(f'%"{tag}"%')
    sql += "LIMIT ?"
    params.append(limit)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "color": r["color"],
            "gem_type": r["gem_type"],
            "tags": json.loads(r["tags"]),
            "supports": json.loads(r["supports"]),
            "description": r["description"],
        }
        for r in con.execute(sql, params)
    ]


def get_gem(name_or_id: str) -> dict | None:
    con = _conn()
    row = con.execute(
        "SELECT id, name, color, gem_type, tags, grants, supports, description, types "
        "FROM gems WHERE id = ? OR lower(name) = lower(?) LIMIT 1",
        (name_or_id, name_or_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "color": row["color"],
        "gem_type": row["gem_type"],
        "tags": json.loads(row["tags"]),
        "grants": json.loads(row["grants"]),
        "supports": json.loads(row["supports"]),
        "description": row["description"],
        "types": json.loads(row["types"]),
    }


def list_ascendancies(character: str | None = None) -> list[dict]:
    con = _conn()
    if character:
        rows = con.execute(
            "SELECT name, class, flavour FROM ascendancies WHERE lower(class) = lower(?) "
            "ORDER BY class, name",
            (character,),
        )
    else:
        rows = con.execute("SELECT name, class, flavour FROM ascendancies ORDER BY class, name")
    return [{"name": r["name"], "class": r["class"], "flavour": r["flavour"]} for r in rows]


def search_mods(
    query: str = "",
    item_tag: str | None = None,
    mod_type: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Search affixes/modifiers by readable text. `item_tag` filters by what it rolls on
    (e.g. "ring", "amulet", "body_armour"); `mod_type` is "prefix" or "suffix"."""
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT m.id, m.name, m.text, m.type, m.tags, m.required_level "
            "FROM mods_fts f JOIN mods m ON m.id = f.mod_id WHERE mods_fts MATCH ? "
        )
        params.append(_match_cols(query, ("name", "text")))
    else:
        sql = "SELECT m.id, m.name, m.text, m.type, m.tags, m.required_level FROM mods m WHERE 1=1 "
    if item_tag:
        sql += "AND m.tags LIKE ? "
        params.append(f'%"{item_tag}"%')
    if mod_type:
        sql += "AND m.type = ? "
        params.append(mod_type)
    sql += "LIMIT ?"
    params.append(limit)
    return [
        {
            "name": r["name"],
            "text": r["text"],
            "type": r["type"],
            "required_level": r["required_level"],
            "rolls_on": json.loads(r["tags"]),
        }
        for r in con.execute(sql, params)
    ]


def reverse_lookup(stat: str, limit: int = 30) -> dict[str, list[dict]]:
    """Find sources of a stat across mods, gems, and uniques (by readable text)."""
    con = _conn()
    q = _match(stat)
    qm = _match_cols(stat, ("name", "text"))
    out: dict[str, list[dict]] = {"mods": [], "gems": [], "uniques": []}
    for r in con.execute(
        "SELECT m.name, m.text, m.type, m.tags FROM mods_fts f JOIN mods m ON m.id = f.mod_id "
        "WHERE mods_fts MATCH ? LIMIT ?",
        (qm, limit),
    ):
        out["mods"].append(
            {
                "name": r["name"],
                "text": r["text"],
                "type": r["type"],
                "rolls_on": json.loads(r["tags"]),
            }
        )
    for r in con.execute(
        "SELECT g.name, g.gem_type, g.description FROM gems_fts f JOIN gems g ON g.id = f.gem_id "
        "WHERE gems_fts MATCH ? LIMIT ?",
        (q, limit),
    ):
        out["gems"].append(
            {"name": r["name"], "gem_type": r["gem_type"], "description": r["description"]}
        )
    for r in con.execute(
        "SELECT u.name, u.base FROM uniques_fts f JOIN uniques u ON u.id = f.unique_id "
        "WHERE uniques_fts MATCH ? LIMIT ?",
        (q, limit),
    ):
        out["uniques"].append({"name": r["name"], "base": r["base"]})
    return out


def search_uniques(query: str = "", item_type: str | None = None, limit: int = 20) -> list[dict]:
    """Search unique items by name/base/mod text. `item_type` filters by slot family
    (e.g. "ring", "body", "bow")."""
    con = _conn()
    params: list[Any] = []
    if query:
        sql = (
            "SELECT u.id, u.name, u.base, u.item_type "
            "FROM uniques_fts f JOIN uniques u ON u.id = f.unique_id WHERE uniques_fts MATCH ? "
        )
        params.append(_match(query))
    else:
        sql = "SELECT u.id, u.name, u.base, u.item_type FROM uniques u WHERE 1=1 "
    if item_type:
        sql += "AND u.item_type = ? "
        params.append(item_type)
    sql += "LIMIT ?"
    params.append(limit)
    return [
        {"name": r["name"], "base": r["base"], "item_type": r["item_type"]}
        for r in con.execute(sql, params)
    ]


def get_unique(name: str) -> dict | None:
    """Return a unique item's full readable text by name."""
    con = _conn()
    row = con.execute(
        "SELECT name, base, item_type, text FROM uniques WHERE lower(name) = lower(?) LIMIT 1",
        (name,),
    ).fetchone()
    if not row:
        return None
    return {
        "name": row["name"],
        "base": row["base"],
        "item_type": row["item_type"],
        "text": row["text"],
    }
