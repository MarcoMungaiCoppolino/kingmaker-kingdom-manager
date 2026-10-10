"""The owner signs a release: SHA256SUMS of its installers, and the
signature of that file with the offline release key.

    python packaging/sign_release.py new-key [path]
        Makes a key: the seed (the secret) in `path`, owner-only, printed
        nowhere; the public key on the screen, to paste into
        kingmaker/launcher/keys.py. Default path: ~/.kingmaker/release-key.txt

    python packaging/sign_release.py sign <version> [--key path]
        Downloads the release's installers with `gh`, writes SHA256SUMS and
        SHA256SUMS.sig next to them, and uploads both to the release. The
        release may still be a draft; publish it afterwards as usual.

The key never goes to GitHub: a compromised account can publish a release
but cannot sign it, and every launcher refuses an unsigned or missigned
installer (`core.verify_download`). Keep the seed file backed up offline.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kingmaker.access import ed25519  # noqa: E402
from kingmaker.launcher import keys  # noqa: E402

DEFAULT_KEY = Path.home() / ".kingmaker" / "release-key.txt"
INSTALLER_PATTERNS = ("*-Setup.exe", "*-linux-x86_64.tar.gz")


def new_key(path: Path) -> int:
    if path.exists():
        print(f"{path} exists already: not overwritten. Delete it first if you mean it.")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = ed25519.new_seed()
    path.write_text(seed.hex() + "\n", encoding="ascii")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"seed written to {path} (keep it offline, back it up)")
    print("public key, for kingmaker/launcher/keys.py:")
    print(f'    "{ed25519.public_key(seed).hex()}",')
    return 0


def read_seed(path: Path) -> bytes:
    text = path.read_text(encoding="ascii").strip()
    seed = bytes.fromhex(text)
    if len(seed) != ed25519.SEED_BYTES:
        raise SystemExit(f"{path}: not a 32-byte seed")
    public = ed25519.public_key(seed).hex()
    if public not in keys.RELEASE_KEYS:
        raise SystemExit(f"{path}: its public key {public[:12]}… is not in kingmaker/launcher/keys.py")
    return seed


def sign(version: str, key_path: Path) -> int:
    seed = read_seed(key_path)
    tag = version if version.startswith("v") else f"v{version}"
    with tempfile.TemporaryDirectory(prefix="km-sign-") as tmp:
        folder = Path(tmp)
        command = ["gh", "release", "download", tag, "--dir", str(folder)]
        for pattern in INSTALLER_PATTERNS:
            command += ["--pattern", pattern]
        subprocess.run(command, check=True, cwd=str(ROOT))
        files = sorted(p for p in folder.iterdir() if p.is_file())
        if not files:
            raise SystemExit(f"no installer found on {tag}")
        lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in files]
        sums = ("\n".join(lines) + "\n").encode("ascii")
        signature = ed25519.sign(seed, sums).hex() + "\n"
        (folder / keys.SUMS_NAME).write_bytes(sums)
        (folder / keys.SIG_NAME).write_text(signature, encoding="ascii")
        for line in lines:
            print(line)
        subprocess.run(["gh", "release", "upload", tag, str(folder / keys.SUMS_NAME),
                        str(folder / keys.SIG_NAME), "--clobber"], check=True, cwd=str(ROOT))
    print(f"{tag}: {keys.SUMS_NAME} and {keys.SIG_NAME} uploaded")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("new-key")
    make.add_argument("path", nargs="?", default=str(DEFAULT_KEY))
    do = sub.add_parser("sign")
    do.add_argument("version")
    do.add_argument("--key", default=str(DEFAULT_KEY))
    args = parser.parse_args(argv)
    if args.command == "new-key":
        return new_key(Path(args.path))
    return sign(args.version, Path(args.key))


if __name__ == "__main__":
    sys.exit(main())
