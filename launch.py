"""Starts Kingmaker Kingdom Manager locally:  python launch.py

Add --lan to make it reachable from the other PCs on your network, or
--online to play with distant friends (see the README).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from kingmaker import config
from kingmaker.main import start

TOKEN_VARIABLE = "KINGMAKER_ON_AIR_TOKEN"


def saved_token() -> str | None:
    """The Windows user's token, read from the registry.

    `SetEnvironmentVariable(..., "User")` writes here, but a program inherits
    the environment from whoever started it: if VS Code (or the terminal) was
    already open when you set it, it does not see it, and there is no way to
    guess that from the error. We go and read it ourselves.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, TOKEN_VARIABLE)
    except (ImportError, OSError):
        return None
    value = str(value).strip()
    return value or None


def configure_log() -> None:
    """Without this the `log.info` of the migrations and the `log.debug` of the
    failed redraws were never seen. KINGMAKER_LOG=DEBUG to turn the volume up."""
    logging.basicConfig(level=os.environ.get("KINGMAKER_LOG", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


if __name__ in {"__main__", "__mp_main__"}:
    configure_log()
    parser = argparse.ArgumentParser(description="Kingmaker Kingdom Manager")
    parser.add_argument("--lan", action="store_true",
                        help="listen on 0.0.0.0 to share it on the local network")
    parser.add_argument("--port", type=int, default=config.PORT,
                        help=f"port to listen on (now {config.PORT}; "
                             "KINGMAKER_PORT changes it too)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open the browser at startup")
    parser.add_argument("--online", nargs="?", const=True, metavar="TOKEN",
                        help="publish the game on the internet with NiceGUI On Air; "
                             f"without a token here it is read from the "
                             f"{TOKEN_VARIABLE} environment variable, so it does not "
                             "end up in the shell history")
    args = parser.parse_args()
    online = args.online
    if online is True:
        online = (os.environ.get(TOKEN_VARIABLE) or "").strip() or None
        if online is None:
            online = saved_token()
            if online:
                print(f"{TOKEN_VARIABLE} was not in the environment of this window,")
                print("  but I found it among your Windows user variables: using that one.")
        if not online:
            # Without a token On Air assigns an anonymous device, with a
            # different address at every start: better say so, or one waits
            # for one's own.
            print(f"! {TOKEN_VARIABLE} is not set in this session: "
                  "the game goes online with a random address.\n"
                  "  For your fixed address, in this same window:\n"
                  f'    PowerShell:  $env:{TOKEN_VARIABLE} = "YOUR-TOKEN"\n'
                  f"    cmd.exe:     set {TOKEN_VARIABLE}=YOUR-TOKEN\n"
                  "  If you saved it with [Environment]::SetEnvironmentVariable(...,'User'), "
                  "it only applies to windows opened afterwards: open a new terminal.\n")
            online = True
        else:
            # Here we only know the variable is there: if the token was
            # revoked the relay refuses it and assigns an anonymous device
            # anyway. Better say what to look at than promise the address.
            print(f"On Air token read from {TOKEN_VARIABLE}.")
            print("  Check the address below: if it looks like")
            print("  https://europe.on-air.io/devices/XXXXXXXX/ the token was not")
            print("  accepted, usually because it was revoked or regenerated.")
            print("  Get a new one at https://nicegui.io/on_air.")
            print()
    start(host="0.0.0.0" if args.lan else config.HOST,
          port=args.port, show=not args.no_browser, online=online)
