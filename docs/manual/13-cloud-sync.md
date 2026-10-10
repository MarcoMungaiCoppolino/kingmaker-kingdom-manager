# 13. The cloud: hosting from several PCs

One PC runs the game; when its owner is offline, nobody plays. The cloud sync lets the
hosting move between the trusted people of the table — the administrator and the GMs whose
launcher the administrator paired — through a folder in the administrator's Dropbox.
Everything here lives in the launcher (`kingmaker/launcher/dropbox.py`, `sync.py`, `wizard.py`,
`vault.py`), in `access/pairing.py` and in seven routes of the server; `python launch.py` from
source and Docker know nothing about it.

## The rules the design follows

- **Hosts are trusted people.** A launcher may host only with the credential of the table's
  cloud folder, and it gets it by **pairing**: the administrator, logged into the game, makes a
  code (`access/pairing.py`, from the accounts dialog behind `MANAGE_USERS`), and the joining
  launcher sends it — and nothing else, no password — to the running host's
  `POST /_launcher/pair`. Players never hold the save. A host's disk holds everything — fog,
  GM notes, password hashes — which is why the code is the administrator's to make and not a
  checkbox for everyone (`users.can_host` stays in the schema, unread, since 2.0.0).
- **One host at a time.** `host.json` in the folder says who; the compare-and-swap on its
  Dropbox `rev` makes two launchers unable to take it in the same instant.
- **Time is the server's.** A record is *held* when Dropbox's `server_modified` of it is
  younger than `HEARTBEAT_STALE` (180 s). A launcher writes a `.clock` file and reads its
  `server_modified` to learn "now" (`sync.server_now`), so a laptop with a wrong clock cannot
  steal the game. The file's bytes change at every write, because Dropbox keeps an upload of
  identical content as the same revision: until 2.0.0 it was rewritten empty, the clock
  stood at the first cloud start, every record looked zero seconds old, and a crashed host's
  record never went stale (probed on the real service on 2026-10-06).
- **The credential is never in the database**, hence never in a Save-tab zip. It rests on each
  host's PC in the launcher's vault (chapter 12: DPAPI on Windows, an owner-only file outside
  the game folder on Linux), travels to a new host over the pairing route, and is handed to
  the server in its environment for the run. It is one credential for the whole table, by
  decision: removing a host means rotating it for all (`window.rotate_access`, below).

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

The document's revision does not see an edit that touches only a table: a portrait, a
vehicle in the stable, a journey. Since 2.1.0 the marks also carry `trev`, the counter of the
campaign's tables (`meta.tables_rev`). SQLite raises it through triggers on every table of
`Archive.TRACKED_TABLES` (the campaign's tables except the kingdom document, which has its
own revision, and the journal, which only follows changes made elsewhere), so no writer can
forget it. `LocalState.diverged` compares both; marks written before 2.1.0 hold no `trev`,
and only the document is compared, as before.

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
token lives, `refresh_air`). *New token…* stays the administrator's door: the wizard still
writes the token locally, and `window.publish_token` moves it into the file with
`air_generation + 1`; the other hosts read it at their next Start with nothing to do.

**The address.** A refused token gives no address at all: the relay answers through NiceGUI's
logger, `Connection error: Invalid device token "…"`, every five seconds, and never connects
(seen on the real relay on 2026-10-06; the game is then local and LAN only). `core.parse_line`
turns that line into `air-refused`, the launcher says so once per start in red, and
`core.mask_secrets` hides the token the line quotes before the log pane keeps it. An address
with `/devices/` in it is the relay's anonymous device, what a start *without* a token gets
(`core.is_random_air_address`); with a token expected it is reported too. Otherwise, when the
server prints its On Air address, `window.handle_line` goes on to the check: 
`window.verify_address` asks the public address `GET /_launcher/whoami?nonce=<hex>` (three
tries over half a minute, the relay takes a moment to route) and compares the answer's `proof`
with `core.whoami_proof(secret, nonce)` — an HMAC of the nonce under this start's launcher
secret, which only this server can make. `core.address_state` reads the answer as `ours`,
`other` (a proof that is not ours, or a page where the proof should be: a program that is not
this server) or `none` (a 404, what the relay serves when no program is connected). `ours` is
a quiet log line and the address written into the file (`air_address`); `other` is a warning:
another program holds the table's address. The check is repeated **every five minutes while
hosting** (`Launcher.RECHECK_EVERY_MS`), because of what the real relay did when probed on
2026-10-06: given two programs with one token, it hands the address to the newest connection
and tells the one before nothing — the first keeps running, unaware, and gets no traffic. A
check at start alone would miss a hijack an hour later. The same probe runs from the check
of who is hosting when the record says nobody hosts (`window.probe_idle`; its warning is shown
once per address, `Launcher.alarmed`, since that check repeats every minute): anything but a 404 at the
table's address then means somebody else holds the token. Both are detection, not prevention;
the manual's security notes say so.

