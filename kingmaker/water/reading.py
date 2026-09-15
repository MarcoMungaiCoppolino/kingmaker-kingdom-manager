"""Reading the water off the map image, to propose it to the GM.

The module decides nothing: it looks at the image already uploaded, says which
sides look crossed by water to it and leaves the floor to the table. It is the
same rule as the rest of the app — effects are proposed and confirmed — and
here it counts double, because here the one that can be wrong is a machine
looking at a drawing.

## Why segmenting the image is not needed

The planner asks a single question for every pair of neighbouring hexes: «can
one pass from here to there?». On a 30x24 grid that is a couple of thousand
questions, and each one boils down to: *does the segment between the two
centers cross water?* Some eighty samples per segment are enough.

That question has the merit of not distinguishing cases: a river drawn along
the edge between two hexes and one meandering inside a hex give the right
answer with the same line of code. No need to rebuild the water mask, nor to
skeletonise it, nor to separate rivers from lakes.

## Why not a pre-trained model

Ready-made *water segmentation* models are trained on multispectral satellite
imagery, and the signal they rest on is near-infrared absorption. A hand-drawn
map has no such band, and in RGB its statistics are the reverse of real water:
satellite water is dark and unsaturated, fantasy-map water is flat and
saturated. Such a model works here outside the distribution it was trained on,
and that is precisely the dimension it depends on.

Here the colour is learnt from this map and from no other: the GM clicks a few
points on the drawn water and those become the reference. No hand-written
threshold, no colour decided at a desk.

Why they click and the app does not guess: a hex marked «Lake» says there is a
lake in that hex, not that the *center* of the hex falls on blue — on the
Stolen Lands map those centers are as brown as the plains. Trying to infer the
colour from them gave a reference indistinguishable from land, and with it a
senseless but confident-looking reading. Better one more question.

If the references do not separate water and land the module **refuses** and
says so: separability is measured by comparing the distance between the two
centroids with how spread the samples are around their own. No hand-picked
threshold here either.
"""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field

from kingmaker.geometry import hexgrid
from kingmaker.locale.i18n import t

# How much the image is shrunk before looking at it. Pillow can decode a JPEG
# at 1/2, 1/4 or 1/8 straight from the coefficients, so shrinking costs less
# than reading.
#
# Half and not a quarter. At a quarter the 8192x2894 of the Stolen Lands
# become 2048x724, and there the streams are lines one or two pixels wide: at
# the limit of what can be told from a compression artefact, and indeed a third
# of them were lost. At half they are four pixels, all visible, and the reading
# goes from two seconds to seven — which for something done once per map is a
# price nobody feels.
REDUCTION = 2

# Samples along the segment between two centers. Eighty over some forty pixels
# means looking at the same pixel several times: on purpose, because the
# threshold is measured as a fraction of the segment and not in pixels, so it
# does not change with the zoom.
SAMPLES = 80

# Samples along a hex side: it is half the segment between two centers, and
# the same resolution is not needed because here one looks not for a narrow
# strip but for a portion of the side.
SAMPLES_PER_SIDE = 24

# The part of the segment near the centers that is skipped. A center inside the
# water is another question — that is a water cell, not a border — and
# including it would make all six sides of a lake hex look «bordering».
MARGIN = 0.18

# How much of a side must be wet for water to really run *on* it. It is the
# right question for a border, and not the one asked for banks: a river cutting
# a hex runs through the middle and leaves the sides dry, a river marking a
# border runs along it. Two different questions, two different mechanisms,
# neither covering the other's work.
SIDE_SHARE = 0.25

# How wide, in pixels of the shrunken image, the longest strip of water met
# along the segment must be. In pixels and not as a fraction of the segment: a
# river is as wide as the brush stroke it was drawn with, and that width does
# not change whether the hexes are big or small.
#
# One pixel and a half, not two: the streams of this map are thin lines and at
# two quite a few were skipped. A few extra false positives cost little,
# because the proposal is looked at in orange before accepting — a missed river
# instead goes unseen, and those are the ones that let a party through where
# it should not.
MIN_WIDTH = 1.5

# Where the colour of land is taken from: the hexes the GM has already marked
# with a dry terrain. If there are none, the whole image is looked at coarsely
# — a map is almost all land, and the centroid holds.
LAND_TERRAINS = ("plains", "hills", "forest", "swamp", "mountains", "ruins")


