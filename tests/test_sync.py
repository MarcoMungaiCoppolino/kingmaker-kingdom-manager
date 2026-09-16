# -*- coding: utf-8 -*-
"""The cloud sync against a Dropbox that fits in one process
(`fake_dropbox.py`): the client, the claim, the heartbeat, the copies and
their retention, the pull, the credential route of a real server.

Runs on the test scene like the rest of the suite; the server started for
the credential route uses a scratch folder of its own.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from fake_dropbox import FakeDropbox  # noqa: E402

results = []
folder = Path(tempfile.mkdtemp(prefix="km-sync-"))
box = FakeDropbox().__enter__()
os.environ["KINGMAKER_DROPBOX_API"] = box.url
os.environ["KINGMAKER_DROPBOX_CONTENT"] = box.url
os.environ["KINGMAKER_DROPBOX_WWW"] = box.url

from kingmaker.launcher import dropbox, sync  # noqa: E402
from kingmaker.state import STATE  # noqa: E402
from kingmaker.storage import bundle  # noqa: E402

A = STATE.archive
credential = dropbox.Credential(app_key="key", refresh_token="rt-secret")
naps = []
client = dropbox.Client(credential, sleep=naps.append)

# 1. OAuth: the URL carries PKCE and offline access; the code is exchanged
verifier = dropbox.new_verifier()
url = dropbox.authorize_url("key", verifier)
results.append(("the authorise URL asks for offline access with PKCE",
                "token_access_type=offline" in url and "code_challenge_method=S256" in url
                and "client_id=key" in url))
answer = dropbox.exchange_code("key", verifier, " GOOD-CODE ")
results.append(("the pasted code becomes a refresh token", answer.get("refresh_token") == "rt-secret"))
try:
    dropbox.exchange_code("key", verifier, "BAD")
    results.append(("a wrong code is refused", False))
except dropbox.DropboxError as error:
    results.append(("a wrong code is refused", error.status == 400))

# 2. the client: upload, metadata, download, compare-and-swap, 429
meta = client.upload("a/one.txt", b"hello", mode="add")
results.append(("upload answers with a rev", bool(meta.get("rev")) and box.refreshes == 1))
data, meta2 = client.download("a/one.txt")
results.append(("download returns bytes and metadata", data == b"hello" and meta2["rev"] == meta["rev"]))
results.append(("metadata of a missing file is None", client.metadata("a/none.txt") is None))
client.upload("a/one.txt", b"hello again", mode="update", rev=meta["rev"])
try:
    client.upload("a/one.txt", b"stale", mode="update", rev=meta["rev"])
    results.append(("a stale rev is a conflict", False))
except dropbox.DropboxError as error:
    results.append(("a stale rev is a conflict", error.conflict))
results.append(("the conflict did not write", client.download("a/one.txt")[0] == b"hello again"))
box.fail_next(429, retry_after=2)
naps.clear()
client.metadata("a/one.txt")
results.append(("429 waits Retry-After and retries", naps == [2.0]))
box.fail_next(429, retry_after=0, summary="too_many_write_operations")
naps.clear()
client.upload("a/two.txt", b"x", mode="overwrite")
results.append(("write contention retries at once", naps == [0.0]))
results.append(("list_folder of a missing folder is empty", client.list_folder("nowhere") == []))
results.append(("list_folder sees the files", {e["name"] for e in client.list_folder("a")} == {"one.txt", "two.txt"}))
client.delete("a/two.txt")
client.delete("a/two.txt")            # already gone: no error
results.append(("delete is idempotent", {e["name"] for e in client.list_folder("a")} == {"one.txt"}))
used, allocated = client.space_usage()
results.append(("space usage is read", allocated == 2 * 1024 ** 3 and used > 0))

# 3. the claim: free, held, stale, released, race, force
box.clock = 1_800_000_000.0
mine = sync.claim(client, "host-A", "Alice")
results.append(("a free folder is claimed at epoch 1", mine.epoch == 1 and mine.host_id == "host-A"))
try:
    sync.claim(client, "host-B", "Bob")
    results.append(("a held record refuses another host", False))
except sync.Held as held:
    results.append(("a held record refuses another host", held.record.host_name == "Alice"))
again = sync.claim(client, "host-A", "Alice")
results.append(("the same host claims again without a new epoch", again.epoch == 1))
box.clock += sync.HEARTBEAT_STALE + 1
stale = sync.claim(client, "host-B", "Bob")
results.append(("a stale record is taken with the next epoch", stale.epoch == 2 and stale.host_id == "host-B"))
sync.release(client, stale)
released = sync.claim(client, "host-A", "Alice")
results.append(("a released record is taken at once", released.epoch == 3))
forced = sync.claim(client, "host-B", "Bob", force=True)
results.append(("force takes a living host's game", forced.epoch == 4))
try:
    sync.heartbeat(client, released)
    results.append(("the old host's heartbeat conflicts", False))
except dropbox.DropboxError as error:
    results.append(("the old host's heartbeat conflicts", error.conflict))
# a race: somebody rewrites the record between our read and our write
record_before = sync.read_record(client)
box.clock += sync.HEARTBEAT_STALE + 1
box.put("host.json", sync.HostRecord(host_id="host-C", host_name="Cara", epoch=5).body())
box.clock += sync.HEARTBEAT_STALE + 1
raced = sync.claim(client, "host-A", "Alice")
results.append(("a race is retried and lands on top", raced.epoch == 6))

# 4. snapshots: recent five, daily once a day, thirty kept, assets by hash
assets = folder / "assets"
(assets / "characters").mkdir(parents=True)
(assets / "map.jpg").write_bytes(b"JPEG-map")
(assets / "characters" / "aldric.png").write_bytes(b"PNG-face")
(assets / "thumbnails").mkdir()
(assets / "thumbnails" / "small.png").write_bytes(b"tiny")
hashes = bundle.asset_hashes(assets)
results.append(("asset hashes skip thumbnails", set(hashes) == {"map.jpg", "characters/aldric.png"}))
known = sync.push_assets(client, assets, hashes)
uploaded = len(client.list_folder("assets"))
calls_before = len(box.calls)
sync.push_assets(client, assets, hashes, known)
results.append(("images are uploaded once", uploaded == 2 and len(box.calls) == calls_before))
snap = bundle.write_snapshot(A, assets, folder / "snap.zip", {"epoch": 6, "seq": 1})
with zipfile.ZipFile(snap) as zf:
    names = set(zf.namelist())
results.append(("a snapshot holds the database and the manifest, no images",
                names == {"kingmaker.db", "manifest.json"}))
results.append(("the manifest carries the marks and the hashes",
                sync.marks_of(snap) == (6, 1) and bundle.manifest(snap)["assets"] == hashes))
results.append(("a snapshot passes the integrity check", bundle.integrity_ok(snap)))
payload = snap.read_bytes()
done = sync.upload_snapshot(client, payload, 6, 1, today="2026-09-16")
results.append(("the first upload of the day writes the daily copy too",
                done["recent"] == "save-e6-s1.zip" and done["daily"] == "save-2026-09-16.zip"))
for seq in range(2, 9):
    sync.upload_snapshot(client, payload, 6, seq, today="2026-09-16")
recent = sorted(e["name"] for e in client.list_folder("recent"))
results.append(("five recent copies are kept, the newest ones",
                recent == [f"save-e6-s{s}.zip" for s in range(4, 9)]))
results.append(("one daily copy per day", len(client.list_folder("daily")) == 1))
for day in range(1, 35):
    sync.upload_snapshot(client, payload, 7, day, today=f"2026-10-{day:02d}")
results.append(("thirty daily copies are kept", len(client.list_folder("daily")) == 30))

# 5. the pull: newest usable first, a corrupt one skipped, images fetched
box.put("recent/save-e9-s1.zip", b"not a zip at all")
picked = sync.newest_usable(client, folder / "pulled")
results.append(("a corrupt newest copy is skipped for the next usable",
                picked is not None and picked.name == "save-e7-s34.zip"))
other_assets = folder / "other-assets"
fetched = sync.pull_assets(client, other_assets, hashes)
results.append(("the images a snapshot refers to are fetched",
                fetched == 2 and (other_assets / "map.jpg").read_bytes() == b"JPEG-map"))
results.append(("already present images are not fetched again",
                sync.pull_assets(client, other_assets, hashes) == 0))

# 6. the record survives a round trip and ages with the server's clock
record = sync.read_record(client)
results.append(("the record is read back with its rev", record is not None and record.rev
                and record.host_id == "host-A" and record.epoch == 6))

# 7. the credential route of a real server: a scratch game, first start
game = folder / "game"
(game / "saves").mkdir(parents=True)
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
env = dict(os.environ, KINGMAKER_DATA_DIR=str(game / "saves"), KINGMAKER_ASSETS_DIR=str(game / "assets"),
           KINGMAKER_LAUNCHER_SECRET="shh", PYTHONIOENCODING="utf-8", PYTHONPATH=ROOT,
           KINGMAKER_SYNC_CREDENTIAL=json.dumps({"app_key": "key", "refresh_token": "rt-secret",
                                                  "table": "Testland", "token": "AIR"}))
server = subprocess.Popen([sys.executable, os.path.join(ROOT, "launch.py"), "--serve", "--no-browser",
                           "--port", str(port)], env=env, cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
password = None
deadline = time.time() + 60
assert server.stdout is not None
while time.time() < deadline:
    line = server.stdout.readline()
    if not line:
        break
    if line.startswith("KM admin-password "):
        password = line.split(" ", 2)[2].strip()
    if line.startswith("KM ready "):
        break
from kingmaker.launcher import core  # noqa: E402


def ask(username, pw):
    try:
        return core.fetch_credential(f"http://127.0.0.1:{port}", username, pw)
    except LookupError as error:
        return str(error)


got = ask("admin", password or "")
results.append(("the administrator receives the credential",
                isinstance(got, dict) and got["credential"]["refresh_token"] == "rt-secret"
                and got["credential"]["token"] == "AIR" and got["role"] == "admin"))
results.append(("a wrong password is a 404", ask("admin", "wrong-password") == "404"))
results.append(("an unknown account is a 404", ask("nobody", "whatever-1234") == "404"))
settings = core.Settings()
core.adopt_credential(settings, got if isinstance(got, dict) else {"credential": {}})
results.append(("the launcher keeps what it was handed",
                settings.cloud_ready and settings.token == "AIR" and settings.cloud["table"] == "Testland"
                and settings.cloud["role"] == "admin"))
status_request = urllib.request.Request(f"http://127.0.0.1:{port}/_launcher/status",
                                        headers={"X-Launcher-Secret": "shh"})
with urllib.request.urlopen(status_request, timeout=10) as answer_:
    status = json.loads(answer_.read().decode("utf-8"))
results.append(("the status route answers the launcher", "rev" in status))
try:
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/_launcher/status",
                                                  headers={"X-Launcher-Secret": "wrong"}), timeout=10)
    results.append(("a wrong secret is a 404", False))
except urllib.error.HTTPError as error:
    results.append(("a wrong secret is a 404", error.code == 404))
local = sync.LocalServer(port, "shh")
snapshot = local.snapshot(3, 7)
(folder / "from-server.zip").write_bytes(snapshot)
results.append(("the snapshot route returns a marked snapshot",
                sync.marks_of(folder / "from-server.zip") == (3, 7)
                and bundle.integrity_ok(folder / "from-server.zip")))
local.synced(3, 7)
results.append(("the synced marks are recorded", local.status().get("synced") == {"epoch": 3, "seq": 7}))
stop = urllib.request.Request(f"http://127.0.0.1:{port}/_launcher/shutdown", method="POST",
                              headers={"X-Launcher-Secret": "shh"})
try:
    urllib.request.urlopen(stop, timeout=10)
except Exception:
    server.kill()
try:
    server.wait(timeout=20)
except subprocess.TimeoutExpired:
    server.kill()

box.__exit__(None, None, None)
shutil.rmtree(folder, ignore_errors=True)
for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
