# -*- coding: utf-8 -*-
"""The screenshots of the manual, taken from a running copy of the app.

Chrome is driven headless over its DevTools protocol: it logs in, walks the
tabs, clicks a hex, proposes a journey, opens the Waters box and the accounts
dialog, and saves every page as a 2x PNG, then as the JPEG the manual shows.

    python docs/manual/screenshots.py en --secrets <file> [options]

The app must be running on a *copy* of the table (`launch_test.py` with
KINGMAKER_DATA_DIR set to the copy), never on the live save: the round logs
in, switches the language of the accounts it uses and proposes a journey. The
secrets file holds two words per account, name then password: a Game Master
(`--gm`) for the pages and an administrator (`--admin`) for the accounts
dialog. It is read, never printed, and must not be committed.

Options give the table's geometry (`--hex-size`, `--origin`, as in the map's
calibration) and the hexes to show: `--centre` scrolls the map there,
`--capital` is the hex opened for the hex sheet, `--traveller` the character
taken in hand and `--destination` the hex aimed at with the right button.
Needs Pillow and `websockets` (both come with the app) and Google Chrome.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image

HERE = Path(__file__).resolve().parent
W, DSF = 1600, 2
TABS = ("map", "kingdom", "turn", "city", "party", "transport", "manual", "gm")
PAGES = (("gm", "regia"), ("kingdom", "regno"), ("turn", "turno"), ("city", "citta"),
         ("party", "compagnia"), ("transport", "trasporti"), ("manual", "manuale"))
ACCEPT = {"it": "it-IT,it;q=0.9", "en": "en-GB,en;q=0.9"}
CHROME = {"win32": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          "linux": "google-chrome",
          "darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/130.0.0.0 Safari/537.36")


class Browser:
    """One headless Chrome, one page, the DevTools calls we need."""

    def __init__(self, chrome: str, lang: str, profile: Path, port: int = 9333):
        self.chrome, self.lang, self.profile, self.port = chrome, lang, profile, port
        self.proc = None
        self.ws = None
        self.next_id = 0

    async def __aenter__(self):
        self.proc = subprocess.Popen(
            [self.chrome, "--headless=new", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", f"--window-size={W},900", "--hide-scrollbars",
             f"--lang={self.lang}", "--no-first-run", "--force-device-scale-factor=1",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        targets = None
        for _ in range(100):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
                break
            except Exception:
                time.sleep(0.2)
        if not targets:
            raise RuntimeError("Chrome did not answer on its debugging port")
        page = next(t for t in targets if t["type"] == "page")
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=2 ** 28)
        await self.call("Page.enable")
        await self.call("Runtime.enable")
        await self.call("Network.enable")
        await self.call("Network.setUserAgentOverride", userAgent=AGENT,
                        acceptLanguage=ACCEPT[self.lang])
        await self.size(W, 1000)
        return self

    async def __aexit__(self, *_):
        await self.ws.close()
        self.proc.terminate()

    async def call(self, method: str, **params):
        self.next_id += 1
        mine = self.next_id
        await self.ws.send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            answer = json.loads(await self.ws.recv())
            if answer.get("id") == mine:
                if "error" in answer:
                    raise RuntimeError(f"{method}: {answer['error']}")
                return answer.get("result", {})

    async def js(self, expression: str):
        r = await self.call("Runtime.evaluate", expression=expression, awaitPromise=True,
                            returnByValue=True)
        if "exceptionDetails" in r:
            detail = r["exceptionDetails"].get("exception", {}).get("description", "javascript error")
            raise RuntimeError(detail)
        return r["result"].get("value")

    async def wait(self, condition: str, timeout: float = 30) -> None:
        start = time.time()
        while time.time() - start < timeout:
            try:
                if await self.js(f"!!({condition})"):
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.2)
        raise TimeoutError(condition)

    async def goto(self, url: str, settle: float = 1.5) -> None:
        await self.call("Page.navigate", url=url)
        await self.wait("document.readyState === 'complete'")
        await asyncio.sleep(settle)

    async def size(self, width: int, height: int) -> None:
        await self.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                        deviceScaleFactor=DSF, mobile=False)
        await asyncio.sleep(0.5)

    async def png(self, clip=None) -> bytes:
        params = {"format": "png"}
        if clip:
            x, y, w, h = clip
            params["clip"] = {"x": x, "y": y, "width": w, "height": h, "scale": 1}
        return base64.b64decode((await self.call("Page.captureScreenshot", **params))["data"])

    async def mouse(self, x: float, y: float, button: str = "left") -> None:
        await self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await asyncio.sleep(0.2)
        for kind in ("mousePressed", "mouseReleased"):
            await self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button=button,
                            clickCount=1)
        await asyncio.sleep(1.5)

    async def click_text(self, selector: str, text: str) -> None:
        """Click the first element matching selector whose text contains text."""
        ok = await self.js(f"""(() => {{
            const e = [...document.querySelectorAll({selector!r})]
                .find(e => e.innerText.includes({text!r}));
            if (!e) return false; e.scrollIntoView({{block: 'center'}}); e.click(); return true; }})()""")
        if not ok:
            raise RuntimeError(f"nothing matching {selector} with {text!r}")
        await asyncio.sleep(0.8)

    async def type_into(self, selector: str, text: str) -> None:
        await self.js(f"""(() => {{ const e = document.querySelector({selector!r}); e.focus();
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {text!r});
            e.dispatchEvent(new Event('input', {{bubbles: true}})); return true; }})()""")

    async def login(self, base: str, user: str, password: str) -> None:
        await self.goto(f"{base}/logout", settle=0.5)
        await self.goto(f"{base}/login")
        await self.ensure_language()
        await self.type_into("input[type=text]", user)
        await self.type_into("input[type=password]", password)
        await self.js("document.querySelector('input[type=password]').dispatchEvent("
                      "new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")
        await self.wait("location.pathname === '/' && document.querySelector('.q-tab')")
        await asyncio.sleep(2)
        await self.ensure_language()

    async def ensure_language(self) -> None:
        """The toggle shows the language it switches to: click it if that is ours."""
        clicked = await self.js(f"""(() => {{ const e = [...document.querySelectorAll('button')]
            .find(e => e.innerText.trim() === {self.lang.upper()!r});
            if (!e) return false; e.click(); return true; }})()""")
        if clicked:
            await asyncio.sleep(2.5)
            await self.wait("document.readyState === 'complete'")
            await asyncio.sleep(1.5)
            await self.size(W, 1000)


class Round:
    def __init__(self, browser: Browser, args):
        self.b, self.args = browser, args
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- pictures
    async def page(self, name: str) -> None:
        """The whole page, from the top: the viewport is stretched to its height."""
        await self.b.call("Input.dispatchMouseEvent", type="mouseMoved", x=4, y=4)
        await asyncio.sleep(0.8)
        height = int(await self.b.js("document.documentElement.scrollHeight"))
        await self.b.size(W, max(height + 8, 1000))
        await asyncio.sleep(0.6)
        self.save(name, await self.b.png(), width=1400)
        await self.b.size(W, 1000)

    async def box(self, name: str, selector: str, margin: int, factor: float) -> None:
        r = await self.b.js(f"document.querySelector({selector!r}).getBoundingClientRect().toJSON()")
        clip = (r["x"] - margin, r["y"] - margin, r["width"] + 2 * margin, r["height"] + 2 * margin)
        self.save(name, await self.b.png(clip), factor=factor)

    def save(self, name: str, png: bytes, width: int | None = None,
             factor: float | None = None) -> None:
        path = self.out / f"{name}.png"
        path.write_bytes(png)
        if self.args.jpeg:
            im = Image.open(path).convert("RGB")
            w, h = im.size
            factor = factor if factor is not None else width / w
            im = im.resize((round(w * factor), round(h * factor)), Image.LANCZOS)
            im.save(self.out / f"{name}.jpg", quality=86, optimize=True, progressive=True)
            path.unlink()
        print(name)

    # --------------------------------------------------------------------- map
    def hex_center(self, col: int, row: int) -> tuple[float, float]:
        size = self.args.hex_size
        ox, oy = self.args.origin
        return ox + math.sqrt(3) * size * (col + 0.5 * (row & 1)), oy + 1.5 * size * row

    async def geometry(self) -> dict:
        return await self.b.js("""(() => { const box = document.querySelector('.km-drag');
            const img = box.querySelector('img'); const r = img.getBoundingClientRect();
            return {x: r.x, y: r.y, scale: r.width / img.naturalWidth}; })()""")

    async def scroll_to(self, col: int, row: int) -> None:
        cx, _cy = self.hex_center(col, row)
        g = await self.geometry()
        await self.b.js(f"(() => {{ const box = document.querySelector('.km-drag'); "
                        f"box.scrollLeft = {cx * g['scale']} - box.clientWidth / 2; return true; }})()")
        await asyncio.sleep(0.5)

    async def click_hex(self, col: int, row: int, button: str = "left") -> None:
        cx, cy = self.hex_center(col, row)
        g = await self.geometry()
        await self.b.mouse(g["x"] + cx * g["scale"], g["y"] + cy * g["scale"], button)

    async def tab(self, name: str) -> None:
        await self.b.js(f"document.querySelectorAll('.q-tab')[{TABS.index(name)}].click()")
        await asyncio.sleep(1.5)

    async def portrait(self, name: str) -> None:
        """The portrait card at the foot of the map: the deepest element with that name."""
        ok = await self.b.js(f"""(() => {{ const hits = [...document.querySelectorAll('.q-tab-panel *')]
            .filter(e => e.children.length === 0 && e.innerText && e.innerText.trim() === {name!r});
            const e = hits[hits.length - 1]; if (!e) return false; e.click(); return true; }})()""")
        if not ok:
            raise RuntimeError(f"no portrait called {name}")
        await asyncio.sleep(1.2)

    # ------------------------------------------------------------------ rounds
    async def gm(self, user: str, password: str) -> None:
        a = self.args
        await self.b.login(a.base, user, password)
        await self.scroll_to(*a.centre)
        await self.page("mappa")
        await self.click_hex(*a.capital)
        await self.page("mappa-esagono")
        await self.b.click_text(".q-tab-panel button", "hiking")     # Travel, by its icon
        await self.portrait(a.traveller)
        await self.click_hex(*a.destination, button="right")
        await self.page("mappa-viaggio")
        await self.portrait(a.traveller)                              # let go of them
        await self.b.click_text(".q-tab-panel button", "hiking")
        await self.b.click_text(".q-tab-panel button", "water")      # the Waters box
        await asyncio.sleep(1.5)
        await self.page("mappa-acque")
        await self.b.click_text(".q-tab-panel button", "water")
        for name, picture in PAGES:
            await self.tab(name)
            await self.page(picture)

    async def admin(self, user: str, password: str) -> None:
        a = self.args
        await self.b.goto(f"{a.base}/logout", settle=0.5)
        await self.b.goto(f"{a.base}/login")
        await self.b.ensure_language()
        await self.box("accesso", ".q-card", 40, 0.75)
        await self.b.login(a.base, user, password)
        await self.b.click_text("button", "manage_accounts")
        await asyncio.sleep(2)
        await self.box("account", ".q-dialog .q-card", 24, 0.5)


def secrets_of(path: str) -> dict[str, str]:
    words = Path(path).read_text(encoding="utf-8").split()
    return {words[i]: words[i + 1] for i in range(0, len(words) - 1, 2)}


def pair(text: str) -> tuple[int, int]:
    col, row = text.split(",")
    return int(col), int(row)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("lang", choices=("en", "it"))
    p.add_argument("--secrets", required=True,
                   help="file with name and password per account, never committed")
    p.add_argument("--gm", default="Marco", help="the Game Master account")
    p.add_argument("--admin", default="admin", help="the administrator account")
    p.add_argument("--base", default="http://127.0.0.1:8081")
    p.add_argument("--out", default=None, help="folder of the pictures (default: img/screenshots[/it])")
    p.add_argument("--jpeg", action="store_true", help="reduce to the manual's JPEGs and drop the PNGs")
    p.add_argument("--chrome", default=CHROME.get(sys.platform, "google-chrome"))
    p.add_argument("--hex-size", type=float, default=161.25)
    p.add_argument("--origin", type=lambda s: tuple(float(v) for v in s.split(",")),
                   default=(190.0, -64.0))
    p.add_argument("--centre", type=pair, default=(19, 4))
    p.add_argument("--capital", type=pair, default=(18, 7))
    p.add_argument("--traveller", default="Argyon")
    p.add_argument("--destination", type=pair, default=(20, 3))
    args = p.parse_args()
    if args.out is None:
        args.out = HERE / "img" / "screenshots" / ("it" if args.lang == "it" else "")
    secrets = secrets_of(args.secrets)
    profile = Path(tempfile.gettempdir()) / "kingmaker-screenshots-profile"

    async def run():
        async with Browser(args.chrome, args.lang, profile) as b:
            round_ = Round(b, args)
            await round_.gm(args.gm, secrets[args.gm])
            await round_.admin(args.admin, secrets[args.admin])
    asyncio.run(run())


if __name__ == "__main__":
    main()
