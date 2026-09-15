# -*- coding: utf-8 -*-
"""The app on the test scene, on port 8081: `python tests/launch_scene.py`.

Builds the scene if it is not there (like `run_all.py`) and starts
`launch_test.py` with `KINGMAKER_DATA_DIR=tests/scene`. Never the live save.
"""
import os
import runpy
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
DATA = os.path.join(HERE, "scene")
os.environ["KINGMAKER_DATA_DIR"] = DATA
os.environ.setdefault("KINGMAKER_PORT", "8081")
if not os.path.exists(os.path.join(DATA, "kingmaker.db")):
    environment = dict(os.environ, PYTHONPATH=BASE, PYTHONIOENCODING="utf-8")
    subprocess.run([sys.executable, os.path.join(HERE, "scene.py")], cwd=BASE, env=environment, check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "stage.py")], cwd=BASE, env=environment, check=True)
sys.path.insert(0, BASE)
runpy.run_path(os.path.join(BASE, "launch_test.py"), run_name="__main__")
