from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICO = ASSETS / "zeroreels.ico"
PNG = ASSETS / "zeroreels.png"


def font(size: int):
    for candidate in (
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def draw_icon(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    dark = "#0D131A"
    mint = "#63E6BE"
    white = "#F4F7FA"
    m = int(size * 0.035)
    radius = int(size * 0.19)
    draw.rounded_rectangle((m, m, size - m, size - m), radius=radius, fill=dark, outline=mint, width=max(8, int(size * 0.035)))

    reel_box = (int(size * 0.15), int(size * 0.14), int(size * 0.65), int(size * 0.64))
    draw.ellipse(reel_box, outline=mint, width=max(10, int(size * 0.045)))
    cx = (reel_box[0] + reel_box[2]) // 2
    cy = (reel_box[1] + reel_box[3]) // 2
    hr = int(size * 0.052)
    offset = int(size * 0.105)
    for dx, dy in ((-offset, -offset), (offset, -offset), (-offset, offset), (offset, offset)):
        draw.ellipse((cx + dx - hr, cy + dy - hr, cx + dx + hr, cy + dy + hr), fill=mint)
    draw.polygon(
        [
            (int(size * 0.38), int(size * 0.27)),
            (int(size * 0.38), int(size * 0.52)),
            (int(size * 0.58), int(size * 0.395)),
        ],
        fill=white,
    )

    zr = "ZR"
    f = font(int(size * 0.22))
    bbox = draw.textbbox((0, 0), zr, font=f)
    tw = bbox[2] - bbox[0]
    draw.text(((size - tw) / 2, size * 0.68), zr, font=f, fill=white, stroke_width=max(1, int(size * 0.004)), stroke_fill=dark)
    # Mint accent on the R keeps the icon tied to the app's existing UI color.
    z_width = draw.textlength("Z", font=f)
    draw.text(((size - tw) / 2 + z_width, size * 0.68), "R", font=f, fill=mint, stroke_width=max(1, int(size * 0.004)), stroke_fill=dark)
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = draw_icon()
    image.save(PNG)
    image.save(ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(ICO)


if __name__ == "__main__":
    main()
