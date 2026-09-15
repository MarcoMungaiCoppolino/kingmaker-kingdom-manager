"""The badges: the marker of a character or a vehicle, as a page element
(not the map SVG, which has its own in `hexmap`).

A single drawing for every box — sheet, party, transport, the group opened
on the map — so a character has the same face everywhere.

Image addresses go through `ui.image`, which under On Air adds the prefix on
its own in the browser: here nothing is touched (`theme.with_prefix` is only
for markup written by us).
"""
from __future__ import annotations

from nicegui import ui

from kingmaker.media import images
from kingmaker import travel as travel_mod
from kingmaker.config import ASSETS_DIR

CHARACTER_FOLDER = ASSETS_DIR / "characters"
VEHICLE_FOLDER = ASSETS_DIR / "vehicles"


def _badge(side: int, edge: str, inside: str, measure: float) -> None:
    ui.html(f'<div style="width:{side}px;height:{side}px;border-radius:50%;'
            f'background:#241d15;border:2px solid {edge};display:flex;'
            f'align-items:center;justify-content:center;flex:0 0 auto;'
            f'font-family:Cinzel,serif;color:{edge};'
            f'font-size:{side * measure:.0f}px">{inside}</div>')


def person_badge(char: dict, side: int) -> None:
    """The character's marker: the image if there is one, otherwise the initials."""
    color = images.valid_color((char or {}).get("color"))
    if char.get("token"):
        measure = images.MARKER_SIDE if side <= 48 else images.PORTRAIT_SIDE
        ui.image(images.address("/assets/characters", CHARACTER_FOLDER,
                                    str(char["token"]), measure)).style(
            f'width:{side}px;height:{side}px;border-radius:50%;object-fit:cover;'
            f'border:2px solid {color};flex:0 0 auto')
        return
    initials = "".join(p[0] for p in (char.get("name") or "?").split()[:2]).upper()
    _badge(side, color, _esc(initials), 0.38)


def vehicle_badge(entry: dict, side: int) -> None:
    """The vehicle's badge: the uploaded marker, or the symbol of its trade."""
    if entry.get("token"):
        ui.image(images.address("/assets/vehicles", VEHICLE_FOLDER,
                                    str(entry["token"]), images.PORTRAIT_SIDE)).style(
            f'width:{side}px;height:{side}px;border-radius:50%;object-fit:cover;'
            f'border:2px solid var(--km-gold-dim);flex:0 0 auto')
        return
    _badge(side, "var(--km-gold-dim)", travel_mod.vehicle_symbol(entry), 0.5)


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
