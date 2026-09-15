# assets/

Images the table uploads: nothing in here is versioned, and **no map image
is distributed with the app**.

- The **map image** goes here: a PNG or JPG of the hex map you play on (for
  the Kingmaker Adventure Path, the Stolen Lands map from your own copy of
  the book, or any hex map). Upload it from *Map → Grid calibration and
  background image* as an administrator, or copy the file into this folder
  and pick it from the same box; then align the grid to the printed hexes.
- `characters/` — portraits and tokens of the characters.
- `vehicles/` — portraits and tokens of the vehicles.
- `thumbnails/` — small copies the app makes on its own.

To keep the images elsewhere set `KINGMAKER_ASSETS_DIR` (see `.env.example`).
Only signed-in users can fetch anything from this folder.
