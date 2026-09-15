"""The water chart: the rivers drawn on a map, in a single file.

Tracing the Shrike hex by hex is half an hour of work, and until now that work
lived in a single database on a single computer. Here it becomes a file: it can
be downloaded, kept aside, sent to another table playing on the same map, and
they find it drawn.

Inside are the things that make up the water, and they must travel together
because apart they mean nothing:

* the **borders** between two hexes (water, ford, bridge);
* the **banks**, i.e. how a river crossing a hex cuts it into two shores;
* the **inner crossings**, the bridge or ford on that cut;
* the **current directions**, i.e. which way each of those stretches flows.

And the **calibration of the grid** they were drawn on is in there too. It is
no extra: a border is a pair of coordinates, and coordinates mean something
only relative to a grid. Whoever opens the file on a differently calibrated map
must know it *before* finding the rivers shifted by one hex, and the only way
for them to know is for the file to say so.

JSON and not a format of our own: it opens in an editor, reads, can be
corrected by hand if needed, and still reads in ten years. It is the same
choice as the kingdom export.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from kingmaker.geometry import waterways, sections
from kingmaker.locale.i18n import t

FORMAT = "kingmaker.acque"
# Version 2 adds the current directions. Version 1 charts still read — a river
# without a direction is a river whose flow is unknown, which is exactly the
# case travel already handles.
VERSION = 2

BORDER_KINDS = {"water", "ford", "bridge"}
INNER_KINDS = {"bridge", "ford"}
DIFFICULTY = {"open", "difficult", "greater_difficult"}

# The calibration keys that end up in the file. `size` and `origin` say
# *where* on the image the grid falls; `columns`, `rows` and `orientation` say
# what a pair of coordinates means. Two different questions, and on opening
# they matter differently.
MAP_KEYS = ("image", "orientation", "columns", "rows",
                "size", "origin_x", "origin_y")


def compose(mapping: dict, borders: dict, banks: dict, crossings: dict,
            kingdom: str = "", currents: dict | None = None) -> dict:
    """The document to save, from what is in the database.

    `borders`, `banks` and `crossings` come exactly as the archive gives them.
    """
    outside_borders = []
    for (col_a, row_a, col_b, row_b), entry in sorted(borders.items()):
        outside_borders.append({"a": [col_a, row_a], "b": [col_b, row_b],
                              "kind": entry.get("kind") or "water"})
    outside_banks = [{"hexagon": [c[0], c[1]], "groups": [sorted(g) for g in groups]}
                  for c, groups in sorted(banks.items())]
    outside_crossings = []
    for coord, entries in sorted(crossings.items()):
        for entry in entries:
            ends = entry.get("ends")
            if ends is None:
                continue
            above = entry.get("at")
            outside_crossings.append({
                "hexagon": [coord[0], coord[1]],
                "ends": [[round(float(p[0]), 6), round(float(p[1]), 6)]
                         for p in ends],
                "at": (None if above is None
                          else [round(float(above[0]), 6),
                                round(float(above[1]), 6)]),
                "kind": entry.get("kind") or "bridge",
                "difficulty": entry.get("difficulty") or None,
            })
    outside_currents = [
        {"upstream": waterways.node_text(upstream), "downstream": waterways.node_text(downstream)}
        for _stretch, (upstream, downstream) in sorted((currents or {}).items())]
    return {
        "format": FORMAT,
        "version": VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kingdom": kingdom,
        "map": {k: mapping.get(k) for k in MAP_KEYS},
        "borders": outside_borders,
        "banks": outside_banks,
        "crossings": outside_crossings,
        "currents": outside_currents,
    }


def file_name(kingdom: str = "") -> str:
    """The name of the downloaded file: telling, and with no surprises.

    The kingdom's name goes into it because a backup folder with three
    `water.json` files inside is useless. It goes through a cleaning of its
    own: the image one will not do, there the allowed extensions are only the
    image ones.
    """
    root = re.sub(r"[^A-Za-z0-9]+", "-", (kingdom or "kingdom")).strip("-").lower()
    return f"acque-{root[:40] or 'kingdom'}-{time.strftime('%Y%m%d')}.json"


def text(document: dict) -> str:
    """The file as written: indented, UTF-8, readable by a human."""
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


@dataclass
class Chart:
    """A water chart read from a file. Nobody has applied it yet.

    Exposes `borders`, `banks` and `cells` with the same shape as the proposal
    of the automatic reading, so the map draws it in orange without knowing
    where it comes from: a proposal is a proposal, and one looks before
    accepting.
    """

    is_valid: bool = True
    reason: str = ""
    origin_: str = "chart"
    file_name: str = ""
    kingdom: str = ""
    created_at: str = ""
    mapping: dict = field(default_factory=dict)
    borders: list = field(default_factory=list)   # (a, b, kind, confidence)
    banks: dict = field(default_factory=dict)      # coord -> [[dir, ...], ...]
    crossings: list = field(default_factory=list)     # (coord, shores, at, kind, difficulty)
    currents: list = field(default_factory=list)  # (upstream node, downstream node)
    cells: list = field(default_factory=list)     # always empty: no terrains here
    warnings: list = field(default_factory=list)
    discarded: int = 0                             # bent entries or out of the grid

    # --- what the proposal drawing needs, as for the reading ---
    @property
    def available(self) -> bool:
        return self.is_valid

    @property
    def cut_ones(self) -> int:
        return sum(1 for g in self.banks.values() if len(g) > 1)

    @property
    def empty_one(self) -> bool:
        # Directions do not count: a chart of directions alone describes no
        # watercourse, and without the stretches they refer to it would say
        # nothing anyway.
        return not self.borders and not self.banks and not self.crossings


def _ends(value):
    """The two points of a crossing, or None if they are not two good points."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    points = [_point(p) for p in value]
    return None if any(p is None for p in points) else tuple(points)


