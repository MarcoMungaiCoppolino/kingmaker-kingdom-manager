"""The signed installers (`core.verify_download`, `launcher/keys.py`): a
good signature passes, a wrong key, a changed file, a missing name and
an unreadable signature are refused, a release without sums is "unsigned"."""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kingmaker.access import ed25519  # noqa: E402
from kingmaker.launcher import core, keys  # noqa: E402

results: list[tuple[str, bool]] = []
folder = Path(tempfile.mkdtemp(prefix="km-updates-"))
installer = folder / "Kingmaker-Kingdom-Manager-2.0.0-Setup.exe"
installer.write_bytes(b"MZ not really an installer " * 100)
other = folder / "Kingmaker-Kingdom-Manager-2.0.0-linux-x86_64.tar.gz"
other.write_bytes(b"\x1f\x8b tarball")

owner_seed = ed25519.new_seed()
owner_key = ed25519.public_key(owner_seed).hex()
stranger_seed = ed25519.new_seed()
keys.RELEASE_KEYS = (owner_key,)                # the owner's key, for this run

sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in (installer, other)).encode()
served = {"mem://sums": sums, "mem://sig": (ed25519.sign(owner_seed, sums).hex() + "\n").encode("ascii")}


def release(with_sums: bool = True) -> core.Release:
    assets = [{"name": installer.name, "url": "mem://exe"}, {"name": other.name, "url": "mem://tar"}]
    if with_sums:
        assets += [{"name": keys.SUMS_NAME, "url": "mem://sums"}, {"name": keys.SIG_NAME, "url": "mem://sig"}]
    return core.Release(version="2.0.0", page="https://example/releases", assets=assets)


def fetch(url: str) -> bytes:
    return served[url]


results.append(("a release with the sums and the signature counts as signed", release().signed))
results.append(("one without them does not", not release(False).signed))
results.append(("a good signature over a matching hash: signed",
                core.verify_download(installer, release(), fetch=fetch) == "signed"))
results.append(("the other installer of the same list too",
                core.verify_download(other, release(), fetch=fetch) == "signed"))
try:
    core.verify_download(installer, release(False), fetch=fetch)
    results.append(("a release from 2.0.0 on without the signed list is refused (2.2.0)", False))
except ValueError as error:
    results.append(("a release from 2.0.0 on without the signed list is refused (2.2.0)",
                    keys.SIGNED_SINCE in str(error)))
old_installer = folder / "Kingmaker-Kingdom-Manager-1.4.0-Setup.exe"
old_installer.write_bytes(b"MZ an installer from before the signatures")
old_release = core.Release(version="1.4.0", page="https://example/releases",
                           assets=[{"name": old_installer.name, "url": "mem://old"}])
results.append(("a release from before the signatures without sums is unsigned, not an error",
                core.verify_download(old_installer, old_release, fetch=fetch) == "unsigned"))
newer_tag = core.Release(version="2.1.4", page="https://example/releases", assets=release().assets)
try:
    core.verify_download(installer, newer_tag, fetch=fetch)
    results.append(("an older release's signed installer under a newer tag is refused (2.2.0)", False))
except ValueError as error:
    results.append(("an older release's signed installer under a newer tag is refused (2.2.0)",
                    "2.1.4" in str(error)))
decoy = core.Release(version="2.0.0", page="https://example/releases",
                     assets=[{"name": "Evil-Setup.exe", "url": "mem://evil"},
                             {"name": "Evil-linux-x86_64.tar.gz", "url": "mem://evil2"}])
results.append(("a release offers no installer under another name, only this version's own",
                decoy.installer() is None
                and release().installer()["name"] == core.installer_name("2.0.0")))


def refused(name: str, path: Path, serving: dict) -> None:
    try:
        core.verify_download(path, release(), fetch=lambda url: serving[url])
        results.append((name, False))
    except ValueError:
        results.append((name, True))


refused("a signature by another key is refused", installer,
        dict(served, **{"mem://sig": (ed25519.sign(stranger_seed, sums).hex() + "\n").encode()}))
