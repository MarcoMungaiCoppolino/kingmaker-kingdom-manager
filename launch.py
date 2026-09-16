"""Starts Kingmaker Kingdom Manager locally:  python launch.py

Add --lan to make it reachable from the other PCs on your network, or
--online to play with distant friends (see the README). --launcher opens
the same window the installed app shows, to start and stop the server
without a terminal.
"""
from __future__ import annotations

from kingmaker.cli import main

if __name__ in {"__main__", "__mp_main__"}:
    main()
