# 13. The cloud: hosting from several PCs

One PC runs the game; when its owner is offline, nobody plays. The cloud sync lets the
hosting move between the trusted people of the table — the administrator and the GMs
flagged *Can host* — through a folder in the administrator's Dropbox. Everything here lives
in the launcher (`kingmaker/launcher/dropbox.py`, `sync.py`, `wizard.py`) and in five routes of
the server; `python launch.py` from source and Docker know nothing about it.

## The rules the design follows

- **Hosts are trusted people.** A launcher may host only with the credential of the table's
  cloud folder, and a running host hands it out only to accounts that pass
  `permissions.HOST_GAME`: every administrator, and a GM with `users.can_host = 1` (the
  checkbox on the GM's row in the accounts dialog). Players never hold the save. A host's
  disk holds everything — fog, GM notes, password hashes — which is why the flag is a trust
  decision and not a convenience.
- **One host at a time.** `host.json` in the folder says who; the compare-and-swap on its
  Dropbox `rev` makes two launchers unable to take it in the same instant.
- **Time is the server's.** A record is *held* when Dropbox's `server_modified` of it is
  younger than `HEARTBEAT_STALE` (180 s). A launcher writes an empty `.clock` file and reads
  its `server_modified` to learn "now" (`sync.server_now`), so a laptop with a wrong clock
  cannot steal the game.
- **The credential is never in the database**, hence never in a Save-tab zip. It lives in
  each host's `launcher.json`, in clear like the On Air token, and travels to a new host over
  the credential route.

## The folder

```
host.json                        host_id, host_name, epoch, seq, since, released, address,
                                 app_version, beat, seen
recent/save-e<epoch>-s<seq>.zip  the last five snapshots, written while playing
daily/save-<YYYY-MM-DD>.zip      the first snapshot of each UTC day, thirty kept
assets/<sha256>.<ext>            the images, one file per content hash, uploaded once
.clock                           an empty file, rewritten to read the server's time
table.json                       format, table_id, name, app_version, air_token, air_address,
                                 air_generation, access_generation, set_by, set_at (since 1.3.0)
```

A **snapshot** (`bundle.write_snapshot`) is the database alone — a consistent copy through
`Archive.backup_to` — plus a manifest with the marks and `{relative path: sha256}` of the
images (`bundle.asset_hashes`, thumbnails excluded). Images travel separately and once:
`sync.push_assets` uploads the hashes the `assets/` listing does not have,
`sync.pull_assets` fetches the ones a snapshot names and the local folder lacks. Your table's
20 MB map is uploaded on the first Start and never again.

`(epoch, seq)` orders everything: `epoch` rises at every take-over, `seq` at every upload. The
database records the marks of the copy it matches (`meta.sync_marks`, written through the
`synced` route), so a launcher can tell whether the cloud is ahead of its local file. Since
1.3.0 the marks also carry `krev`, the kingdom document's revision (`STATE.k["_rev"]`, which
`theme.mark_dirty` raises at every change and `Archive.write` stores in `kingdoms.rev`) at the
moment of the upload: comparing it with the revision the file has now (`Archive.document_rev`)
tells a copy that merely fell behind the cloud from one that was **played on since** —
`core.LocalState.diverged`. A file synced before 1.3.0 recorded it cannot say, and the cloud
wins as it always did.

Images travel with three checks on the way down (`sync.pull_assets`), because the manifest
was written by another host: the path must stay inside the assets folder (`bundle.safe_asset`,
the same test `bundle.restore` makes on a zip) and end in an image's extension
(`images.EXTENSIONS`); the bytes must hash to the name they came under; and they must be an
image (`imgsize.sizes`, the uploads' sniff). A refusal is one line in the log, and the file is
written through a `.part` sibling, so nothing half-arrived is ever served.

## The table's file (`table.json`, `sync.TableRecord`)

What the table *is*, as opposed to who hosts it right now: a random `table_id`, the name, the
**version every host must run**, and the **On Air token**. The first launcher of 1.3.0 or
newer that claims the record and finds no file creates it (`sync.ensure_table`): its own
version pins the table, and its local token goes in if it has one. Every later Start reads it
(`window.settle_table`) before claiming anything. Writes go through a compare-and-swap on the
file's rev (`sync.write_table`; a conflict reads again and writes once more, keeping what the
caller set). Any member of the folder can write the file — Dropbox gives no finer right — so
the launcher's manners below are a convention, not a wall, and the user guide says so.

