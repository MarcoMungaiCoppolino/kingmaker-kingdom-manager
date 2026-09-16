"""Builds the installed app: the PyInstaller folder, then the Windows
installer (Inno Setup) or the Linux tarball, then a smoke test of what was
built.

    python packaging/build.py             everything
    python packaging/build.py --no-test   skip the smoke test
    python packaging/build.py --only-pack the PyInstaller folder only

Same script on this machine and in CI (`.github/workflows/release.yml`).
Outputs go to `packaging/out/`; `build/` and `dist/` are PyInstaller's.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kingmaker import __version__  # noqa: E402

OUT = ROOT / "packaging" / "out"
DIST = ROOT / "dist"
WINDOWS = sys.platform == "win32"
NAME = "Kingmaker Kingdom Manager" if WINDOWS else "kingmaker-kingdom-manager"
STEM = f"Kingmaker-Kingdom-Manager-{__version__}"
ISCC_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


def say(text: str) -> None:
    print(f"== {text}", flush=True)


def run(command: list[str], **kw) -> None:
    print("$", " ".join(str(c) for c in command), flush=True)
    subprocess.run(command, check=True, cwd=str(ROOT), **kw)


def check_tag() -> None:
    """In CI the tag must be the version, or the release would lie."""
    tag = os.environ.get("GITHUB_REF_NAME", "")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and tag.lstrip("v") != __version__:
        sys.exit(f"tag {tag} does not match kingmaker.__version__ = {__version__}")


def pack() -> Path:
    say(f"PyInstaller {NAME} {__version__}")
    shutil.rmtree(DIST / NAME, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         str(ROOT / "packaging" / "kingmaker.spec")])
    built = DIST / NAME
    if not built.is_dir():
        sys.exit(f"PyInstaller left nothing at {built}")
    return built


def find_iscc() -> Path | None:
    for candidate in ISCC_CANDIDATES:
        if candidate.is_file():
            return candidate
    found = shutil.which("ISCC") or shutil.which("iscc")
    return Path(found) if found else None


def installer(built: Path) -> Path | None:
    OUT.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        iscc = find_iscc()
        if iscc is None:
            say("Inno Setup not found: the PyInstaller folder is built, the Setup.exe is not "
                "(winget install JRSoftware.InnoSetup)")
            return None
        say("Inno Setup")
        run([str(iscc), f"/DAppVersion={__version__}", f"/DSourceDir={built}",
             f"/DOutputDir={OUT}", f"/DOutputName={STEM}-Setup",
             str(ROOT / "packaging" / "kingmaker.iss")])
        return OUT / f"{STEM}-Setup.exe"
    say("tarball")
    target = OUT / f"{STEM}-linux-x86_64.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        tar.add(built, arcname=NAME)
        for extra in ("kingmaker.desktop", "INSTALL.txt"):
            tar.add(ROOT / "packaging" / "linux" / extra, arcname=f"{NAME}/{extra}")
    return target


def smoke_test(built: Path, port: int = 8090) -> None:
    """Starts the built program with --serve on a temporary game folder,
    waits for `KM ready`, fetches the login page, asks it to stop."""
    say("smoke test")
    exe = built / (f"{NAME}.exe" if WINDOWS else NAME)
    game = Path(tempfile.mkdtemp(prefix="km-smoke-"))
    env = dict(os.environ, KINGMAKER_DATA_DIR=str(game / "saves"),
               KINGMAKER_ASSETS_DIR=str(game / "assets"),
               KINGMAKER_LAUNCHER_SECRET="smoke", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([str(exe), "--serve", "--no-browser", "--port", str(port)],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []
    ready = False
    deadline = time.time() + 90
    assert process.stdout is not None
    while time.time() < deadline:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                break
            continue
        lines.append(line.rstrip())
        if line.startswith("KM ready "):
            ready = True
            break
    if not ready:
        print("\n".join(lines[-40:]))
        process.kill()
        sys.exit("the built program never said KM ready")
    page = b""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=10) as answer:
            page = answer.read()
    finally:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/_launcher/shutdown",
                                         method="POST", headers={"X-Launcher-Secret": "smoke"})
        try:
            urllib.request.urlopen(request, timeout=5)
        except Exception:
            process.kill()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
    shutil.rmtree(game, ignore_errors=True)
    if b"Kingmaker" not in page:
        sys.exit("the login page did not come back from the built program")
    if any("admin-password" in line for line in lines) is False:
        sys.exit("no first-start password line from the built program")
    say(f"smoke test passed (exit code {process.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-test", action="store_true")
    parser.add_argument("--only-pack", action="store_true")
    args = parser.parse_args()
    check_tag()
    built = pack()
    if not args.no_test:
        smoke_test(built)
    if args.only_pack:
        return
    result = installer(built)
    if result is not None:
        say(f"done: {result} ({result.stat().st_size // 1_000_000} MB)")


if __name__ == "__main__":
    main()