@dataclass
class Proposal:
    """What the reading saw. Nobody has applied it yet."""

    available: bool = True
    reason: str = ""                      # why it could not be read
    borders: list = field(default_factory=list)   # (a, b, kind, confidence)
    banks: dict = field(default_factory=dict)      # coord -> [[dir, ...], ...]
    outside_image: int = 0               # sides skipped because outside the drawing
    examined: int = 0
    water_references: int = 0
    land_references: int = 0
    scale: float = 1.0

    @property
    def cut_ones(self) -> int:
        """How many hexes the river really crosses, cutting them into several banks."""
        return sum(1 for g in self.banks.values() if len(g) > 1)

    @property
    def empty_one(self) -> bool:
        return not self.borders and not self.cut_ones


# ------------------------------------------------------------------- colour
def _hsv(rgb) -> tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in rgb[:3])
    return colorsys.rgb_to_hsv(r, g, b)


def _dist(a, b) -> float:
    """How different two colours are, in HSV and with the hue wrapping around.

    Hue is an angle: between 0.99 and 0.01 there is a hundredth of a turn, not
    ninety-eight. Brightness weighs less than the other two, because on a
    drawing shading changes it a lot without changing what the thing is.
    """
    dt = abs(a[0] - b[0])
    dt = min(dt, 1.0 - dt)
    return math.sqrt((dt * 2.2) ** 2 + (a[1] - b[1]) ** 2 + ((a[2] - b[2]) * 0.6) ** 2)


class Classifier:
    """Water or land, learnt from the colours of this map and no other.

    It is a nearest centroid, i.e. the simplest thing that works: every decision
    can be re-read as «this point looks more like the water the GM pointed at,
    or more like the land». Nothing to train and nothing to explain that does
    not fit in that sentence.

    `is_separate` says whether the two references are really two different
    things: if the two colour clouds overlap, this object cannot answer and its
    user must stop instead of producing random numbers.
    """

    def __init__(self, groups: list, land: list) -> None:
        # One centroid per clicked point, not a single one for all. On a map
        # water has no single colour: the lake is dark blue and the river a
        # light blue line, and averaging them would give a colour that is
        # nowhere. By clicking two, the GM is describing two things.
        self.waters = [_centroid(g) for g in groups if g]
        everyone = [c for g in groups for c in g]
        self.land = _centroid(land) if land else None
        self.water_scatter = max(
            (_scatter(g, _centroid(g)) for g in groups if g), default=0.0)
        self.land_scatter = _scatter(land, self.land) if land else 0.0
        self.dist = (min(_dist(a, self.land) for a in self.waters)
                         if self.land and self.waters else 0.0)
        self.radius = self.dist * 0.5 if self.land else 0.25
        self.samples = len(everyone)

    def _near(self, c) -> float:
        return min(_dist(c, a) for a in self.waters)

    @property
    def is_separate(self) -> bool:
        """Do the references describe different colours, or the same one?

        The distance between the water reference *closest to land* and the land
        is compared with how wide the two clouds are: if they sit closer than
        that, any threshold would split the noise, not water from land.
        """
        if self.land is None or not self.waters:
            return bool(self.waters)
        return self.dist > (self.water_scatter + self.land_scatter)

    def watery(self, rgb) -> bool:
        c = _hsv(rgb)
        from_water = self._near(c)
        if self.land is None:
            return from_water < self.radius
        return from_water < _dist(c, self.land) and from_water < self.radius * 1.6


def _scatter(colors: list, center) -> float:
    """How spread the samples are around their own centroid."""
    if not colors:
        return 0.0
    return sum(_dist(c, center) for c in colors) / len(colors)


def _centroid(colors: list) -> tuple[float, float, float]:
    """Hue is averaged as an angle, saturation and value as numbers."""
    sx = sum(math.cos(c[0] * 2 * math.pi) for c in colors)
    sy = sum(math.sin(c[0] * 2 * math.pi) for c in colors)
    tint = (math.atan2(sy, sx) / (2 * math.pi)) % 1.0
    return (tint,
            sum(c[1] for c in colors) / len(colors),
            sum(c[2] for c in colors) / len(colors))