**The version.** `TableRecord.mismatch` is an exact string match, patch releases included,
because the same save format has carried different rules (1.1.7 and 1.2.0 both write schema
29 and play different games). On a mismatch nothing is claimed: `window.version_dialog` offers
*Install {version}* — `core.find_release` looks the exact release up on GitHub and
`download_update` runs it (Windows) or opens its page (Linux) — and, to the administrator, a
move. A move **up** writes the file at once after the pull; a move **down** reaches the file
only after `newest_usable` has read the cloud's newest copy, since a copy from a newer app
stops the pull (`NewerCopy`) and leaves the table where it was. Old launchers (≤ 1.2.0) do not
read the file and cannot be stopped from hosting; the "hosted by" line names a host's version
and marks one too old to know the table's (`launcher.cloud.hosted_by_old`).

**The token.** With the cloud, no host keeps the On Air token on disk: `settle_table` returns
the file's token, `claimed` carries it to `start_server`, and `core.server_environment(token=…)`
puts it in the server's environment for that run. The migration from 1.2.x is one Start: the
administrator's local token goes into the file (and whenever it differs from the file's — a
renewal made while the cloud was away), a GM's local copy fills an empty file, and both are
then forgotten locally (`window.token_moved`, the field replaced by a line that says where the
token lives, `refresh_air`). *Lost the token?* stays the administrator's door: the wizard still
writes the token locally, and `window.publish_token` moves it into the file with
`air_generation + 1`; the other hosts read it at their next Start with nothing to do.

**The address.** When the server prints its On Air address, `window.handle_line` looks at it
twice. An address with `/devices/` in it is the relay's anonymous device: the token was refused
(`core.is_random_air_address`, the shape `cli.py` describes), said in red. Otherwise
`window.verify_address` asks the public address `GET /_launcher/whoami?nonce=<hex>` (three
tries over half a minute, the relay takes a moment to route) and compares the answer's `proof`
with `core.whoami_proof(secret, nonce)` — an HMAC of the nonce under this start's launcher
secret, which only this server can make. A match is a quiet log line and the address written
into the file (`air_address`); a mismatch is a warning: another program holds the table's
address. The same probe runs from *Who is hosting?* when the record says nobody hosts
(`window.probe_idle`): something of ours answering at the table's address then means somebody
else holds the token. Both are detection, not prevention; the manual's security notes say so.

## Becoming the host (`sync.claim`)

0. Read `table.json` (created if absent); a version mismatch ends here, with the dialog above.
1. Read `host.json` (absent: free) and the server's time.
2. Held by someone else and not `force` → `sync.Held`; the window shows "hosted by X since…",
   *Join* (the address the host wrote in the record) and, for an administrator, *Force
   take-over*. Held by us (a crash and a restart) → the epoch stays.
3. Write the record with `epoch + 1` in `update` mode on the rev just read (`add` when
   absent). A `path/conflict` means somebody wrote first: read again, three times at most.
4. `sync.newest_usable`: the recent copies newest first, then the daily ones; each is
   downloaded, `bundle.inspect`ed and `PRAGMA integrity_check`ed; the first usable wins. A
   corrupt copy is skipped for the next. A copy that `inspect` refuses as **newer** than this
   app (`main.newer_schema`) stops the search with `sync.NewerCopy`: falling back to an older
   copy there rolled the game back to before the newer host played, and nobody knew. The
   window releases the record, says which version wrote the copy and offers the Versions
   window (`claim_failed_newer`). A recent copy whose epoch is above the record's is skipped
   with a log line: epochs come from the record alone, so no host ever wrote it.
5. If the copy's marks are ahead of the local database's, it is loaded (`core.load_save`, the
   previous local file kept as `.before-restore-<date>.bak`) — unless the local file
   **diverged** too (`core.local_state`, above): then `window.fork_dialog` asks which copy is
   the game. *Load the cloud's copy* keeps the local one as the `.bak`; *Keep mine* loads
   nothing and lets the first upload, under the new epoch, become the newest copy; *Cancel*
   releases the record. If the local file is simply ahead — our own minutes that never got
   uploaded — it is kept and uploaded first. Then the images.
6. The server starts. When it says `KM ready`, `window.begin_hosting` starts the `Hoster`.

