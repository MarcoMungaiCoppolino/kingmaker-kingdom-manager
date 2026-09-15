# -*- coding: utf-8 -*-
"""The cases for the bench: every configuration up to three lines, with the
mask, the graph and a few courses by waypoints computed by Python. The browser
redoes them and must say the same (bench10.html)."""
import io
import itertools
import json
import os
import random

from kingmaker.geometry import atoms

O = "pointy"
lines = list(atoms.DIAGONALS) + [(a, None) for a in range(6)]
cases = []
rng = random.Random(7)
edge = atoms.edge_atoms(O)
for n in (1, 2, 3):
    for combo in itertools.combinations(lines, n):
        closed = atoms.closed_by_stretches(list(combo), O)
        g = atoms.graph(closed, frozenset(), O)
        entry = {"mask": atoms.mask(closed),
                 "neighbours": [sorted(g[i]) for i in range(atoms.HOW_MANY)],
                 "courses": []}
        # A couple of courses by waypoints per configuration, with a random
        # opening among the closed sides (if there are any), and a random
        # waypoint.
        openings = []
        if closed:
            openings = [[rng.choice(sorted(closed)), rng.choice([0.0, 1.0])]]
        provinces = atoms.provinces(closed, O)
        province_of = {x: k for k, g_ in enumerate(provinces) for x in g_}
        for ring in range(3):
            from_ = edge[rng.randrange(6)]
            to = edge[rng.randrange(6)]
            constrained = ring == 2 and len(provinces) > 1
            if constrained:
                # The whole row: the departure shore and then one or two others.
                row = [province_of[from_]]
                for _k in range(rng.choice([1, 2])):
                    row.append(rng.randrange(len(provinces)))
                waypoints = [sorted(provinces[k]) for k in row]
            else:
                waypoints = ([sorted(rng.choice(provinces))]
                             if len(provinces) > 1 and rng.random() < 0.7 else [])
            outcome = atoms.course_by_waypoints(closed, openings, from_, waypoints, to, 0.25, O,
                                                constrained=constrained)
            entry["courses"].append({"openings": openings, "from": from_, "to": to,
                                     "waypoints": waypoints, "constrained": constrained,
                                     "cost": None if outcome is None else outcome[0],
                                     "atoms": None if outcome is None else outcome[1]})
        cases.append(entry)
data = {"atoms": atoms.for_browser(O), "cases": cases}
here = os.path.dirname(os.path.abspath(__file__))
io.open(os.path.join(here, "atom_cases.json"), "w", encoding="utf-8").write(json.dumps(data))
print(len(cases), "configurations,", sum(len(c["courses"]) for c in cases), "courses")
