"""Render the Clearance app icon from its geometry.

Design A, "Stamp on a file", approved by the owner on 03/09/2026 from the
candidate sheet: a plum declaration with two ruled lines, and a mint stamp
disc overlapping its lower-right corner. Where the disc crosses the sheet the
colour goes dark teal — that overlap is the signature of the Odoo 19 icon
family (Project's tick over its square does the same thing).

Conventions taken from the real Odoo 19 icons, measured rather than assumed:
100 x 100, transparent, no tile, flat fills, glyph across ~80% of the canvas.

Run:  python tools/render_clearance_icon.py
Writes addons/elite_clearance/static/description/icon.png and icon.svg.
"""
import pathlib

from PIL import Image, ImageChops, ImageDraw

SIZE = 100
SS = 8          # supersample factor; the edges are smoothed by downscaling

SHEET = "#8C5183"        # plum, as Employees and Inventory use
RULE = "#B47FAC"         # the same plum lifted, for the ruled lines
STAMP = "#1ACFB0"        # mint, as Project and Purchase use
OVERLAP = "#0E6B62"      # dark teal where the stamp crosses the sheet

# x0, y0, x1, y1 in the 100 x 100 canvas
SHEET_BOX = (15, 9, 65, 85)
SHEET_R = 6
RULE_BOXES = ((26, 24, 54, 31), (26, 38, 54, 45))
RULE_R = 3.5
STAMP_C = (66, 65)
STAMP_R = 26

OUT = pathlib.Path(__file__).resolve().parent.parent / "addons/elite_clearance/static/description"


def _scaled(box):
    return [c * SS for c in box]


def _stamp_box():
    cx, cy = STAMP_C
    return (cx - STAMP_R, cy - STAMP_R, cx + STAMP_R, cy + STAMP_R)


def _mask(draw_on):
    m = Image.new("L", (SIZE * SS, SIZE * SS), 0)
    draw_on(ImageDraw.Draw(m))
    return m


def render_png():
    canvas = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    d.rounded_rectangle(_scaled(SHEET_BOX), radius=SHEET_R * SS, fill=SHEET)
    for box in RULE_BOXES:
        d.rounded_rectangle(_scaled(box), radius=int(RULE_R * SS), fill=RULE)
    d.ellipse(_scaled(_stamp_box()), fill=STAMP)

    # the darker third tone: exactly where the disc and the sheet coincide
    sheet_mask = _mask(lambda dr: dr.rounded_rectangle(
        _scaled(SHEET_BOX), radius=SHEET_R * SS, fill=255))
    stamp_mask = _mask(lambda dr: dr.ellipse(_scaled(_stamp_box()), fill=255))
    overlap = ImageChops.multiply(sheet_mask, stamp_mask)
    canvas.paste(Image.new("RGBA", canvas.size, OVERLAP), (0, 0), overlap)

    icon = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    path = OUT / "icon.png"
    icon.save(path, optimize=True)
    return path, icon


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <!-- Clearance Files. Design A, "Stamp on a file", approved 03/09/2026.
       A plum declaration, two ruled lines, and a mint stamp whose overlap
       with the sheet goes dark teal - the Odoo 19 icon convention. -->
  <defs>
    <clipPath id="sheet">
      <rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="{sr}"/>
    </clipPath>
  </defs>
  <rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="{sr}" fill="{sheet}"/>
  <rect x="26" y="24" width="28" height="7" rx="3.5" fill="{rule}"/>
  <rect x="26" y="38" width="28" height="7" rx="3.5" fill="{rule}"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{stamp}"/>
  <g clip-path="url(#sheet)">
    <circle cx="{cx}" cy="{cy}" r="{r}" fill="{overlap}"/>
  </g>
</svg>
'''


def render_svg():
    x0, y0, x1, y1 = SHEET_BOX
    path = OUT / "icon.svg"
    path.write_text(SVG.format(
        sx=x0, sy=y0, sw=x1 - x0, sh=y1 - y0, sr=SHEET_R,
        cx=STAMP_C[0], cy=STAMP_C[1], r=STAMP_R,
        sheet=SHEET, rule=RULE, stamp=STAMP, overlap=OVERLAP,
    ), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    png, image = render_png()
    svg = render_svg()
    corner = image.getpixel((0, 0))
    print("%s  %dx%d  %s  corner alpha=%d" % (
        png.name, image.width, image.height, image.mode, corner[3]))
    print("%s" % svg.name)
