"""Generate ``assets/icon.png`` — the icon shown for the .mcpb in Claude Desktop.

Mirrors the design in ``assets/icon.svg`` (an original passive-tree "constellation" mark, not
GGG's logo). Pillow is a dev-only tool, not a runtime/project dependency — install it ad hoc
(``uv pip install pillow``) and re-run this only when changing the icon. The committed
``assets/icon.png`` is what ships in the bundle.

    uv pip install pillow && uv run python scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = 512  # final icon size (Claude Desktop recommends 512×512)
S = 8  # supersample factor, downscaled at the end for antialiasing
W = 256 * S

DARK = (20, 17, 13, 255)
BORDER = (58, 47, 31, 255)
LINE = (122, 95, 48, 255)
NODE = (232, 185, 74, 255)
GLOW = (242, 193, 78)

CENTER = (128, 128)
SATS = [(74, 72), (188, 70), (196, 156), (92, 190), (170, 206)]
LINES = [
    (CENTER, (74, 72)),
    (CENTER, (188, 70)),
    (CENTER, (196, 156)),
    (CENTER, (92, 190)),
    ((74, 72), (188, 70)),
    ((196, 156), (170, 206)),
    ((92, 190), (170, 206)),
]


def _s(p: tuple[int, int]) -> tuple[int, int]:
    return (p[0] * S, p[1] * S)


def _disc(draw: ImageDraw.ImageDraw, c: tuple[int, int], r: int, fill: tuple[int, ...]) -> None:
    x, y = _s(c)
    rr = r * S
    draw.ellipse([x - rr, y - rr, x + rr, y + rr], fill=fill)


def main() -> None:
    base = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([0, 0, W - 1, W - 1], radius=48 * S, fill=DARK)
    d.rounded_rectangle(
        [6 * S, 6 * S, W - 6 * S, W - 6 * S], radius=44 * S, outline=BORDER, width=3 * S
    )
    for a, b in LINES:
        d.line([_s(a), _s(b)], fill=LINE, width=5 * S)

    # node glow on its own layer so the alpha composites over the background
    glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    _disc(gd, CENTER, 34, (*GLOW, 40))
    _disc(gd, CENTER, 24, (*GLOW, 56))
    base = Image.alpha_composite(base, glow)
    d = ImageDraw.Draw(base)

    for sat in SATS:
        r = 9 if sat == (170, 206) else 11
        x, y = _s(sat)
        rr = r * S
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=NODE, outline=DARK, width=3 * S)

    cx, cy = _s(CENTER)
    r = 18 * S
    d.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(247, 210, 113, 255),
        outline=(138, 106, 44, 255),
        width=4 * S,
    )
    r = 7 * S
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 242, 207, 255))

    out = base.resize((OUT, OUT), Image.LANCZOS)
    dst = Path(__file__).resolve().parents[1] / "assets" / "icon.png"
    out.save(dst)
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
