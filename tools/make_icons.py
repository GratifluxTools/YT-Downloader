"""Generate the app icon: src/assets/icon.png (1024px), packaging/yt-downloader.png (256px), packaging/icon.ico.

    pip install pillow
    python tools/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 2048           # supersampled canvas, downscaled to 1024
OUT = 1024
ROOT = Path(__file__).resolve().parent.parent


def gradient(c1, c2):
    v = Image.linear_gradient("L").resize((S, S))
    h = v.transpose(Image.Transpose.ROTATE_90)
    m = ImageChops.add(v, h, scale=2)                       # diagonal gradient mask
    return Image.composite(Image.new("RGB", (S, S), c2), Image.new("RGB", (S, S), c1), m)


def glyph_layer():
    g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    w = (255, 255, 255, 255)
    k = S / 1024
    P = lambda pts: [(x * k, y * k) for x, y in pts]
    # arrow shaft + head
    d.rounded_rectangle([452 * k, 190 * k, 572 * k, 540 * k], radius=60 * k, fill=w)
    head = P([(318, 470), (706, 470), (512, 690)])
    d.polygon(head, fill=w)
    r = 26 * k  # round the three corners with circles + edge strokes (avoids joint artifacts)
    for (x1, y1), (x2, y2) in zip(head, head[1:] + head[:1]):
        d.line([(x1, y1), (x2, y2)], fill=w, width=int(2 * r))
        d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=w)
    # tray
    tray = P([(262, 650), (262, 790), (762, 790), (762, 650)])
    d.line(tray, fill=w, width=int(64 * k), joint="curve")
    for x, y in tray[::3]:
        d.ellipse([x - 32 * k, y - 32 * k, x + 32 * k, y + 32 * k], fill=w)
    return g


def main():
    bg = gradient((79, 70, 229), (219, 39, 119)).convert("RGBA")   # indigo -> pink
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)

    glyph = glyph_layer()
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.putalpha(glyph.split()[3].filter(ImageFilter.GaussianBlur(S * 0.012)).point(lambda a: int(a * 0.35)))
    shadow = ImageChops.offset(shadow, 0, int(S * 0.012))
    bg.alpha_composite(shadow)
    bg.alpha_composite(glyph)

    # "REC" dot (live / premiere support)
    d = ImageDraw.Draw(bg)
    k = S / 1024
    cx, cy = 800 * k, 232 * k
    d.ellipse([cx - 112 * k, cy - 112 * k, cx + 112 * k, cy + 112 * k], fill=(255, 255, 255, 255))
    d.ellipse([cx - 84 * k, cy - 84 * k, cx + 84 * k, cy + 84 * k], fill=(239, 68, 68, 255))

    bg.putalpha(mask)
    icon = bg.resize((OUT, OUT), Image.Resampling.LANCZOS)
    a = ROOT / "src" / "assets"
    a.mkdir(parents=True, exist_ok=True)
    icon.save(a / "icon.png")
    (ROOT / "packaging").mkdir(exist_ok=True)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(ROOT / "packaging" / "yt-downloader.png")
    icon.save(ROOT / "packaging" / "icon.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote", a / "icon.png", "and packaging/icon.ico")


if __name__ == "__main__":
    main()
