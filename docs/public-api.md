# Public API

What Kingmaker Kingdom Manager promises not to break between versions of the same major
number. A change that breaks one of these things needs a MAJOR version; adding to them is
MINOR. Everything not listed here (Python modules and functions, catalog keys, page layout,
test hooks) is internal and may change in any release.

The project follows [Semantic Versioning](https://semver.org/). This list was first written for
2.1.0.

## Saved games

**The database file** (`saves/kingmaker.db`, or `$KINGMAKER_DATA_DIR/kingmaker.db`).
- A file written by an earlier version of the same major number opens, and is brought to
  today's format on open. Within a major number, tables, columns and kingdom-document keys
  are only added, never renamed or removed.
- Files from earlier major numbers open as far as the CHANGELOG says. Today that includes the
  Italian saves from before 1.0 (the oldest sample the tests keep is schema 26).
- A file written by a *newer* version is refused, untouched, with a message that names the
  version that wrote it (`NewerSaveError`; from the command line, exit code 3). This is the
  expected behaviour, not a break.
- The `meta` table holds `schema_version`, `app_history` (which versions opened the file),
  `sync_marks` (the cloud copy the file matches: `epoch`, `seq`, the document revision `krev`
  and, from 2.1.0, the campaign tables' counter `trev`), `tables_rev` and `forked_at`. Other
  `meta` keys are migration marks and internal.
- The kingdom document (`kingdoms.document`) is JSON. Its keys are listed by `new_kingdom()`
  in `kingmaker/state.py`, which is the reference for their defaults.

**Backups and bundles** (`.zip`): `manifest.json` (app, version, schema, kingdom, date),
`kingmaker.db`, `kingdom.json` and `assets/`. A bundle made by a version restores in every later
version of the same major number.

**Cloud snapshots** (`.zip`): `manifest.json` with `epoch`, `seq` and the hashes of the images,
and `kingmaker.db`, signed from 2.0.0 (`signature.json`).

## The table in the cloud

The files a table keeps in its Dropbox folder. Launchers of the same major number read each
other's files; a launcher older than the table's version is asked to update before it hosts.
- `table.json`: the table's name, id, version pin and On Air token (format 1), and from 2.0.0
  the administrator's seat and key, signed (format 2).
- `host.json`: who holds the game right now, with heartbeat and address, signed.
- `launchers.json`: the launchers let in, each vouched for by the launcher that admitted it.
- `.clock`: written only to read the server's time.
- `recent/` and `daily/`: the copies, named `save-e<epoch>-s<seq>.zip` and
  `save-<date>.zip`; `assets/`: the images, by content hash.

## The launcher and the server

The launcher starts the game as a child process; they talk through these.
- **Lines on standard output:** `KM ready <url>`, `KM lan <url>`, `KM admin-password <pw>`, and
  NiceGUI's own "NiceGUI is on air at <url>".
- **Local routes** (answer only to 127.0.0.1 with the right secret): `POST /_launcher/shutdown`,
  `GET /_launcher/status` (`rev`, `kingdom`, `synced`), `POST /_launcher/snapshot` (with the
  `X-Kingmaker-Rev` header), `POST /_launcher/synced`, `POST /_launcher/pairing`.
- **Public routes:** `GET /_launcher/whoami` (proves the server with its secret),
  `POST /_launcher/pair` (pairing by code), `POST /_launcher/credential` (410 Gone in 2.x; it
  goes away in 3.0.0, as announced in the 2.0.0 CHANGELOG).
- **Environment set by the launcher:** `KINGMAKER_LAUNCHER_SECRET`, `KINGMAKER_LAUNCHER_ID`,
  `KINGMAKER_LAUNCHER_SIGN`, `KINGMAKER_SYNC_CREDENTIAL`, `KINGMAKER_ON_AIR_TOKEN`,
  `KINGMAKER_ON_AIR_ANONYMOUS`.
- **`launcher.json`** in the game folder: the launcher's settings (`mode`, `port`, `language`,
  `token`, `open_browser`, `firewall_shown`, `check_updates`, `cloud`, `host_id`,
  `host_name`, `vault`, `welcomed`, `role`). Unknown keys are ignored, missing ones get their
  default.

## Running the app

- **Command line:** `--launcher`, `--serve`, `--lan`, `--online [TOKEN]`, `--port N`,
  `--no-browser`. Exit code 3 means the save was written by a newer version.
- **Environment for whoever runs the server by hand** (Docker included):
  `KINGMAKER_DATA_DIR`, `KINGMAKER_ASSETS_DIR`, `KINGMAKER_VAULT_DIR`, `KINGMAKER_HOST`,
  `KINGMAKER_PORT`, `KINGMAKER_LANG`, `KINGMAKER_HTTPS`, `KINGMAKER_TRUST_PROXY`,
  `KINGMAKER_STORAGE_SECRET`, `KINGMAKER_LOG`. The `KINGMAKER_DROPBOX_*` variables are test hooks
  and internal.

## Releases

Every release on GitHub carries the Windows installer, the Linux tarball, `SHA256SUMS` and
`SHA256SUMS.sig`, the owner's Ed25519 signature of the sums. The launcher refuses an installer
the signature does not cover.

## Files the app reads

- **The water chart** (JSON, from the map's water tools): ours, and promised like a save.
- **Imports of other programs' files** (Pathbuilder 2e and Foundry VTT exports, planned for
  2.8.0 and 2.9.0): theirs. This document will record which export versions were tested; their
  format is not ours to promise.