Before step 1, one more question when it applies: a record that is held, alive, and carries
**our own `host_id`** while this process never held it (`Launcher.hosted_before`) is either a
crash and a restart or a game folder copied to another PC, which carries the same identity.
Only the person knows which, so the window asks before taking it (`launcher.cloud.same_identity`).
A thread cannot touch the widgets, so `Launcher.ask` posts the question to the Tk thread and
waits for the answer.

**Hosting without the cloud.** When Dropbox does not answer, `claim_failed` offers to host
without it, in words that say what it is: a fork. The server then starts with
`core.server_environment(..., cloud=False)`: **no token**, so the table's fixed address never
points at a copy the cloud knows nothing about, and no credential to hand out from a server
nobody is told of. Leaving the token out is not enough — `cli.resolve_online` also reads it
from the user's environment and, on Windows, from the registry — so the launcher sets
`KINGMAKER_ON_AIR_ANONYMOUS=1`, which makes the server go online with a random address
whatever token it could find. The day is written to `meta.forked_at` (`core.mark_fork`) and shown in the
fork dialog at the next cloud start, which clears it once the question is settled.

The claim runs in a thread; the window is told at each step through `Launcher.post`, which
puts the callback on the same queue as the server's lines, because `root.after` from another
thread is not safe.

## While hosting (`sync.Hoster`)

A thread ticking every `STATUS_EVERY` (30 s):

- **Heartbeat** every 60 s: the record rewritten in `update` mode, with `beat` raised first so
  that the bytes differ from the last write: Dropbox keeps an upload of identical content as
  the same revision, `server_modified` included, and a host with nothing new to say would have
  looked dead after three quiet minutes. A conflict means the record is no longer ours — the
  administrator took the game — and the window stops the server without a final upload
  (`handle_taken`).
- **Snapshot** when the server's `rev` (from `GET /_launcher/status`) changed and the last
  upload is older than `UPLOAD_EVERY` (180 s): `POST /_launcher/snapshot?epoch=&seq=` →
  the bytes, the images pushed, `sync.upload_snapshot` (to `recent/`, and to `daily/` if the
  UTC day has no copy yet), the retention (`sync.prune`: 5 and 30), the record rewritten
  with the new `seq`, `POST /_launcher/synced` so the database records the marks. Recording
  the marks is itself a write that bumps `rev`, so the revision is read again afterwards.
- **On Stop** (`Hoster.stop(final=True)`): a last snapshot, then the record rewritten with
  `released: true`, so the next host need not wait 180 s; `sync.release` asks three times
  with a pause when Dropbox does not answer, and gives up quietly (the record then goes stale
  on its own). A server that died on its own releases the record without uploading
  (`handle_exit`).
- Every call honours `Retry-After` on 429 and retries with a growing pause
  (`dropbox.Client._call`); `too_many_write_operations` is retried at once, as Dropbox asks.
  Failures go to the status line and the log, never to the game.

## The server's routes (`main.launcher_route`)

Registered only when the launcher started the server (the secret in
`KINGMAKER_LAUNCHER_SECRET`); the first four answer only `127.0.0.1` with the secret in
`X-Launcher-Secret`, anything else is a 404:

| Route | What |
|---|---|
| `POST /_launcher/shutdown` | stop, the last save written |
| `GET /_launcher/status` | `{"rev", "kingdom", "synced"}` |
| `POST /_launcher/snapshot?epoch=&seq=` | the database-only bundle, after `theme.write_to_disk()` |
| `POST /_launcher/synced` | records `{"epoch","seq","krev"}` in `meta.sync_marks` |
| `GET /_launcher/whoami?nonce=` | **over the network**, open: `{"proof": HMAC(secret, nonce), "app"}` |
| `POST /_launcher/credential` | **over the network**: `{"username","password"}` → the credential |

The credential route exists only when the launcher passed a credential in
`KINGMAKER_SYNC_CREDENTIAL` (`core.server_environment`: the Dropbox app key and refresh
token, the account, the table's name and the table's On Air token). It runs `auth.verify` off
the loop, with the same throttles by name and by address as the login page, then
`permissions.can(who, HOST_GAME)`; a refusal of any kind is a 404. The hand-out is written
to the journal. All five paths are in `login.OPEN_PAGES`, or the access middleware would
redirect them to `/login`.

## The three dialogs (`launcher/wizard.py`)