def _point(value) -> tuple[float, float] | None:
    """A point inside the hex, in hex radii from the center.

    Outside the circle containing the hex it is not a point of that hex: a
    chart carrying one is describing another map, or is bent.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if (x * x + y * y) <= 1.0001 else None


def _pair(value) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _valid_groups(groups) -> list | None:
    """The banks must be a real partition of the six sides, or they divide nothing."""
    if not isinstance(groups, list) or len(groups) < 2:
        return None
    cleaned, seen = [], set()
    for group in groups:
        if not isinstance(group, list) or not group:
            return None
        sides = []
        for d in group:
            if not isinstance(d, int) or not 0 <= d <= 5 or d in seen:
                return None
            seen.add(d)
            sides.append(d)
        cleaned.append(sorted(sides))
    return cleaned if seen == set(range(6)) else None


def read(content_, mapping: dict, file_name: str = "") -> Chart:
    """Reads a chart and compares it with the grid of *this* map.

    What is bent is discarded and counted; what does not fit today's grid is
    discarded and reported. Everything is refused only when the file is not a
    water chart, or when the grid orientation differs: there the coordinates
    would mean something else, and applying them would draw rivers at random.
    """
    if isinstance(content_, (bytes, bytearray)):
        try:
            content_ = content_.decode("utf-8")
        except UnicodeDecodeError:
            return Chart(is_valid=False, file_name=file_name,
                         reason=t("water_chart.not_text_file_water"))
    try:
        document = json.loads(content_)
    except (json.JSONDecodeError, TypeError):
        return Chart(is_valid=False, file_name=file_name,
                     reason=t("water_chart.file_not_readable_json"))
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        return Chart(is_valid=False, file_name=file_name,
                     reason=t("water_chart.this_not_kingmaker_water"))
    try:
        version = int(document.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version > VERSION:
        return Chart(is_valid=False, file_name=file_name,
                     reason=t("water_chart.chart_version_this_app", version=version, VERSION=VERSION))

    its = document.get("map") if isinstance(document.get("map"), dict) else {}
    chart = Chart(file_name=file_name, mapping=its,
                  kingdom=str(document.get("kingdom") or ""),
                  created_at=str(document.get("created_at") or ""))

    if its.get("orientation") and its["orientation"] != mapping.get("orientation"):
        return Chart(is_valid=False, file_name=file_name, mapping=its,
                     reason=t("water_chart.chart_drawn_grid_orientation", orientation=its["orientation"], get=mapping.get("orientation")))

    columns, rows = int(mapping.get("columns") or 0), int(mapping.get("rows") or 0)

    def inside(coord) -> bool:
        return 0 <= coord[0] < columns and 0 <= coord[1] < rows

    for key, how in (("columns", "columns"), ("rows", "rows")):
        if its.get(key) and int(its[key]) != int(mapping.get(key) or 0):
            chart.warnings.append(
                t("water_chart.chart_grid_this_one", its=its[key], how=how, get=mapping.get(key)))
    if its.get("image") and its["image"] != mapping.get("image"):
        chart.warnings.append(
            t("water_chart.drawn_another_image_coordinates", image=its["image"]))
    elif any(its.get(k) is not None and its.get(k) != mapping.get(k)
             for k in ("size", "origin_x", "origin_y")):
        chart.warnings.append(
            t("water_chart.same_image_but_grid"))

    for entry in document.get("borders") or []:
        a = _pair(entry.get("a")) if isinstance(entry, dict) else None
        b = _pair(entry.get("b")) if isinstance(entry, dict) else None
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if a is None or b is None or kind not in BORDER_KINDS:
            chart.discarded += 1
            continue
        if not (inside(a) and inside(b)):
            chart.discarded += 1
            continue
        chart.borders.append((a, b, kind, 1.0))

    for entry in document.get("banks") or []:
        coord = _pair(entry.get("hexagon")) if isinstance(entry, dict) else None
        groups = _valid_groups(entry.get("groups")) if isinstance(entry, dict) else None
        if coord is None or groups is None or not inside(coord):
            chart.discarded += 1
            continue
        chart.banks[coord] = groups

    for entry in document.get("crossings") or []:
        coord = _pair(entry.get("hexagon")) if isinstance(entry, dict) else None
        kind = entry.get("kind") if isinstance(entry, dict) else None
        difficulty = entry.get("difficulty") if isinstance(entry, dict) else None
        if (coord is None or not inside(coord) or kind not in INNER_KINDS
                or (difficulty is not None and difficulty not in DIFFICULTY)):
            chart.discarded += 1
            continue
        # A crossing without the cut it hops over crosses nothing.
        if coord not in chart.banks:
            chart.discarded += 1
            continue
        # New charts carry the **two points** of the joined shores; older ones
        # carried the pair of sides, and are translated here — from the sides
        # to the two sections they divided, and from those to their points.
        ends = _ends(entry.get("ends"))
        above = _point(entry.get("at"))
        if ends is None:
            sides = _pair(entry.get("sides"))
            if (sides is None or not all(0 <= d <= 5 for d in sides)
                    or sides[0] == sides[1]):
                chart.discarded += 1
                continue
            faces = sections.faces_of(
                sections.cuts_from_groups(chart.banks[coord]),
                mapping.get("orientation") or "pointy")
            found = sections.hop_between_sides(faces, sides[0], sides[1])
            if found is None:
                chart.discarded += 1
                continue
            ends, above = found[0], found[1]
        chart.crossings.append((coord, ends, above, kind, difficulty))

    # Directions are accepted only on stretches the chart itself carries: a
    # direction on a piece of river that is not there says nothing, and keeping
    # it would mean filling the database with rows that describe nothing.
    network = waterways.build(
        {(a[0], a[1], b[0], b[1]): {"kind": kind}
         for a, b, kind, _f in chart.borders},
        chart.banks, mapping.get("orientation") or "pointy")
    for entry in document.get("currents") or []:
        upstream = (waterways.node_from_text(entry.get("upstream"))
                 if isinstance(entry, dict) else None)
        downstream = (waterways.node_from_text(entry.get("downstream"))
                 if isinstance(entry, dict) else None)
        if upstream is None or downstream is None or upstream == downstream:
            chart.discarded += 1
            continue
        if not network.has_stretch(upstream, downstream):
            chart.discarded += 1
            continue
        chart.currents.append((upstream, downstream))

    if chart.empty_one and not chart.discarded:
        chart.warnings.append(t("water_chart.chart_contains_no_watercourse"))
    return chart
