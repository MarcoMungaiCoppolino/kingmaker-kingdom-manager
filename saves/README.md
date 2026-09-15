# saves/

This folder holds **your game**: it is created empty on the first start and
nothing in it is versioned.

- `kingmaker.db` — the whole campaign in one SQLite file: kingdom, hexes,
  accounts, characters, vehicles, journeys, water, who has seen what. Back it
  up by copying it while the app is closed (or use *Download the JSON save*
  in the Manual tab from an administrator account).
- `kingmaker.db.pre-v27.bak` — written automatically the first time a save
  made before release 1.0.0 is opened, right before it is migrated.
- `.storage_secret` — the key that signs the browser session cookies. Delete
  it and everyone has to sign in again; nothing else happens.
- `sessions/` — the browser sessions kept by NiceGUI.
- `regno.json` — only if you come from a version older than 0.4.0: the old
  JSON save, imported once into the database.

To keep the game elsewhere set `KINGMAKER_DATA_DIR` (see `.env.example`).
