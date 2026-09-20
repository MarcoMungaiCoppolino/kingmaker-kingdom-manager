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
host.json                        host_id, host_name, epoch, seq, since, released, address
recent/save-e<epoch>-s<seq>.zip  the last five snapshots, written while playing
daily/save-<YYYY-MM-DD>.zip      the first snapshot of each UTC day, thirty kept
assets/<sha256>.<ext>            the images, one file per content hash, uploaded once
.clock                           an empty file, rewritten to read the server's time
```

A **snapshot** (`bundle.write_snapshot`) is the database alone — a consistent copy through
`Archive.backup_to` — plus a manifest with the marks and `{relative path: sha256}` of the
images (`bundle.asset_hashes`, thumbnails excluded). Images travel separately and once:
`sync.push_assets` uploads the hashes the `assets/` listing does not have,
`sync.pull_assets` fetches the ones a snapshot names and the local folder lacks. Your table's
20 MB map is uploaded on the first Start and never again.

`(epoch, seq)` orders everything: `epoch` rises at every take-over, `seq` at every upload. The
database records the marks of the copy it matches (`meta.sync_marks`, written through the
`synced` route), so a launcher can tell whether the cloud is ahead of its local file.

## Becoming the host (`sync.claim`)

1. Read `host.json` (absent: free) and the server's time.
2. Held by someone else and not `force` → `sync.Held`; the window shows "hosted by X since…",
   *Join* (the address the host wrote in the record) and, for an administrator, *Force
   take-over*. Held by us (a crash and a restart) → the epoch stays.
3. Write the record with `epoch + 1` in `update` mode on the rev just read (`add` when
   absent). A `path/conflict` means somebody wrote first: read again, three times at most.
4. `sync.newest_usable`: the recent copies newest first, then the daily ones; each is
   downloaded, `bundle.inspect`ed and `PRAGMA integrity_check`ed; the first usable wins. If
   its marks are ahead of the local database's, `core.load_save` puts it in (the previous
   local file kept as `.before-restore-<date>.bak`); if the local file is ahead — our own
   minutes that never got uploaded — it is kept and uploaded first. Then the images.
5. The server starts. When it says `KM ready`, `window.begin_hosting` starts the `Hoster`.

The claim runs in a thread; the window is told at each step through `Launcher.post`, which
puts the callback on the same queue as the server's lines, because `root.after` from another
thread is not safe.

## While hosting (`sync.Hoster`)

A thread ticking every `STATUS_EVERY` (30 s):

- **Heartbeat** every 60 s: the record rewritten in `update` mode. A conflict means the
  record is no longer ours — the administrator took the game — and the window stops the
  server without a final upload (`handle_taken`).
- **Snapshot** when the server's `rev` (from `GET /_launcher/status`) changed and the last
  upload is older than `UPLOAD_EVERY` (180 s): `POST /_launcher/snapshot?epoch=&seq=` →
  the bytes, the images pushed, `sync.upload_snapshot` (to `recent/`, and to `daily/` if the
  UTC day has no copy yet), the retention (`sync.prune`: 5 and 30), the record rewritten
  with the new `seq`, `POST /_launcher/synced` so the database records the marks. Recording
  the marks is itself a write that bumps `rev`, so the revision is read again afterwards.
- **On Stop** (`Hoster.stop(final=True)`): a last snapshot, then the record rewritten with
  `released: true`, so the next host need not wait 180 s. A server that died on its own
  releases the record without uploading (`handle_exit`).
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
| `POST /_launcher/synced` | records `{"epoch","seq"}` in `meta.sync_marks` |
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
and `cli.py` says what a refused token looks like.

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
revs, `server_modified`, the upload modes and their conflicts, a controllable clock and
injected 429s. `tests/test_sync.py` runs the client, the claim in every state (free, held,
stale, released, raced, forced), the copies and their retention, the pull with a corrupt
newest copy, the images by hash, and the five routes of a real server started on a scratch
folder — including the credential route refusing a wrong password and an unknown account.
The two-launcher hand-over was driven by hand against the fake, with two launchers in two
processes: A hosts and uploads, B is refused, A stops, B starts with A's game, A is refused,
A forces the take-over and B stops.