**Set up Dropbox…** (the administrator, once): seven steps with a picture each from
`launcher/guide/` — a Dropbox account; *Create app* in the App Console with *Scoped access*
and *App folder*; the five permissions; the *App key* pasted in, with the table's name; the
authorisation page opened with the PKCE URL (`dropbox.authorize_url`, `token_access_type=
offline`, no redirect): Dropbox warns that the app has few users, asks to allow, and shows
the code; the code pasted back on its own step (`dropbox.exchange_code` → the refresh token,
`Client.account()` for the name, kept even if that lookup fails, since the code is spent);
done. The pictures are the owner's screenshots of the console, numbered where the order of
clicks matters. Each
administrator creates their own Dropbox app, so no table depends on the author's app or on
Dropbox's review of it.

**Set up On Air…** (whoever hosts, when the table plays online): seven steps with a picture
each from `launcher/guide/air/` — what the relay is and the site opened with `core.ON_AIR_PAGE`
(`https://on-air.nicegui.io/login`, which is where the site lives; `nicegui.io/on_air` has been
a 404 since 1.1.3 and was the old button's target); the login dialog, where On Air sends you to
GitHub; GitHub's sign-in, which is where the password is typed, so neither On Air nor this app
sees it; the table with no device in it and *+ ADD DEVICE*, which is what a new account really
meets; the dialog that hands out the token, which pressing that button opens by itself, with
the token pasted back — all `settings.token` ever is; the cog and its *New token*, for the day
the token is lost or the device was already there; done. That last step has a door of its own:
*Lost the token?* in the On Air box opens `AirWizard(..., start="renew")` straight at it, and
from there *Paste the new token…* goes back to the field. Walking from the first step would not
do, because the step before it is the one that asks for the token that has been lost; and the
closing step says "Token saved" only when a token really is saved, since arriving from the
renewal step nobody has necessarily written one down. The steps follow the one road a new
account walks — add the device, take the token it hands out — and leave the making of another
token to the end, where it belongs: needed once in a long while, and never on the way in. The wizard
asks nothing of the network itself — whether the token works is answered by the first Start,
and `cli.py` says what a refused token looks like. With the cloud set up, the administrator's
wizard ends with `window.publish_token`: the token goes into `table.json` and is forgotten
locally, so a renewal reaches every host at their next Start.

Its pictures are screenshots of the live site with the organization's name and the token
blurred out, taken in September 2026; the site says it is moving its login to GitHub, so they
will want taking again when it does.

**Connect to a table…** (the other hosts): the table's address, username, password →
`core.fetch_credential` → `core.adopt_credential` keeps the cloud, the table's token and our
role; the password is not kept. *Forget the cloud* clears it; an administrator is also
offered to revoke the credential at Dropbox (`Client.revoke`), after which every host must
connect again.

## Dropbox, as checked in September 2026

Free plan: 2 GB, version history 30 days not counted against the quota; our usage is
under 100 MB for years. Rate limits are per linked user and unpublished; a limited call gets
a 429 with `Retry-After`. `files/upload` takes up to 150 MB per call; `mode: update` with a
`rev` is the compare-and-swap. The refresh token "won't expire automatically"; access tokens
last four hours and are refreshed on demand. `KINGMAKER_DROPBOX_API`, `_CONTENT` and `_WWW`
point the client at another base URL: the tests' fake.

## Testing

`tests/fake_dropbox.py` is a Dropbox in one process: `http.server` on an in-memory dict with
revs, `server_modified`, the upload modes and their conflicts, a controllable clock, injected
429s and, switched on by `box.dedupe`, the real service's habit of keeping identical bytes as
the old revision. `tests/test_sync.py` runs the client, the claim in every state (free, held,
stale, released, raced, forced), the copies and their retention, the pull with a corrupt
newest copy, with a newer-app copy (stops) and with a copy above the record's epoch (ignored),
the images by hash and the three refusals, the heartbeat under `dedupe`, the table's file
(created once, read by the next launcher, matched exactly, written on a stale rev), the
`whoami` proof and the launcher's probe of it, and the five other routes of a real server started on a scratch
folder — including the credential route refusing a wrong password and an unknown account.
The two-launcher hand-over was driven by hand against the fake, with two launchers in two
processes: A hosts and uploads, B is refused, A stops, B starts with A's game, A is refused,
A forces the take-over and B stops.
