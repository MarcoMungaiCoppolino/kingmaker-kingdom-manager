"""Starts a copy of the app for testing, on port 8081 and on separate data.

Never on the live save: that one is on 8080 and the table plays on it. Here
the data comes from KINGMAKER_DATA_DIR, normally a copy of the database, and
the real database is not even opened.

    KINGMAKER_DATA_DIR=<copy> python launch_test.py

The images stay the real ones: they are only read.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

if __name__ in {"__main__", "__mp_main__"}:
    data = os.environ.get("KINGMAKER_DATA_DIR", "").strip()
    if not data:
        sys.exit("Set KINGMAKER_DATA_DIR to a *copy* of the save: "
                 "this script must not touch saves/.")
    real_one = (Path(__file__).resolve().parent / "saves").resolve()
    if Path(data).resolve() == real_one:
        sys.exit(f"KINGMAKER_DATA_DIR points at the live save ({real_one}). "
                 "Use a copy.")
    os.environ.setdefault("KINGMAKER_PORT", "8081")
    logging.basicConfig(level=os.environ.get("KINGMAKER_LOG", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from kingmaker.main import start
    start(host="127.0.0.1", port=int(os.environ["KINGMAKER_PORT"]), show=False)