# ------------------------------------------------------------------ reading
def _disc(pixel, width, height, cx, cy, radius, step=3):
    """The colours around a point, skipping those outside the image."""
    outside = []
    r = int(radius)
    for dy in range(-r, r + 1, step):
        for dx in range(-r, r + 1, step):
            if dx * dx + dy * dy > r * r:
                continue
            x, y = int(cx + dx), int(cy + dy)
            if 0 <= x < width and 0 <= y < height:
                outside.append(pixel[x, y])
    return outside


def _wet_chord(pixel, L, A, judge, p, q) -> bool:
    """Does the chord between two points cross water?

    Used for the banks: if from the midpoint of one side you cannot reach that
    of another without getting wet, those two sides are on different banks.

    Sampled **one point per pixel**. Sampling more sparsely looks like a saving
    and is not: a stream two pixels wide, looked at every two, is seen every
    other time, and half a time passes no threshold. This way instead the
    threshold in pixels is exactly a number of samples, and means what it says.
    """
    length = math.hypot(q[0] - p[0], q[1] - p[1])
    if length < 1e-6:
        return False
    samples = max(int(length), 8)
    min_ = max(MIN_WIDTH, 2.0)
    run_ = maximum = 0
    for i in range(samples + 1):
        t = i / samples
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        if not (0 <= x < L and 0 <= y < A):
            return False            # outside the drawing: unknown, not cut
        if judge.watery(pixel[int(x), int(y)]):
            run_ += 1
            maximum = max(maximum, run_)
        else:
            run_ = 0
    return maximum >= min_


