"""poe2-build-mcp — MCP server for Path of Exile 2 build analysis and theorycrafting."""

# When running from a self-contained bundle, activate the vendored dependency directory
# (lib/). Prepend it so bundled deps take precedence over any system site-packages, and run
# addsitedir so .pth hooks (e.g. pywin32's native DLL setup) execute. No-op in a dev checkout.
import site as _site
import sys as _sys
from pathlib import Path as _Path

_lib = _Path(__file__).resolve().parents[1] / "lib"
if _lib.is_dir():
    _lib_str = str(_lib)
    if _lib_str not in _sys.path:
        _sys.path.insert(0, _lib_str)
    _site.addsitedir(_lib_str)
