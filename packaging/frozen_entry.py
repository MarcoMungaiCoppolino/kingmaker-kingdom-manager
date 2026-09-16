"""The entry point of the installed app.

Without arguments it opens the launcher window; with `--serve` it is the
server, with the same flags as `launch.py`. The launcher starts the server
by running this same executable again with `--serve`, so one file does both.
"""
from __future__ import annotations

import multiprocessing
import sys

from kingmaker.cli import main

if __name__ == "__main__":
    # Cheap insurance: a frozen program that spawns a process without this
    # runs its whole self again in the child.
    multiprocessing.freeze_support()
    main(frozen=True, prog=sys.argv[0].rsplit("\\", 1)[-1].rsplit("/", 1)[-1])
