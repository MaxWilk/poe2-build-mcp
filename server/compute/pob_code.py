"""Encode/decode Path of Building import codes.

A PoB share code is ``urlsafe(base64(zlib(xml)))`` — confirmed against the fork source
(ImportTab.lua:133 export, :260 import): standard base64 with ``+``/``/`` swapped to
``-``/``_``, wrapping a standard zlib stream of the build XML.

The headless engine deliberately stubs Deflate/Inflate, so this (de)compression happens
here in Python; the engine only ever sees raw XML.
"""

from __future__ import annotations

import base64
import re
import zlib
from urllib.request import Request, urlopen

_WS = re.compile(r"\s+")
_LINK = re.compile(r"^\s*https?://", re.IGNORECASE)
_POBB = re.compile(r"^https?://pobb\.in/([A-Za-z0-9_-]+)/?$", re.IGNORECASE)
_PASTEBIN = re.compile(r"^https?://pastebin\.com/(?:raw/)?([A-Za-z0-9]+)/?$", re.IGNORECASE)


class PobCodeError(ValueError):
    """Raised when a PoB code/link cannot be decoded."""


def decode_code(code: str) -> str:
    """Decode a PoB import code into build XML."""
    if not code or not code.strip():
        raise PobCodeError("empty import code")
    s = _WS.sub("", code).replace("-", "+").replace("_", "/")
    s += "=" * ((-len(s)) % 4)  # restore stripped padding
    try:
        raw = base64.b64decode(s, validate=False)
    except Exception as e:  # noqa: BLE001 - normalize to one error type
        raise PobCodeError(f"invalid base64 in import code: {e}") from e
    try:
        xml = zlib.decompress(raw)
    except zlib.error as e:
        raise PobCodeError(f"invalid deflate stream in import code: {e}") from e
    return xml.decode("utf-8")


def encode_code(xml: str) -> str:
    """Encode build XML into a PoB import code (inverse of :func:`decode_code`)."""
    compressed = zlib.compress(xml.encode("utf-8"), 9)
    b64 = base64.b64encode(compressed).decode("ascii")
    return b64.replace("+", "-").replace("/", "_")


def is_link(source: str) -> bool:
    return bool(_LINK.match(source or ""))


def to_raw_url(url: str) -> str:
    """Map a pobb.in / pastebin page URL to its raw-code endpoint."""
    url = url.strip()
    m = _POBB.match(url)
    if m:
        return f"https://pobb.in/{m.group(1)}/raw"
    m = _PASTEBIN.match(url)
    if m:
        return f"https://pastebin.com/raw/{m.group(1)}"
    return url  # assume it already points at raw text


def fetch_code(url: str, timeout: float = 15.0) -> str:
    """Fetch a raw PoB code from a pobb.in/pastebin link (network)."""
    raw_url = to_raw_url(url)
    req = Request(raw_url, headers={"User-Agent": "poe2-build-mcp/0.1"})
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - http(s) only
            return resp.read().decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        raise PobCodeError(f"failed to fetch import code from {raw_url}: {e}") from e


def to_xml(source: str) -> str:
    """Accept a PoB code OR a pobb.in/pastebin link and return build XML."""
    source = (source or "").strip()
    if is_link(source):
        source = fetch_code(source)
    return decode_code(source)
