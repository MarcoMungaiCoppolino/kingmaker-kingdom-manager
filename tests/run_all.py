# -*- coding: utf-8 -*-
"""Every test, one per process, on a scene built from scratch.

    python tests/run_all.py                          # the whole suite
    python tests/run_all.py test_lake.py test_route.py

The scene is built in `tests/scene/` (not versioned) at the start, and before
every file `stage.py` brings it back to the starting state. The live save in
`saves/` is never opened.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
DATA = os.path.join(HERE, "scene")
# The suite has its own images too: the scene's map is a placeholder written
# by scene.py, never the table's real one, so a test that looks for the file
# passes on any machine and not only where the live assets are.
ENVIRONMENT = dict(os.environ, PYTHONPATH=BASE, PYTHONIOENCODING="utf-8",
                KINGMAKER_DATA_DIR=DATA, KINGMAKER_ASSETS_DIR=os.path.join(DATA, "assets"))
SUITE = ["test_atoms.py", "test_ring.py", "test_faces.py", "test_redraw.py",
         "test_bank_model.py", "test_borders.py", "test_modes.py",
         "test_real_map.py", "test_map_banks.py", "test_cut.py",
         "test_eraser.py", "test_marker_clicks.py", "test_water_off.py",
         "test_traces.py", "test_crossings.py", "test_prefix.py",
         "test_chart.py", "test_waterways.py", "test_current.py",
         "test_route.py", "test_lake.py", "test_center.py",
         "test_stretches.py", "test_boarding.py",
         "test_onair.py", "test_map_view.py",
         "test_veil.py", "test_arrow.py",
         "test_together.py", "test_shores.py", "test_swimming.py", "test_badges.py",
         "test_arrival.py", "test_atom_count.py", "test_rendezvous.py", "test_edges.py",
         "test_water_atoms.py", "test_pointed_shore.py", "test_cleanup.py", "test_security.py",
         "test_structures.py", "test_migration_v27.py", "test_i18n.py",
         "test_backup.py", "test_launcher.py", "test_sync.py", "test_refresh.py",
         "test_windows.py", "test_layers.py", "test_screens.py", "test_farmland.py", "test_shared_rolls.py",
         "test_fame.py", "test_feats.py", "test_rules.py", "test_save_formats.py"]


# A file that takes longer than this is stuck, not slow: the slowest, the
# windows test, takes about ninety seconds. Once in a while it used to wait
# forever and hold the whole batch; now it fails, and the batch goes on.
TIMEOUT = 300


def run_file(script: str) -> subprocess.CompletedProcess:
    command = [sys.executable, os.path.join(HERE, script)]
    try:
        return subprocess.run(command, cwd=BASE, env=ENVIRONMENT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired as stuck:
        out = stuck.stdout or ""
        if isinstance(out, bytes):           # what the timeout hands back may be bytes
            out = out.decode("utf-8", "replace")
        return subprocess.CompletedProcess(command, 1, out, f"stuck: no end after {TIMEOUT} s")


def main(names) -> int:
    scene = run_file("scene.py")
    if scene.returncode != 0:
        print(scene.stdout, scene.stderr)
        return 2
    print(scene.stdout.strip())
    passed = totals = 0
    routes = []
    for name in names:
        run_file("stage.py")
        outcome = run_file(name)
        tally_ = re.findall(r"(\d+)/(\d+) (?:passate|passed)", outcome.stdout or "")
        if outcome.returncode != 0 or not tally_:
            routes.append((name, (outcome.stderr or outcome.stdout or "")[-900:]))
            print(f"  ROTTA  {name}")
            continue
        a, b = int(tally_[-1][0]), int(tally_[-1][1])
        passed += a
        totals += b
        print(f"  {'ok ' if a == b else 'NO '} {name:26} {a}/{b}")
        for row in (outcome.stdout or "").splitlines():
            if row.startswith(" NO"):
                print("        " + row.strip())
    print(f"\n{passed}/{totals} passed in {len(names)} files")
    for name, queue in routes:
        print(f"\n----- {name}\n{queue}")
    return 0 if passed == totals and not routes else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or SUITE))
