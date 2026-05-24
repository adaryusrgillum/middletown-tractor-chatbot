"""
Generate simple launcher icons for the PWA and Android APK.
Renders a green roundel with "MT" in white as a placeholder brand mark.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PRIMARY = (47, 122, 58, 255)
PRIMARY_DARK = (31, 85, 39, 255)
WHITE = (255, 255, 255, 255)


def make_icon(size: int, out_path: Path) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Filled circle
    d.ellipse((0, 0, size, size), fill=PRIMARY)
    # Inner ring
    pad = max(2, size // 32)
    d.ellipse((pad, pad, size - pad, size - pad), outline=PRIMARY_DARK, width=max(2, size // 64))
    # "MT" text
    text = "MT"
    font = None
    for f in ("arialbd.ttf", "Arial Bold.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(f, int(size * 0.46))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - size * 0.03), text, fill=WHITE, font=font)
    img.save(out_path, "PNG")
    print(f"wrote {out_path} ({size}x{size})")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    assets = root / "site_bundle" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for sz in (192, 512):
        make_icon(sz, assets / f"icon-{sz}.png")
    # Also write a 1024x1024 for Capacitor's icon-generation tooling
    make_icon(1024, assets / "icon-1024.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
