"""Images uploaded from browsers: harmless names and verified content.

It used to live in `ui/hexmap.py`, when the only image was the map background.
Now players upload too (portrait and marker of their own character), and the
checks must be the same for everyone: the name comes from the client and is
not trustworthy, and the extension is chosen by the uploader while the first
bytes are not.
"""
from __future__ import annotations

import logging
import re
import secrets
import urllib.parse
from pathlib import Path

from kingmaker.media import imgsize
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)

EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# The map of the Stolen Lands is a large image; a portrait is not, and keeping
# the same ceiling would let anyone with an account fill the disk one portrait
# at a time.
MAX_MAP_BYTES = 40 * 1024 * 1024
MAX_PORTRAIT_BYTES = 8 * 1024 * 1024


class ImageRejected(Exception):
    """The file is not acceptable, with the reason to show the uploader."""


def safe_file_name(name: str) -> str | None:
    """Harmless file name derived from the one sent by the browser.

    A `../../map.jpg` would escape the folder, and an `.html` would end up
    served from the app's own domain. We keep only the base name, check the
    extension and clean the rest. None if it is not acceptable.
    """
    base = Path(name.replace(chr(92), "/")).name.strip()
    east = Path(base).suffix.lower()
    if east not in EXTENSIONS:
        return None
    root = re.sub(r"[^A-Za-z0-9._-]", "_", Path(base).stem).strip("._-")
    # A name made only of accents or dots empties out in the cleaning: better
    # a fallback name than an incomprehensible refusal.
    return (root[:80] or "image") + east


def unique_name(prefix: str, extension: str) -> str:
    """New name for a file that replaces another.

    The random part is not for security but for the browser cache: without it
    a replaced portrait would keep showing the old one.
    """
    root = re.sub(r"[^A-Za-z0-9_-]", "", prefix)[:40] or "image"
    return f"{root}-{secrets.token_hex(3)}{extension}"


async def accept(file, folder: Path, final_name: str,
                  max_byte: int = MAX_PORTRAIT_BYTES) -> Path:
    """Saves the uploaded file inside `folder`, if it really is an image.

    Raises `ImageRejected` with a readable reason when it is not. The file is
    written aside and moved into place only after the first bytes are checked,
    so an `.html` renamed `.jpg` never sits on disk under a name the app would
    then serve.
    """
    if file.size() > max_byte:
        raise ImageRejected(
            t("images.image_too_large_limit", v=max_byte // (1024 * 1024)))
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    destination = (folder / final_name).resolve()
    if destination.parent != root:
        raise ImageRejected(t("images.invalid_file_path"))

    provisional = destination.with_name(destination.name + ".parziale")
    await file.save(provisional)
    if imgsize.sizes(provisional) is None:
        provisional.unlink(missing_ok=True)
        raise ImageRejected(t("images.file_not_valid_png"))
    provisional.replace(destination)
    return destination


def delete(folder: Path, name: str | None) -> None:
    """Deletes a replaced image, without leaving its folder."""
    if not name:
        return
    root = folder.resolve()
    path = (folder / Path(name).name).resolve()
    if path.parent == root:
        path.unlink(missing_ok=True)
    # And its thumbnails, or copies of a portrait that no longer exists would
    # remain — and sooner or later one would be served instead of the new one.
    small_ones = folder / THUMBNAIL_FOLDER
    if small_ones.is_dir():
        for old_one in small_ones.glob(Path(name).stem + "-*"):
            old_one.unlink(missing_ok=True)


# --------------------------------------------------------------- thumbnails
#
# A marker is drawn inside a circle as big as half a hex. The file that ends
# up in it can be two megabytes, and that is what the browser downloads: here
# on the laptop it goes unnoticed, on another player's phone behind the On Air
# relay the map redraws several times while opening, and every redraw rebuilds
# the <image> element. The result is a dozen requests for the same big file
# all at once, and a marker that never shows up.
#
# The shrunken copy is made once and stays next to the original, which is not
# touched: whoever uploaded it still has it as it was.
THUMBNAIL_FOLDER = "thumbnails"
MARKER_SIDE = 192
PORTRAIT_SIDE = 640


def thumbnail(folder: Path, name: str | None, side: int) -> str | None:
    """The name — relative to `folder` — of a copy at most `side` high.

    Returns the original name if it is already small enough, or if it cannot
    be shrunk: better a heavy image than a hole. Without Pillow installed the
    function does nothing and only says so in the log.
    """
    if not name:
        return None
    source_text = folder / Path(name).name
    try:
        if not source_text.is_file():
            return name
        sizes = imgsize.sizes(source_text)
        if sizes and max(sizes) <= side:
            return name                     # already small: nothing to do
        # A JPEG stays a JPEG: redoing it as PNG makes it *grow*, and it did
        # happen — a 71 KB portrait became a 364 KB thumbnail. PNG is needed
        # only where transparency must be kept, i.e. for cut-out markers.
        as_jpeg = source_text.suffix.lower() in {".jpg", ".jpeg"}
        small_one = (folder / THUMBNAIL_FOLDER
                   / f"{source_text.stem}-{side}{'.jpg' if as_jpeg else '.png'}")
        if (small_one.is_file()
                and small_one.stat().st_mtime >= source_text.stat().st_mtime):
            return f"{THUMBNAIL_FOLDER}/{small_one.name}"
        from PIL import Image
        small_one.parent.mkdir(parents=True, exist_ok=True)
        provisional = small_one.with_name(small_one.name + ".parziale")
        with Image.open(source_text) as image:
            copy_ = image.convert("RGB" if as_jpeg else "RGBA")
            copy_.thumbnail((side, side))
            if as_jpeg:
                copy_.save(provisional, "JPEG", quality=85, optimize=True)
            else:
                copy_.save(provisional, "PNG", optimize=True)
        # And if in spite of everything it did not come out lighter, it is
        # useless: a thumbnail's reason to exist is to weigh less.
        if provisional.stat().st_size >= source_text.stat().st_size:
            provisional.unlink(missing_ok=True)
            return name
        provisional.replace(small_one)
        return f"{THUMBNAIL_FOLDER}/{small_one.name}"
    except Exception:
        # Missing Pillow, a broken PNG, a full disk: in every case the original
        # is there and that one is served.
        log.debug("thumbnail not created for %s", name, exc_info=True)
        return name


def address(base: str, folder: Path, name: str | None,
              side: int | None = None) -> str:
    """The address to put in the HTML for an uploaded image.

    `base` is the served prefix (for instance `/assets/characters`). With
    `side` one asks for the shrunken copy, which is what is needed almost
    always: the only two sizes we use are the marker and the portrait.
    """
    if not name:
        return ""
    if side is not None:
        name = thumbnail(folder, name, side) or name
    return base.rstrip("/") + "/" + urllib.parse.quote(name, safe="/")


def valid_color(color) -> str:
    """A colour chosen by a player, if it really is a colour.

    It ends up inside a `style` or SVG attribute: without this check anything
    could be written there and close the attribute.
    """
    text = str(color or "")
    return text if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", text) else "#d7b263"

