"""The command line, shared by `launch.py` and the installed app.

    python launch.py                 the server, as always
    python launch.py --launcher      the launcher window, from source
    <installed app>                  the launcher window
    <installed app> --serve [...]    the server, with the same flags as launch.py

The server flags are one parser in one place, so the launcher, the frozen
entry point and the terminal never disagree on them.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

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


def parser(prog: str | None = None) -> argparse.ArgumentParser:
    from kingmaker import config
    p = argparse.ArgumentParser(prog=prog, description="Kingmaker Kingdom Manager")
    p.add_argument("--serve", action="store_true",
                   help="start the server (the default from launch.py; the installed "
                        "app opens the launcher window without it)")
    p.add_argument("--launcher", action="store_true",
                   help="open the launcher window instead of the server")
    p.add_argument("--lan", action="store_true",
                   help="listen on 0.0.0.0 to share it on the local network")
    p.add_argument("--port", type=int, default=config.PORT,
                   help=f"port to listen on (now {config.PORT}; "
                        "KINGMAKER_PORT changes it too)")
    p.add_argument("--no-browser", action="store_true",
                   help="do not open the browser at startup")
    p.add_argument("--online", nargs="?", const=True, metavar="TOKEN",
                   help="publish the game on the internet with NiceGUI On Air; "
                        f"without a token here it is read from the "
                        f"{TOKEN_VARIABLE} environment variable, so it does not "
                        "end up in the shell history")
    return p


def resolve_online(online) -> str | bool | None:
    """What `--online` means once the environment has been looked at: a
    token, True (an anonymous address) or None (not online at all)."""
    if online is not True:
        return online
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
        return True
    # Here we only know the variable is there: if the token was
    # revoked the relay refuses it and assigns an anonymous device
    # anyway. Better say what to look at than promise the address.
    print(f"On Air token read from {TOKEN_VARIABLE}.")
    print("  Check the address below: if it looks like")
    print("  https://europe.on-air.io/devices/XXXXXXXX/ the token was not")
    print("  accepted, usually because it was revoked or regenerated.")
    print("  Get a new one at https://on-air.nicegui.io/login.")
    print()
    return online


def serve(args: argparse.Namespace) -> None:
    from kingmaker import config
    from kingmaker.main import start
    start(host="0.0.0.0" if args.lan else config.HOST,
          port=args.port, show=not args.no_browser,
          online=resolve_online(args.online))


def main(argv: list[str] | None = None, frozen: bool = False, prog: str | None = None) -> None:
    """The entry point. From source the server is the default; in the
    installed app no argument means the launcher window."""
    configure_log()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser(prog).parse_args(argv)
    if args.launcher or (frozen and not args.serve and not argv):
        from kingmaker.launcher import window
        window.run()
        return
    serve(args)
