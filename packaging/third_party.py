"""The licences of everything the installed app bundles, in one file.

    python packaging/third_party.py [folder]      writes THIRD_PARTY_LICENSES.txt there
                                                  (default: the repository root)

`build.py` runs it into the PyInstaller folder, so the Windows installer and
the Linux tarball ship the file next to the program. The MIT licence and its
kin ask for their text to travel with any binary that contains the code: the
frozen app contains some fifty Python packages, the browser libraries NiceGUI
serves, the Material icons and the Roboto face it ships, Python itself with
Tcl/Tk, PyInstaller's bootloader, and the three typefaces of the interface.

What can be read from the environment is read: every installed distribution
that is not a build tool, through `importlib.metadata`, with the licence
files its wheel carries. What no metadata knows — the JavaScript inside
NiceGUI's `static/`, Python's own licence, Tcl/Tk's — is listed by hand
below, with the standard text once per licence. Run it in the same
environment that builds the app, or the list will not match the binary.
"""
from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kingmaker import __version__  # noqa: E402

OUTPUT = "THIRD_PARTY_LICENSES.txt"
# Not shipped: they build the app, they are not in it. PyInstaller is the
# one exception, handled below, because its bootloader is in the binary.
BUILD_TOOLS = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib",
               "altgraph", "pefile", "pywin32-ctypes", "packaging", "macholib",
               "kingmaker-kingdom-manager"}
FONTS_DIR = ROOT / "kingmaker" / "ui" / "static" / "fonts"

