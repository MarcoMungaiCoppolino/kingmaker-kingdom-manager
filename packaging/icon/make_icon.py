"""Writes kingmaker.ico (16 to 256 px) and kingmaker.png from party.png.

    python packaging/icon/make_icon.py

`party.png` is the crest of the party that founded the kingdom of the
author's table; it is the face of the installed app (the web app keeps the
👑 favicon). The outputs are committed, so a build never needs Pillow for
this; run the script only after changing the source image.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "party.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)
# The crest fills the square with a little margin all round: cropping it
# away makes the small sizes read better. Corners rounded like the other
# Windows icons, radius as a fraction of the side.
CROP, RADIUS = 0.04, 0.18


def framed(size: int) -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    side = min(source.size)
    cut = int(side * CROP)
    left = (source.width - side) // 2 + cut
    top = (source.height - side) // 2 + cut
    square = source.crop((left, top, left + side - 2 * cut, top + side - 2 * cut))
    # Shrink in two steps for the smallest sizes: one big jump smears the lines.
    while square.width > size * 4:
        square = square.resize((square.width // 2, square.height // 2), Image.LANCZOS)
    square = square.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * 4 - 1, size * 4 - 1],
                                           radius=int(size * 4 * RADIUS), fill=255)
    square.putalpha(mask.resize((size, size), Image.LANCZOS))
    return square


def main() -> None:
    images = [framed(s) for s in SIZES]
    images[-1].save(HERE / "kingmaker.png")
    images[-1].save(HERE / "kingmaker.ico", sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    print("written", HERE / "kingmaker.ico", "and kingmaker.png")


if __name__ == "__main__":
    main()
