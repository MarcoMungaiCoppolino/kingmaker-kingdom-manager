"""The signed installers (`core.verify_download`, `launcher/keys.py`): a
good signature passes, a wrong key, a changed file, a missing name and
an unreadable signature are refused, a release without sums is "unsigned"."""
import hashlib
import os
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
results.append(("a release without sums is unsigned, not an error",
                core.verify_download(installer, release(False), fetch=fetch) == "unsigned"))


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

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
sys.exit(0 if all(ok for _n, ok in results) else 1)
