"""Draws the C3CAST logo (broadcast mark, amber on a dark tile) into webapp/static and docs/: SVG, favicon, exe icon, PNG."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
AMBER, BG, EDGE = (240, 165, 44, 255), (11, 15, 19, 255), (47, 60, 72, 255)
S = 4


def draw(size):
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = n / 512
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=int(112 * k), fill=BG, outline=EDGE, width=max(1, int(4 * k)))
    c = n // 2
    d.ellipse((c - 34 * k, c - 34 * k, c + 34 * k, c + 34 * k), fill=AMBER)
    for r in (105, 165, 225):
        box = (c - r * k, c - r * k, c + r * k, c + r * k)
        d.arc(box, -46, 46, fill=AMBER, width=int(26 * k))
        d.arc(box, 134, 226, fill=AMBER, width=int(26 * k))
    return img.resize((size, size), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect x="2" y="2" width="508" height="508" rx="112" fill="#0b0f13" stroke="#2f3c48" stroke-width="4"/>
<g fill="none" stroke="#f0a52c" stroke-width="26">
<path d="M{a} A105 105 0 0 0 {b}M{c} A105 105 0 0 0 {d}"/>
<path d="M{e} A165 165 0 0 0 {f}M{g} A165 165 0 0 0 {h}"/>
<path d="M{i} A225 225 0 0 0 {j}M{k} A225 225 0 0 0 {l}"/>
</g><circle cx="256" cy="256" r="34" fill="#f0a52c"/></svg>
"""

if __name__ == "__main__":
    import math

    def pt(r, deg):
        return f"{256 + r * math.cos(math.radians(deg)):.1f} {256 - r * math.sin(math.radians(deg)):.1f}"
    v = {}
    for r, names in ((105, "abcd"), (165, "efgh"), (225, "ijkl")):
        v[names[0]], v[names[1]] = pt(r, -46), pt(r, 46)      # right arc, bottom to top
        v[names[2]], v[names[3]] = pt(r, 134), pt(r, 226)     # left arc, top to bottom
    static = ROOT / "webapp" / "static"
    (static / "logo.svg").write_text(SVG.format(**v), encoding="utf-8")
    draw(512).save(ROOT / "docs" / "logo.png")
    draw(32).save(static / "favicon.png")
    draw(256).save(static / "c3cast.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    print("logo assets written")