tampered = folder / installer.name
tampered.write_bytes(installer.read_bytes() + b"!")
refused("a file whose bytes changed is refused", tampered, served)
installer.write_bytes(b"MZ not really an installer " * 100)
unlisted = folder / "Kingmaker-Kingdom-Manager-2.0.1-Setup.exe"
unlisted.write_bytes(b"MZ")
refused("a file the signed list does not name is refused", unlisted, served)
refused("an unreadable signature is refused", installer, dict(served, **{"mem://sig": b"not hex"}))
forged_sums = sums.replace(installer.name.encode(), b"x" + installer.name.encode()[1:])
refused("a list rewritten after signing is refused", installer, dict(served, **{"mem://sums": forged_sums}))
keys.RELEASE_KEYS = ()
refused("with no key shipped nothing is trusted", installer, served)
keys.RELEASE_KEYS = (owner_key,)
results.append(("the shipped key list holds hex keys of the right length",
                all(len(k) == 64 and all(c in "0123456789abcdef" for c in k)
                    for k in __import__("importlib").reload(keys).RELEASE_KEYS)))

# The latest release when GitHub's API refuses (its hourly limit per address):
# the releases page names the tag, and the files follow from it.
asked = []


def api_refused() -> dict:
    asked.append("api")
    raise OSError("HTTP Error 403: rate limit exceeded")


def page_off() -> str:
    raise OSError("offline")


found = core.latest_release(api=api_refused, page=lambda: "v2.1.2")
names = [a["name"] for a in found.assets] if found else []
results.append(("the API refused, the releases page names the tag: the release with its four files",
                found is not None and found.version == "2.1.2" and found.signed
                and "Kingmaker-Kingdom-Manager-2.1.2-Setup.exe" in names
                and "Kingmaker-Kingdom-Manager-2.1.2-linux-x86_64.tar.gz" in names
                and found.assets[0]["url"] == f"https://github.com/{core.REPOSITORY}/releases/download/v2.1.2/"
                f"Kingmaker-Kingdom-Manager-2.1.2-Setup.exe"
                and found.page.endswith("/releases/tag/v2.1.2")))
results.append(("both refused: nothing, no error", core.latest_release(api=api_refused, page=page_off) is None))
results.append(("a page naming no tag: nothing", core.latest_release(api=api_refused, page=lambda: "") is None))
results.append(("a tag that is not a version: nothing",
                core.latest_release(api=api_refused, page=lambda: "latest") is None))
answered = core.latest_release(api=lambda: {"tag_name": "v9.9.9", "html_url": "h", "assets": []},
                               page=page_off)
results.append(("the API answering: its release, the page never asked",
                answered is not None and answered.version == "9.9.9" and answered.page == "h"))
results.append(("the release page's tag is read from the redirect's address",
                core.release_from_tag("v2.0.0").version == "2.0.0" and core.release_from_tag("junk") is None))

# --- 2.3.0: whether GitHub answered at all, and the versions worth listing ---------
results.append(("check_latest: both refused, (None, False): «could not check»",
                core.check_latest(api=api_refused, page=page_off) == (None, False)))
results.append(("the API refused, the page answering with no tag: (None, True), checked",
                core.check_latest(api=api_refused, page=lambda: "") == (None, True)))
release, reached = core.check_latest(api=lambda: {"tag_name": "v9.9.9", "html_url": "h", "assets": []},
                                     page=page_off)
results.append(("the API answering: (release, True)", reached and release is not None and release.version == "9.9.9"))
mine = core.installer_name("3.0.0")
with_file = core.Release(version="3.0.0", page="p", assets=[{"name": mine, "url": "u"}])
without = core.Release(version="2.9.9", page="p", assets=[])
results.append(("the versions list keeps only releases with this system's installer",
                core.with_installer([with_file, without]) == [with_file]))

shutil.rmtree(folder, ignore_errors=True)
for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
sys.exit(0 if all(ok for _n, ok in results) else 1)