MIT = """MIT License

Copyright (c) {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

APACHE_NOTE = """Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy of
the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations under
the License. The full text of the Apache License 2.0 is reproduced once at
the end of this file.
"""

# The browser side, served by NiceGUI from its `static/` folder. Nothing in
# the Python metadata names them, so here they are: (name, licence, holder,
# home page).
BROWSER_LIBRARIES = [
    ("Vue.js", "MIT", "2018-present, Yuxi (Evan) You", "https://vuejs.org/"),
    ("Quasar Framework", "MIT", "2015-present Razvan Stoenescu", "https://quasar.dev/"),
    ("Tailwind CSS", "MIT", "Tailwind Labs, Inc.", "https://tailwindcss.com/"),
    ("Socket.IO client", "MIT", "2014-2024 Guillermo Rauch", "https://socket.io/"),
    ("DOMPurify", "Apache-2.0 OR MPL-2.0", "2015 Mario Heiderich", "https://github.com/cure53/DOMPurify"),
    ("Immutable.js", "MIT", "2014-present, Lee Byron and other contributors", "https://immutable-js.com/"),
    ("Dart Sass (JavaScript build)", "MIT", "2016, Google Inc.", "https://sass-lang.com/"),
    ("UnoCSS", "MIT", "2021-present Anthony Fu", "https://unocss.dev/"),
    ("Material Icons and Material Symbols", "Apache-2.0", "Google LLC", "https://fonts.google.com/icons"),
    ("Roboto", "Apache-2.0", "Google LLC (Christian Robertson)", "https://fonts.google.com/specimen/Roboto"),
]

# The typefaces of the interface, shipped in `kingmaker/ui/static/fonts/`,
# each with the OFL text from the google/fonts repository.
TYPEFACES = [
    ("Cinzel", "OFL-cinzel.txt", "https://github.com/NDISCOVER/Cinzel"),
    ("IBM Plex Sans", "OFL-ibmplexsans.txt", "https://github.com/IBM/plex"),
    ("Press Start 2P", "OFL-pressstart2p.txt", "https://github.com/google/fonts/tree/main/ofl/pressstart2p"),
]


def rule(title: str) -> str:
    return f"\n{'=' * 78}\n{title}\n{'=' * 78}\n\n"


def licence_name(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    for value in meta.get_all("Classifier") or []:
        if value.startswith("License ::"):
            return value.split("::")[-1].strip()
    text = (meta.get("License") or "").strip()
    return text.splitlines()[0][:80] if text else "see the licence text below"


def licence_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """(name, text) of every licence file the wheel declared or carries."""
    found: list[tuple[str, str]] = []
    names = set(dist.metadata.get_all("License-File") or [])
    for file in dist.files or []:
        text = str(file).replace("\\", "/")
        base = text.rsplit("/", 1)[-1]
        if ".dist-info/" not in text:
            continue
        if text.split(".dist-info/", 1)[1] in names or base in names \
                or base.upper().startswith(("LICEN", "COPYING", "NOTICE", "AUTHORS")):
            try:
                found.append((base, file.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue
    return found


def python_licence() -> str:
    """Python's own licence (and Tcl/Tk's on Windows), from the interpreter
    the app was frozen with."""
    base = Path(sys.base_prefix)
    pieces = []
    for candidate in (base / "LICENSE.txt", base / "LICENSE",
                      Path(sys.base_prefix, "lib", f"python{sys.version_info[0]}.{sys.version_info[1]}",
                           "LICENSE.txt")):
        if candidate.is_file():
            pieces.append(candidate.read_text(encoding="utf-8", errors="replace"))
            break
    else:
        pieces.append("PSF License Agreement for Python — https://docs.python.org/3/license.html\n")
    for candidate in sorted((base / "tcl").glob("tcl8*/license.terms")) if (base / "tcl").is_dir() else []:
        pieces.append("\n--- Tcl/Tk ---\n\n" + candidate.read_text(encoding="utf-8", errors="replace"))
        break
    else:
        pieces.append("\n--- Tcl/Tk ---\n\nTcl/Tk licence — https://www.tcl.tk/software/tcltk/license.html\n")
    return "".join(pieces)


def apache_full() -> str:
    """The Apache 2.0 text, taken from any installed wheel that carries it,
    else a pointer."""
    for dist in metadata.distributions():
        for _name, text in licence_files(dist):
            if "Apache License" in text and "Version 2.0, January 2004" in text:
                return text
    return "https://www.apache.org/licenses/LICENSE-2.0.txt\n"


def build(target_dir: Path) -> Path:
    out: list[str] = []
    out.append(f"Kingmaker Kingdom Manager {__version__} — third-party licences\n\n"
               "The program itself is under the MIT licence (LICENSE). The game rules are Open\n"
               "Game Content under the Open Game License v1.0a (OPEN_GAME_LICENSE.md); the\n"
               "Pathfinder and Kingmaker names appear under Paizo's Community Use Policy\n"
               "(NOTICE.md). Everything below is the work of others, bundled with this app\n"
               "under the licence stated for each. Python {0} on {1}.\n".format(
                   sys.version.split()[0], sys.platform))

    out.append(rule("1. Python packages"))
    seen = set()
    dists = sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower())
    for dist in dists:
        name = dist.metadata["Name"] or ""
        key = name.lower()
        if not name or key in seen or key in BUILD_TOOLS:
            continue
        seen.add(key)
        home = dist.metadata.get("Home-page") or ""
        for url in dist.metadata.get_all("Project-URL") or []:
            if not home and url.lower().startswith(("homepage", "source", "repository")):
                home = url.split(",", 1)[-1].strip()
        out.append(f"\n--- {name} {dist.version} — {licence_name(dist)}"
                   f"{' — ' + home if home else ''} ---\n\n")
        files = licence_files(dist)
        if files:
            for file_name, text in files:
                out.append(f"[{file_name}]\n{text.rstrip()}\n\n")
        else:
            out.append("(the wheel carries no licence file; see the project page)\n\n")

    out.append(rule("2. PyInstaller bootloader"))
    try:
        pyi = metadata.distribution("pyinstaller")
        out.append(f"PyInstaller {pyi.version}. Only its bootloader — the small program that\n"
                   "unpacks and starts the app — is inside the executable. PyInstaller is\n"
                   "under the GPL 2.0 with a special exception that lets the bootloader be\n"
                   "bundled with software under any licence; the app's own MIT licence is\n"
                   "unaffected.\n\n")
        for file_name, text in licence_files(pyi):
            out.append(f"[{file_name}]\n{text.rstrip()}\n\n")
    except metadata.PackageNotFoundError:
        out.append("(this file was written outside the build environment: PyInstaller is not\n"
                   "installed here, and no bootloader is bundled in a source install)\n")

    out.append(rule("3. Python and Tcl/Tk"))
    out.append(python_licence())

    out.append(rule("4. Browser libraries and fonts served by NiceGUI"))
    out.append("NiceGUI ships these in its `static/` folder; the app's pages load them from\n"
               "the host, never from the internet.\n\n")
    for name, licence, holder, home in BROWSER_LIBRARIES:
        out.append(f"\n--- {name} — {licence} — {home} ---\n\n")
        if licence == "MIT":
            out.append(MIT.format(holder=holder))
        elif licence.startswith("Apache-2.0 OR"):
            out.append(f"Copyright (c) {holder}. Offered under the Apache License 2.0 or the\n"
                       "Mozilla Public License 2.0, at the user's choice; used here under\n"
                       "the Apache License 2.0.\n\n" + APACHE_NOTE)
        else:
            out.append(f"Copyright (c) {holder}.\n\n" + APACHE_NOTE)

    out.append(rule("5. The typefaces of the interface"))
    out.append("Served by the app from `kingmaker/ui/static/fonts/`, each under the SIL Open\n"
               "Font License 1.1, whose text follows with the copyright of each face.\n\n")
    for name, file_name, home in TYPEFACES:
        path = FONTS_DIR / file_name
        text = path.read_text(encoding="utf-8") if path.is_file() else "(licence file missing)\n"
        out.append(f"\n--- {name} — OFL-1.1 — {home} ---\n\n{text.rstrip()}\n\n")

    out.append(rule("6. Apache License 2.0 (full text)"))
    out.append(apache_full())

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / OUTPUT
    target.write_text("".join(out), encoding="utf-8", newline="\n")
    return target


def main() -> None:
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    target = build(target_dir)
    print(f"wrote {target} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