## Becoming the host (`sync.claim`)

0. Read `table.json` (created if absent); a version mismatch ends here, with the dialog above.
1. Read `host.json` (absent: free) and the server's time.
2. Held by someone else and not `force` → `sync.Held`; the window shows "hosted by X since…",
   *Join* (the address the host wrote in the record) and, for an administrator, *Ask to hand
   over…* (below). Held by us (a crash and a restart) → the epoch stays.
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
| `POST /_launcher/synced` | records `{"epoch","seq","krev","trev"}` in `meta.sync_marks` |
| `GET /_launcher/whoami?nonce=` | **over the network**, open: `{"proof": HMAC(secret, nonce), "app"}` |
| `POST /_launcher/pairing` | a fresh pairing code for the launcher that started us |
| `POST /_launcher/pair` | **over the network**: `{"code","host_name"}` → the credential, once |
| `POST /_launcher/credential` | the hand-out of 1.x: `410`, gone in 3.0 |

The pairing routes exist only when the launcher passed a credential in
`KINGMAKER_SYNC_CREDENTIAL` (`core.server_environment`: the Dropbox app key and refresh
token, the account, the table's name and `table_id`; not the token, which is in `table.json`).
`access/pairing.py` keeps one code at a time as its SHA-256, with its expiry (ten minutes),
its wrong tries (three kill it) and who made it; `pairing.check` spends the right code at its
first use. The route answers 404 to everything else and consults the table's brake for
everyone (`auth.global_wait`) first; the making and the use of a code are written to the
journal. The administrator's launcher offers the same code while it hosts
(`window.make_pairing_code` → `LocalServer.pairing` → the local route; the dialog shows the
code with the address the other launcher must type), and the Table box says so in words. On
the joining side `core.pair` sends the code with the launcher's id and public key, and the
game answers with the hosts' credential, the table's id, the administrator's public key and
an **admission** (`sync.make_admission`): the newcomer's id, name and key signed with the
hosting launcher's seed, which reached the game through the environment
(`KINGMAKER_LAUNCHER_SIGN`, `KINGMAKER_LAUNCHER_ID`). `core.adopt_pairing` keeps the answer
only after it opened the table's folder, found the `table_id` the host named on a table file
`trusted_by` the administrator's key handed out, and found the admission vouched for
(`sync.known_launchers` over the folder's list plus this admission); it then appends the
admission to `launchers.json` (`sync.add_launcher`, a compare-and-swap). A program at a
hijacked address, or a host running a copy that is not the table's, hands out something that
fails there and nothing is kept. Every path is in `login.OPEN_PAGES`, or the access middleware
would redirect it to `/login`.

Transport: through the On Air address the launcher speaks TLS to the relay, so a Wi-Fi
eavesdropper sees nothing (the relay sees everything, as it does for every login); on the LAN
the exchange is plain HTTP, exactly as exposed as every password typed at the login page
there. No home-made encryption, on purpose.

**Change the keys** (`window.rotate_access`, the administrator's Table box): the set-up
wizard reopened at the *hosts_authorise* step with the app key already known → a new hosts'
refresh token (`cloud.hosts_refresh_token`), saved; the old one revoked with a client built on
it (`auth/token/revoke` disables the calling token and no other); the administrator's own
token untouched; `table.json.access_generation` raised and the file re-signed; a closing
dialog that says what to do (a code for each remaining host; a new On Air token if the person
also had the table's address). On every other PC the next cloud call fails at the token
refresh with `invalid_grant`, which `window.note_lost_access` reads as a state, not an outage:
the Table box says the keys were changed and offers *Pair with a table…*. The administrator's
own access refused the same way (the app disconnected on dropbox.com after *Cut off a lost
PC…*, `core.DROPBOX_APPS_PAGE`) shows *Authorise again…* instead (`window.reauthorise`: both
keys from the *authorise* step, then the same closing).

## Trust in the folder: the seat, the keys, the signatures (2.0.0)

Dropbox gives every key holder the whole folder, so what a launcher believes of the folder
comes from signatures (`access/ed25519.py`, pure Python, the RFC 8032 vectors in
`tests/test_ed25519.py`). Each launcher makes a key pair with its identity
(`Settings.identity`: `sign_seed` in the vault, `sign_key` public). **Two Dropbox keys**: the
administrator's own `refresh_token` and the `hosts_refresh_token` made by a second
authorisation in the set-up wizard (`SetupWizard` pages *hosts_authorise*, *hosts_code*);
`core.server_environment` hands the hosts' one out, never the administrator's.

**`table.json` format 2** (`TableRecord`): the fields of format 1 plus `admin` {host_id, name,
key, since}, `revoked` (launcher ids struck off), `signed_since` (the first epoch whose copies
must be signed; a table upgraded from 1.x keeps its older copies accepted unsigned) and
`signature` over the canonical JSON of the rest (`sync.canonical`: sorted keys, no spaces).
`verified` checks the signature under the key the file names; `trusted_by(key)` is a host's
question, with the key it learned at pairing (`cloud.admin_key`). Only `write_table` with a
seed signs; hosts write the file no more (`window.settle_table`).

**The seat.** `settle_table` on the administrator's side creates the file with its seat
(`ensure_table(admin=…, seed=…)`), upgrades a format-1 file (`sync.take_seat` with the
record's next epoch), or, finding another key on the seat, asks and takes it. Every read of
the table (`window.checked` → `check_seat`) compares: the administrator whose key is no
longer on the seat revokes its own Dropbox token, forgets the table and says who took the seat
(`seat_lost`); a host whose file is no longer `trusted_by` its administrator's key shows "the
administrator's launcher changed, pair again" (`seat_changed`).

**`launchers.json`** (`read_launchers`, `add_launcher`): `{format: 1, entries: [...]}`, one
admission per launcher id, appended by the newcomer with a compare-and-swap. An entry is
vouched for when its signature verifies under its admitter's key and the admitter is the
administrator or a vouched-for entry (`known_launchers`, a chain bounded by `CHAIN_DEPTH`, a
loop ending at a visited id); a struck-off id vouches for nobody, so *Strike off*
(`window.strike_off`) re-admits the hosts it had let in under the administrator's own
signature, each still listed to strike on its own.

**Signed records and copies.** `HostRecord` carries `key` and a `signature` over the fields a
thief would want to write (id, name, epoch, since, address, version, key), not over the
heartbeat's; `claim` signs. The window shows *Join* only for a holder the table vouches for
(`holder_known`) and gives the administrator *Take the record back* otherwise. A snapshot
leaves the game unsigned and is signed by the launcher before the upload
(`sync.sign_snapshot`: a `signature.json` member over the hashes of `manifest.json` and
`kingmaker.db`, with the launcher's id and key), so the seed never leaves the launcher;
`newest_usable(trusted=known_launchers(...), signed_since=…)` skips a copy at or above
`signed_since` whose signer is not trusted, with a line in the log.

## The guides and the welcome (`launcher/wizard.py`)

One frame, `Wizard`: the window, Back / Next / Cancel, a page that scrolls when the screen is
short (`screen.Scrolled`), and a list of pages named `group/name` — the group says where the
texts live (`launcher.wizard.*`, `launcher.air.wizard.*`, `launcher.welcome.*`) and where the
picture is (`guide/`, `guide/air/`, none). A subclass draws each page in `render` and says in
`leaving` whether Next may go on, after doing what the page asked: a check, a save, or a
request whose answer moves on by itself. The two sets of pages, `DropboxPages` and `AirPages`,
are mixins: `SetupWizard` and `AirWizard` are one set each, and `WelcomeWizard` is built from
both plus its own pages.

**The welcome** (`WelcomeWizard`, 2.0.0): the first run. `Settings.welcomed` holds the
revision seen (`core.WELCOME_REVISION`); a fresh install has 0 and `window.run` opens the
welcome alone, the main window kept hidden until it closes (the wizard is made `transient`
only over a window on screen, since one kept over a hidden window is hidden with it); the
settings live in `saves\`, which an update and an uninstall that keeps the game both leave in
place, so those starts go straight to the main window. A file from before the field existed is taken
as set up already (`Settings.load` fills it in), and *Reset the setup…* in the Settings
reopens it after `Settings.reset_setup` forgot its answers (the role, the mode, the token, the
table; never the game folder's files, nor the language, the port or this PC's identity), the
main window hidden again. `Settings.role` keeps the first page's answer (`core.ROLES`), saved
as soon as that page is left; a file from before it takes the table's role, or the
administrator's. `Launcher.build` draws the window of that role: the administrator's with
where you play, the address box (online) and *Load a save file…*, the Table box hidden on this
computer only while there is no table (`place_table_box`); a host's with the Table box and
*Start* only, `paired` setting the mode from the table's address, and *Start* held back by
`gate_start` until the pairing. `plan` rebuilds the page list from the answers each time one changes, keeping the
current page in place. The language chooser sits on every page's title line (`header_extra`),
since whoever reads no English must be able to read the rest and must not go back for it: it
saves `settings.language` and redraws the page, and the main window rebuilds itself when the
welcome closes. No page of the welcome is numbered (`numbering` returns None; the titles
are bare, and `launcher.wizard.step` adds "Step n of total" only in the guides opened alone),
because nearly every answer changes how many pages follow. The pages: who you are (`who`; no
Skip, since it is the decision
the rest hangs on; closing the welcome's window (`close`) always closes the launcher
(`on_quit`, the main window never shown): before the first page's Next the welcome stays due
for the next start, after it `welcomed` is written as by Skip and the next start opens the
main window;
the administrator goes on to where you play; a host
goes to the pairing form and is done, the mode read off the address with
`core.mode_for_address`), where you play, online and without a table the address page (the On
Air pages follow for "guide me", a field here for "I have one", nothing for "later"), on the
network or online and without a table the others page (the Dropbox pages follow for "set up
Dropbox"), and the summary, which ends with where to change it all
(`launcher.welcome.done.change`). A table already in the settings skips the address and the others,
since both live in the folder. Finishing or skipping writes `welcomed`; the window then
reflects whatever was set (`Launcher.welcomed`: the mode, the token, the table, the boxes, and
the token published to the table's file when the administrator has both, rebuilt for the
role) and, at the first run or after a reset, comes on screen.

**Set up Dropbox…** (the administrator, once; *Let someone else host…* in the Table box, or the
welcome's others page): seven steps with a picture each from
`launcher/guide/` — a Dropbox account; *Create app* in the App Console with *Scoped access*
and *App folder*; the five permissions; the *App key* pasted in, with the table's name; the
authorisation page opened with the PKCE URL (`dropbox.authorize_url`, `token_access_type=
offline`, no redirect): Dropbox warns that the app has few users, asks to allow, and shows
the code; the code pasted back on its own step (`dropbox.exchange_code` → the refresh token,
`Client.account()` for the name, kept even if that lookup fails, since the code is spent);
done. For an app made before (another PC, a reinstall), *Connect to an existing app* on the
create step (`use_existing`) opens `APP_LIST` and switches the road to `EXISTING_STEPS`: the
`existing` page, with its picture of which app to click, goes in before the permissions, which
stay on the road (an app made and left before that step would pass the key and fail at the
first upload); Next from the create step again goes back
to a new app (`leaving_cloud`). `repage_cloud` swaps the page list keeping the current page,
through `cloud_pages` (the guide's own list, or the welcome's `plan`). The pictures are the owner's screenshots of the console, numbered where the order of
clicks matters. Each
administrator creates their own Dropbox app, so no table depends on the author's app or on
Dropbox's review of it.

**Set up a fixed address…** (whoever hosts, when the table plays online): seven steps with a picture
each from `launcher/guide/air/` — what the relay is and the site opened with `core.ON_AIR_PAGE`
(`https://on-air.nicegui.io/login`, which is where the site lives; `nicegui.io/on_air` has been
a 404 since 1.1.3 and was the old button's target); the login dialog, where On Air sends you to
GitHub; GitHub's sign-in, which is where the password is typed, so neither On Air nor this app
sees it; the table with no device in it and *+ ADD DEVICE*, which is what a new account really
meets; the dialog that hands out the token, which pressing that button opens by itself, with
the token pasted back — all `settings.token` ever is; the cog and its *New token*, for the day
the token is lost or the device was already there; done. That last step has a door of its own:
*New token…* in the address box opens `AirWizard(..., start="renew")` straight at it, and
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

**The Table box** (`window.refresh_cloud`): one line for where things
stand, then one row per action (`Launcher.action`: the button and, next to it, what it is for
and when). Which rows appear depends on the state — nothing set up (for the administrator "Only this
computer can start the game" and *Let someone else host…*, hidden on this computer only; for a
host "not paired yet" and *Pair with a table…*), the keys changed away (*Pair with a table…*,
*Forget*), hosting (*Pair a launcher…* for the administrator), somebody else hosting (*Join*,
the administrator's take-over), or ready (for the administrator *Pair a launcher…* and *Change
the keys…*, then *Forget the table*), each group under a small heading (`Launcher.group`) in
order of how often. There is no button to ask who is hosting:
`Launcher.watch_host` asks by itself 1.5 s after the window opens and then every
`WATCH_EVERY_MS` (a minute; `WATCH_HOSTED_MS`, 15 s, while someone else hosts, when somebody
waits for them to stop) while this launcher does not host, through `check_host(quiet=True)`.
A check is two calls: the record's download (`sync.download_if_there`, which reads "not found"
as no file instead of asking first) and the clock it is judged by; the table's file is a third,
which the 15-second checks make only once `TABLE_EVERY_S` (a minute) has passed, since what they
show needs only who hosts. Start, and every check while nobody hosts, read it afresh.
The quiet check has its own flag (`watching`), not `cloud_busy`, so a Start pressed meanwhile
is never ignored and its own answer wins; it rewrites the line under Start only while that line
already speaks of who hosts (`status_about_host`), and logs an outage once (`watch_error`). The
welcome did the explaining, so the rows say less than they did. The address box (*Your table's
address*, `refresh_air`) without a table shows one status line that follows the field — fixed
address or random — the guide's row and the field; with a table, one line, since the token is
not on this PC, and for the administrator *New token…*: renewing belongs with the token, and
only once there is a table. That row (`open_air_new`) opens the On Air wizard at its first
step when no token is known, at the renewal step otherwise.

**Pair with a table…** (`wizard.PairDialog`, the other hosts): the table's address, the pairing
code, a name for this PC → `core.pair` → `core.adopt_pairing`, which checks the table's folder
before keeping anything (above); the launcher's role becomes `host`, and the name typed is
what the other hosts read in `host.json`. The welcome's pairing page is the same form
(`PairForm`), with Next as its button. *Forget the table* clears it; an administrator is
also offered to revoke the credential at Dropbox (`Client.revoke`), after which every host must
pair again — the same as a rotation without a successor.

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
`whoami` proof and the launcher's probe of it, and the other routes of a real server started on a scratch
folder — including a code made through the local route and spent by `core.pair`, a second use
refused, three wrong codes killing the live one, the 1.x hand-out answering 410, and
`core.adopt_pairing` throwing away a credential that opens another table.
The two-launcher hand-over was driven by hand against the fake, with two launchers in two
processes: A hosts and uploads, B is refused, A stops, B starts with A's game, A is refused,
A forces the take-over and B stops. The hand-over is covered by `test_sync` with two
hosters on one fake: the ask lands in the holder's record, the holder's look uploads and
releases, the taker's wait ends there and the claim is free; a holder that never looks times
out and the forced claim still stands; a holder taken by force learns it at its next look.

## The hand-over (`sync.request_handover`, `Hoster.look`, `sync.wait_for_release`)

*Force take-over* lost the holder's last minutes: their next write hit a conflict and they
stopped without uploading. Now the administrator **asks**. `request_handover` reads the
record and, if a living host holds it, writes it back with `handover = {to_id, to_name,
asked_at}` on its rev (a conflict reads again). The holder's `Hoster.tick` begins with
`look`: one download of the record every `STATUS_EVERY` seconds. The record gone, or on
another host or epoch: `taken` (so a forced take-over is noticed without waiting for a write
to conflict). The record ours with `handover` set and not released: `hand_over`, which
uploads once more (`upload_once(force=True)`, the snapshot and the heartbeat), releases the
record, and tells the window through `on_handed(name)`; the window stops the server with
"You handed the game to…", and `Hoster.stop` uploads nothing more (`state.handed`). On the
asking side `window.hand_over_wait` runs on the Start thread: `wait_for_release` polls the
record every ten seconds up to `HANDOVER_WAIT_S` (120 s), with the status line counting; it
returns True once the record is released, stale, gone or someone else's, and the ordinary
`claim` follows; on timeout the person chooses, through `Launcher.choose`, to take it anyway
(`claim(force=True)`, the old path), keep waiting, or cancel. A holder on a version from
before the hand-over never reads `handover`; its next write conflicts, it stops as before,
and the taker's wait ends at the timeout with the forced claim offered. Because `table.json`
pins every host to one version, that case only arises for a table still on an old version.
