"""Reading the size of an image from its header bytes alone.

No external dependencies: supports PNG, JPEG, GIF and WebP, which cover every
format accepted for the map.
"""
from __future__ import annotations

import struct
from pathlib import Path


def sizes(path: str | Path) -> tuple[int, int] | None:
    """Returns (width, height) in pixels, or None if not recognised."""
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            head = fh.read(32)
            if len(head) < 12:
                return None

            # PNG
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)

            # GIF
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return int(w), int(h)

            # WebP
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                fh.seek(0)
                data = fh.read(64)
                kind = data[12:16]
                if kind == b"VP8X":
                    w = int.from_bytes(data[24:27], "little") + 1
                    h = int.from_bytes(data[27:30], "little") + 1
                    return w, h
                if kind == b"VP8 ":
                    w = int.from_bytes(data[26:28], "little") & 0x3FFF
                    h = int.from_bytes(data[28:30], "little") & 0x3FFF
                    return w, h
                if kind == b"VP8L":
                    b = data[21:26]
                    n = int.from_bytes(b[1:5], "little")
                    return (n & 0x3FFF) + 1, ((n >> 14) & 0x3FFF) + 1
                return None

            # JPEG: look for the SOF marker
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    nbytes = fh.read(1)
                    if not nbytes:
                        return None
                    if nbytes != b"\xff":
                        continue
                    while nbytes == b"\xff":
                        nbytes = fh.read(1)
                        if not nbytes:
                            return None
                    marker_ = nbytes[0]
                    if marker_ in (0xD8, 0xD9) or 0xD0 <= marker_ <= 0xD7:
                        continue
                    raw_length = fh.read(2)
                    if len(raw_length) < 2:
                        return None
                    length = struct.unpack(">H", raw_length)[0]
                    # SOF0..SOF15 except DHT (C4), JPG (C8) and DAC (CC)
                    if 0xC0 <= marker_ <= 0xCF and marker_ not in (0xC4, 0xC8, 0xCC):
                        body = fh.read(5)
                        if len(body) < 5:
                            return None
                        h, w = struct.unpack(">HH", body[1:5])
                        return int(w), int(h)
                    fh.seek(length - 2, 1)
    except OSError:
        return None
    return None
