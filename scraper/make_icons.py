"""
Generate launcher icons for the PWA and Android APK.
Modern rounded square with a green-gradient surface, dark backdrop, and "MT" mark.
Matches the in-app dark / One UI 7 styling.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# Dark backdrop + brand green
BG_DARK = (10, 14, 12, 255)
PRIMARY = (82, 193, 104, 255)
PRIMARY_DARK = (47, 122, 58, 255)
WHITE = (255, 255, 255, 255)
INK = (6, 16, 8, 255)


def _gradient(size: int, top, bottom) -> Image.Image:
    """Vertical linear gradient `top` -> `bottom` over a `size`x`size` square."""
    grad = Image.new("RGBA", (1, size), (0, 0, 0, 0))
    for y in range(size):
        t = y / max(size - 1, 1)
        r = round(top[0] + (bottom[0] - top[0]) * t)
        g = round(top[1] + (bottom[1] - top[1]) * t)
        b = round(top[2] + (bottom[2] - top[2]) * t)
        a = round(top[3] + (bottom[3] - top[3]) * t)
        grad.putpixel((0, y), (r, g, b, a))
    return grad.resize((size, size))


def _rounded_mask(size: int, radius_frac: float = 0.24) -> Image.Image:
    """Squircle-ish mask: a rounded square with `radius` = `radius_frac` * size."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_frac)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=255)
    return mask


def make_icon(size: int, out_path: Path) -> None:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Dark rounded-square base
    base = Image.new("RGBA", (size, size), BG_DARK)
    base.putalpha(_rounded_mask(size))
    canvas.alpha_composite(base)

    # Inner green gradient pill with padding
    pad = int(size * 0.18)
    inner_size = size - pad * 2
    grad = _gradient(inner_size, PRIMARY, PRIMARY_DARK)
    grad_mask = _rounded_mask(inner_size, radius_frac=0.32)
    grad.putalpha(grad_mask)
    canvas.alpha_composite(grad, (pad, pad))

    # Soft glow above the inner pill for depth
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = int(inner_size * 0.32)
    gd.rounded_rectangle((pad, pad, pad + inner_size, pad + inner_size), radius=r,
                         outline=(255, 255, 255, 38), width=max(2, size // 96))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(1, size // 96)))
    canvas.alpha_composite(glow)

    # "MT" text
    text = "MT"
    font = None
    for f in ("arialbd.ttf", "Arial Bold.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(f, int(size * 0.44))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    d = ImageDraw.Draw(canvas)
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - w) / 2 - bbox[0]
    ty = (size - h) / 2 - bbox[1] - size * 0.03
    d.text((tx, ty), text, fill=INK, font=font)

    canvas.save(out_path, "PNG")
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
