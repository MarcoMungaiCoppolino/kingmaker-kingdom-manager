# -*- coding: utf-8 -*-
"""The launcher's secrets at rest: the blob round-trips, a tampered or
foreign blob fails cleanly, the file scheme keeps its file owner-only and
outside the game folder, and `launcher.json` carries no secret in clear
once saved — a file from before 1.4.0 is migrated by its first save.

Runs on the test scene; the secrets file goes to `tests/scene/vault/`
(`KINGMAKER_VAULT_DIR`, set by run_all.py), never to the home folder.
"""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kingmaker.launcher import core, vault  # noqa: E402

results = []
folder = Path(tempfile.mkdtemp(prefix="km-vault-"))
os.environ.setdefault("KINGMAKER_VAULT_DIR", str(folder / "vault"))

# 1. the file scheme, on every system
blob = vault.protect(b"shh-secret", scheme="file")
kept = vault.secrets_dir() / f"{blob['id']}.secret"
results.append(("the file scheme writes a file in the secrets folder, not in the game folder",
                blob["scheme"] == "file" and kept.is_file()
                and vault.secrets_dir() != Path(ROOT) / "saves"))
results.append(("and reads it back", vault.unprotect(blob) == b"shh-secret"))
if sys.platform != "win32":
    mode = stat.S_IMODE(kept.stat().st_mode)
    results.append(("the file is the owner's alone", mode == 0o600))
try:
    vault.unprotect({"scheme": "file", "id": "0123456789abcdef"})
    results.append(("a missing file is a clean error", False))
except vault.VaultError:
    results.append(("a missing file is a clean error", True))
try:
    vault.unprotect({"scheme": "file", "id": "../etc/passwd"})
    results.append(("an id that is not hex is refused", False))
except vault.VaultError:
    results.append(("an id that is not hex is refused", True))
vault.forget(blob)
results.append(("forget removes the file", not kept.exists()))

# 2. DPAPI, on Windows
if sys.platform == "win32":
    blob = vault.protect(b"shh-secret")
    results.append(("DPAPI is the default scheme on Windows", blob["scheme"] == "dpapi"))
    results.append(("a DPAPI blob round-trips", vault.unprotect(blob) == b"shh-secret"))
    results.append(("the blob is not the secret", "shh-secret" not in json.dumps(blob)))
    tampered = dict(blob, data=blob["data"][:-8] + "AAAAAAAA")
    try:
        vault.unprotect(tampered)
        results.append(("a tampered blob fails cleanly", False))
    except vault.VaultError:
        results.append(("a tampered blob fails cleanly", True))
else:
    results.append(("DPAPI is for Windows only", vault.default_scheme() == "file"))
    try:
        vault.protect(b"x", scheme="dpapi")
        results.append(("asking for DPAPI elsewhere is a clean error", False))
    except vault.VaultError:
        results.append(("asking for DPAPI elsewhere is a clean error", True))

# 3. launcher.json keeps no secret in clear
path = folder / "launcher.json"
settings = core.Settings(mode="online", token="AIR-TOKEN",
                         cloud={"app_key": "k", "refresh_token": "rt-secret", "table": "T", "role": "gm"})
settings.save(path)
text = path.read_text(encoding="utf-8")
results.append(("the saved file holds neither the token nor the refresh token",
                "AIR-TOKEN" not in text and "rt-secret" not in text and '"vault"' in text))
back = core.Settings.load(path)
results.append(("and the launcher reads them back from the vault",
                back.token == "AIR-TOKEN" and back.cloud.get("refresh_token") == "rt-secret"
                and back.cloud_ready and back.vault_error == "" and back == settings))
results.append(("the credential is whole again", back.credential() is not None
                and back.credential().refresh_token == "rt-secret"))

# 4. a file from before 1.4.0, in clear, is migrated by its first save
legacy = folder / "legacy.json"
legacy.write_text(json.dumps({"mode": "online", "token": "OLD-TOKEN",
                              "cloud": {"app_key": "k", "refresh_token": "old-rt", "table": "T"}}),
                  encoding="utf-8")
old = core.Settings.load(legacy)
results.append(("the old file is read as before", old.token == "OLD-TOKEN" and old.cloud_ready))
old.save(legacy)
after = legacy.read_text(encoding="utf-8")
results.append(("its first save moves the secrets into the vault",
                "OLD-TOKEN" not in after and "old-rt" not in after
                and core.Settings.load(legacy).token == "OLD-TOKEN"))

# 5. a vault that cannot be read: the rest of the settings survive, and the
#    launcher is told
broken = folder / "broken.json"
data = json.loads(path.read_text(encoding="utf-8"))
data["vault"] = {"scheme": "file", "id": "feedfeedfeedfeed"}
broken.write_text(json.dumps(data), encoding="utf-8")
hurt = core.Settings.load(broken)
results.append(("an unreadable vault leaves the settings without their secrets, and says so",
                hurt.vault_error != "" and not hurt.cloud_ready and hurt.token == ""
                and hurt.cloud.get("app_key") == "k" and hurt.mode == "online"))

# 6. forgetting the secrets removes the blob and its file
back.cloud = {}
back.token = ""
back.save(path)
results.append(("no secrets, no vault", core.Settings.load(path).vault == {}
                and '"vault": {}' in path.read_text(encoding="utf-8")))

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