def _banks_of(pixel, L, A, judge, coord, directions, vehicle) -> list:
    """The banks of a hex: its sides grouped by bank.

    The river crossing a hex cuts it in two (or three, at a confluence). Which
    sides go together is found by asking, for every pair, whether one can go
    from one to the other staying dry — and grouping those that answer yes. No
    need to know where the river runs: knowing who separates whom is enough.

    Returns a list of lists of direction indices, always sorted, so two
    readings of the same map give the same result.
    """
    parent_ = {d: d for d in directions}

    def root(x):
        while parent_[x] != x:
            parent_[x] = parent_[parent_[x]]
            x = parent_[x]
        return x

    for i, a in enumerate(directions):
        for b in directions[i + 1:]:
            if not _wet_chord(pixel, L, A, judge, vehicle[a], vehicle[b]):
                parent_[root(a)] = root(b)

    groups: dict = {}
    for d in directions:
        groups.setdefault(root(d), []).append(d)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def trace(image_path, mapping: dict, hexes: dict, inside=None,
            water_points=None) -> Proposal:
    """Look at the map and propose where the water runs.

    `hexes` is {(col, row): hex}, and serves for the colour of land and to
    avoid re-proposing what is already there. `water_points` are the points
    the GM clicked on the water, in pixels of the full-size image: they are the
    reference, and without them nothing is read. `inside(coord)` says which
    coordinates make sense; without it, the whole grid counts.
    """
    try:
        from PIL import Image
    except ImportError:
        return Proposal(available=False, reason=(
            t("water_reading.pillow_library_needed_open")))

    try:
        img = Image.open(image_path)
        img.draft("RGB", (img.width // REDUCTION, img.height // REDUCTION))
        img = img.convert("RGB")
    except Exception as error:              # noqa: BLE001 - any format
        return Proposal(available=False,
                        reason=t("water_reading.cannot_open_image", error=error))

    size = float(mapping["size"])
    origin = (float(mapping["origin_x"]), float(mapping["origin_y"]))
    orient = mapping["orientation"]
    columns, rows = int(mapping["columns"]), int(mapping["rows"])
    real_width = float(mapping.get("img_width") or img.width * REDUCTION)
    scale = img.width / real_width
    pixel = img.load()
    L, A = img.width, img.height

    def point(coord):
        x, y = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
        return x * scale, y * scale

    def in_the_image(x, y) -> bool:
        return 0 <= x < L and 0 <= y < A

    # --- the colour of water: the GM points at it --------------------------
    radius = size * scale * 0.35
    water_groups, water_samples = [], []
    for px_x, px_y in (water_points or ()):
        x, y = float(px_x) * scale, float(px_y) * scale
        if not in_the_image(x, y):
            continue
        group = [_hsv(c) for c in
                  _disc(pixel, L, A, x, y, max(radius * 0.12, 3), step=1)]
        if group:
            water_groups.append(group)
            water_samples += group
    if not water_samples:
        return Proposal(available=False, reason=(
            t("water_reading.i_do_not_know")))

    # --- the colour of land: the hexes already marked, or everything else --
    land_samples = []
    for coord, hexagon in hexes.items():
        if not (set((hexagon or {}).get("terrains") or ()) & set(LAND_TERRAINS)):
            continue
        x, y = point(coord)
        if in_the_image(x, y):
            land_samples += [_hsv(c) for c in
                               _disc(pixel, L, A, x, y, radius * 0.5)]
    if not land_samples:
        # No terrain marked: the whole image is looked at coarsely. A map is
        # almost all land, and a few water pixels in the heap do not move the
        # centroid.
        step = max(L // 120, 1)
        land_samples = [_hsv(pixel[x, y])
                          for y in range(0, A, step) for x in range(0, L, step)]

    judge = Classifier(water_groups, land_samples)
    outside = Proposal(scale=scale,
                     water_references=len(water_samples),
                     land_references=len(land_samples))

    if not judge.is_separate:
        return Proposal(available=False, reason=(
            t("water_reading.points_you_pointed_have")))

    # --- the sides ---------------------------------------------------------
    seen = set()
    for row in range(rows):
        for col in range(columns):
            if inside is not None and not inside((col, row)):
                continue
            ax, ay = point((col, row))
            for near in hexgrid.neighbours(col, row, orient):
                if not (0 <= near[0] < columns and 0 <= near[1] < rows):
                    continue
                if inside is not None and not inside(near):
                    continue
                key = hexgrid.border_key((col, row), near)
                if key in seen:
                    continue
                seen.add(key)
                bx, by = point(near)
                # The map can be shorter than the grid: the rows falling
                # outside the drawing are not land, they are unread. Saying so
                # is the only honest answer.
                if not (in_the_image(ax, ay) and in_the_image(bx, by)):
                    outside.outside_image += 1
                    continue
                outside.examined += 1
                # The *side* is sampled, not the line between the centers. The
                # line between the centers answers another question — «is there
                # water between me and him?» — and on a real map that question
                # is almost always answered yes, because almost every river
                # crosses something. The result was walling off whole dry hexes.
                # Here we ask whether the water runs *along the border*, which
                # is the only thing a border can say.
                side = hexgrid.shared_side((col, row), near, size, origin,
                                              orient)
                if side is None:
                    continue
                (lx1, ly1), (lx2, ly2) = [(q[0] * scale, q[1] * scale)
                                          for q in side]
                wet = valid = 0
                for i in range(SAMPLES_PER_SIDE + 1):
                    frac = MARGIN + (1 - 2 * MARGIN) * i / SAMPLES_PER_SIDE
                    x, y = lx1 + (lx2 - lx1) * frac, ly1 + (ly2 - ly1) * frac
                    if not in_the_image(x, y):
                        continue
                    valid += 1
                    if judge.watery(pixel[int(x), int(y)]):
                        wet += 1
                if not valid:
                    continue
                share = wet / valid
                if share >= SIDE_SHARE:
                    outside.borders.append(
                        ((key[0], key[1]), (key[2], key[3]),
                         "water", round(min(share / SIDE_SHARE, 3.0), 2)))

    # --- the banks: which side of the river you are on inside the hex -------
    # A hex crossed by a river is not closed, it is *cut*: one enters it from
    # every side, but from one bank one cannot reach the other. Here only who
    # separates whom is found; the pathfinder will make two nodes of it.
    for row in range(rows):
        for col in range(columns):
            coord = (col, row)
            if inside is not None and not inside(coord):
                continue
            cx, cy = point(coord)
            if not in_the_image(cx, cy):
                continue
            directions, vehicle = [], {}
            for index, near in enumerate(
                    hexgrid.neighbours(col, row, orient)):
                if not (0 <= near[0] < columns and 0 <= near[1] < rows):
                    continue
                if inside is not None and not inside(near):
                    continue
                vx, vy = point(near)
                if not in_the_image(vx, vy):
                    continue
                directions.append(index)
                vehicle[index] = ((cx + vx) / 2, (cy + vy) / 2)
            if len(directions) < 2:
                continue
            groups = _banks_of(pixel, L, A, judge, coord, directions, vehicle)
            # A hex with a single bank is dry: there is nothing to say, and not
            # writing it keeps the table as small as the map is dry.
            if len(groups) > 1:
                outside.banks[coord] = groups

    return outside
