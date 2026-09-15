# Development log

One entry per version, written after the fact from the session notes, the docstrings and the
long water document. Each entry says what was tried, what broke, and what was learned. The
dry list of changes is in [`../CHANGELOG.md`](../CHANGELOG.md); how the app is built today is
in the [code manual](manual/README.md).

---

## 0.1.0 — 3 September 2026 · Founding

The app was born at the table, out of a spreadsheet that could not keep up. The Kingdom Turn
of Pathfinder 2e's Kingmaker has sixty activities, each with four outcomes, and the players
were re-reading the wiki at every roll. The first day produced the sheet, the ten steps of
kingdom creation, the turn with its phases and steps, the settlements with the Urban Grid, and
a hex map drawn as SVG over an uploaded image.

Three decisions from that first day survived every rewrite:

- **The data comes from the rules, never invented.** Activities, structures, feats and tables
  were transcribed from the Italian wiki into JSON, each file with its `_fonte`. What the rules
  do not say is marked `"fonte": "tavolo"` («table») and shown as such in the in-app Manual.
- **Effects are proposed and confirmed.** An activity computes its outcome and shows tickable
  rows; nothing is applied until someone clicks. The players wanted to argue about a result
  before it landed, and that turned out to be the invariant of the whole interface.
- **One Python process, NiceGUI, no separate frontend.** The author works in Python and has no
  Node on the machine; the interface is Python and the browser runs only the scripts that
  must follow the mouse.

What broke: the save was a single JSON file rewritten at every change, and two windows open
at once lost each other's edits. That was the first item on the next day's list.

## 0.2.0 — 5 September 2026 · Identity, GM screen, fog

The second session added the things that make it a table tool and not a personal notebook:
accounts with roles, the GM's private view, the fog of war, and publishing over the network.

Passwords are PBKDF2 with the standard library, 600,000 iterations, one salt per user; the
login page runs `verify` off the event loop because half a second of hashing must not freeze
the others. A non-existent user still hashes, so response times do not reveal who exists. The
throttle counts failures per name; counting per address came later, once On Air showed that
everybody arrives from the same relay.

The GM screen was designed around one rule: **a player never receives what they do not know.**
The filter sits in the server (`vista.py` then, `view.py` now), not in the CSS. Hidden features,
hidden roads, GM notes and the fog are all decided before the SVG is built, so a curious
player reading the page source finds nothing. «See as the players» builds the view of a fake
user in the GM's window — same code, other eyes — and caught two leaks in its first hour.

NiceGUI On Air taught the prefix lesson: the app is served under `/<name>/device-0/`, NiceGUI
adds the prefix to its own elements, and every address we write ourselves into the SVG needs
it added by hand. The redirect to `/login` had it added twice and looped; it was found only by
the one person who had never logged in before, which is the worst way to find a bug.

## 0.3.0 — 6 September 2026 · Characters, tokens, travel, time

Characters became rows of their own, with portraits and tokens like Roll20, linked to the
account that plays them and to the leadership roles they hold. Two roles of the same character
now count as one leader, as the rules intend.

**Travel** started as Dijkstra over the hex grid with the rules' costs: open 1, difficult 2,
greater difficult 3, roads improving by a grade, activities per day from the Speed of the
slowest, one pays the hex one enters. The ruler was the interesting part: the server sends the
whole cost field once, and the browser draws the arrow with no round trip while the mouse
moves. On release the server recomputes everything from the drawn path and keeps nothing of
the browser's count — a rule that never changed.

The **rendezvous** of a scattered party came out of a real evening: three characters in three
hexes, one target, and the question «where do we meet». The answer is a lexicographic minimum
over every reachable place: first make nobody later than they would be alone, then meet as
early as possible. It is exact, not heuristic — a few Dijkstras on a few hundred hexes.

**Time** got a calendar (Absalom Reckoning, months of different lengths, leap years) and a
clock that runs on the server so two windows never count different days. Journeys advance one
day at a time, and the Kingdom Turn falls at the end of the month, as the rules say, so a turn
lasts as long as the month.

What broke: the clock kept running after a restart and made three months pass while nobody
was watching. Now it always restarts stopped.

## 0.4.0 — 7 September 2026 · Vehicles, rivers, SQLite

Vehicles were transcribed from the rules catalogue (45 of them) and sorted by where they go —
land, water, air — because that is the only distinction travel really looks at. Where a page
gives no Speed in feet, the app asks instead of guessing.

**Water** entered the map as borders between hexes (water, ford, bridge) and as banks inside a
hex, drawn by joining two vertices. The first model of a bank was a group of sides: the
vertices touched by water, and the edge arcs between two touches. It looked right on every
river of the real map and was wrong in three ways that
[chapter 9 of the manual](manual/09-water-travel.md) measures.

The JSON save gave way to **SQLite**: the kingdom document in one row, hexes, users, characters,
vehicles, journeys and water in real tables, a timer writing at most every two seconds, and
differential writes so the journal is not rewritten at every click. The old JSON is still
imported once and left in place.

## 0.5.0 — 8 September 2026 · Performance, sharing, water vehicles

The day of measurements. The map was redrawn in every window at every change, including the
windows looking at another tab; the SVG ground layers were rebuilt every time; the map view
was built four times per redraw. The fixes are the refresh bus described in chapter 4 of the
manual: panels registered with the tab they belong to, redrawn only when that tab is in the
foreground, marked dirty otherwise; ground layers cached per window and keyed on the archive
revision.

Boats got routes along the drawn rivers, a current brush (click upstream, follow the river,
click downstream), lakes drawn by hand as a ring of vertices, and a «⛵ By river» alternative
next to the land plan. The **water chart** (export and import of the whole drawing as JSON,
with the grid calibration inside so a differently calibrated map is refused) and the
**assisted reading** of the water from the image (a proposal in orange, accepted or discarded)
arrived the same day.

Thumbnails fixed a real problem: a 2.2 MB token requested ten times while the map opened under
On Air never appeared. The thumbnail is 60 KB.

## 0.6.0 — 9 September 2026 · Faces, points, the water route

The section model was replaced by **faces**: the water lines plus the hex edge form a planar
drawing, and the sections are its faces. Two separate chords make three pieces, not four; a
triangle inside the hex is an island; twenty-four sections are representable. The travel
graph did not change a line — the set of sections was wrong, not the engine.

The important consequence: **section numbers are never saved.** A section is a question asked
of a point. Markers, vehicles and crossings store a point inside the hex, and the section is
derived from it every time; when the GM redraws the water, nobody jumps to the other bank.

Boats moved onto the **atom sides**: every drawable line is exactly a set of atom sides (four
for a chord, two for a spoke), the junctions are the nineteen points where lines meet, a piece
costs ¼ and an edge ½, double against the current. The number is not chosen; it comes out of
the geometry. Lakes became a triangular mesh of still water.

## 0.7.0 — 10 September 2026 · Boarding, self-crossing paths, the shared arrow

«Board» became a gesture made where one stands: a vehicle is placed in a hex, one boards from
the same piece, one lands ashore next to it. The transport tab went back to being the depot.
The ghost link — a character «on» a wagon three hexes away — disappeared with the dropdown
that allowed it.

The ruler learned to cross itself and pass a hex twice (a bridge downstream brings you back to
the other shore of the same hex), to distinguish «going back» from «closing a loop» by the one
exact criterion — re-entering the cell you just left — and to say **why** it stops: a red flash,
a vibration, a message, at most one every two and a half seconds. The arrow is shown live to
every window entitled to see it, in the colour of the person drawing it, and the red flash
reaches them too.

What broke: the browser and the server counted a step differently at an inner bridge, so the
dragged arrow stopped at the bridge and the rest appeared only on release. One `stepCost` used
by all four trades of the ruler fixed it.

## 0.8.0 — 11 September 2026 · The hex as 24 atoms

Three things the faces model could not do: put a bridge where the hand naturally puts it, make a
river that only touches the hex cost anything, and say «I am in that piece there». The answer
was to turn the model around: the hex is **already divided into 24 fixed pieces**, and a water
line does not create pieces, it closes passages between pieces that were always there.

The numbers are measured, not assumed (`prova_atomi.py`): 24 atoms, 36 borders all lying on
drawable lines, a clean crossing through exactly 4 atoms in all 15 directions. So ¼ per atom
gives the cost of the rules without calibrating anything, a detour around water pays for
itself, and over all 1,561 configurations of up to three lines a crossing costs 4 to 8 atoms or
is impossible — never less than the rules.

The travel node became `(col, row, gate)` with the entry side instead of the shore, because
entering and leaving by the two ends of the same shore means walking along the river, and the
old node could not say so. The dragged ruler received the rule instead of the graph — a 36-bit
mask per cut hex — and rebuilt the same layered Dijkstra in JavaScript, with the same tie-break,
verified by two benches loading the real script.

Markers were drawn per piece, sized by the piece, with a count instead of a face when several
share one.

## 0.8.1 — 12 September 2026 · Rounding, cleanup, the manual

Small numbers: half activities do not exist on the sheet, so server and browser
round the same way; a boat's plan sums the stretches per hex and rounds at the end. The
docstrings that told the story of every previous version were trimmed to the «why», and the
story moved into the water document. The code manual was started.

## 0.9.0 — 13 September 2026 · The manual, ctrl-select, the first security pass

The code manual reached eleven chapters, with figures generated by the app's own drawing
functions on the test scene and a screenshot of every tab. Ctrl+click on a badge builds a
group one person or vehicle at a time. Reconnoiter got its button.

The **cleanup review** (its list is in the changelog) closed thirty dead functions, merged the
three HTML badges into one (and found, doing it, a face with the On Air prefix added twice),
split the 9,800-line `hexmap.py` into a package of nine modules behind a facade, keyed every
cache on the archive revision, and moved the journal into its own table. The **first security
pass** added permission checks to the ruler events, escaped the JSON texts reaching `ui.html`,
throttled login by address, and made «Start over» empty every campaign table.

## 1.0.0 — 15 September 2026 · English, bilingual, public

The release for the world outside the table. The code had been written in Italian for a
group of Italian players; publishing it meant an English codebase, an interface in both
languages, English rule texts that are not translations, and a licence that respects Paizo's
terms.

**The rename** covered 25,500 lines: modules, identifiers, dictionary keys, JavaScript globals,
CSS classes, the SQL schema, the stored enum values, the tests, the tools, the docs. It was
done with a token-level renamer driven by a map of about three thousand rows, one module at a
time, leaves first, with the suite run after every module. It found two real bugs in
passing: a cosmetic rename shadowed `hexgrid.neighbours` inside a function, and `launch.py`
ignored its token argument. The storage rename is **schema 27**, with an automatic backup of
the save before migration and a fixture-driven test.

**i18n** moved about 1,100 literals into flat catalogs, `t("area.key")`. Two rules came out of
the first broken build: never call `t()` at import time, and never bind a local named `t`. A
checker enforces both. Texts sent to other windows — the trace titles, the plan labels — are
rendered in each recipient's language, and the ruler receives its label patterns in the
payload. The language is a property of the window, like the identity.

**English rule texts** were pulled from Archives of Nethys through its search endpoint —
structures, activities, feats, vehicles, kingdom tables — and stored per language with the
source URL. The structures' effects, which release 0.9 parsed from Italian prose at runtime,
became structured data with a golden test before the parser was deleted. Mechanics and texts
were split into separate files, so a language is a folder.

**The second security review** turned the audit's findings into tests: escaping everywhere a
user's text reaches markup (including inside the JavaScript ruler), permission re-checked by
every mutator so a spectator is read-only by construction, identity re-read when the archive
changes, throttling that works behind a relay, capped ruler payloads, the last administrator
protected from itself.

What was learned, in one line each:

- A rename is a refactor: run the tests after every module, never on the whole tree at once.
- A flat package of twenty-four modules hides its layers; one folder per layer (`geometry`,
  `storage`, `access`, `travel`, `ui/tabs`, `ui/hexmap`) makes the dependency graph visible in
  the tree itself, and absolute imports say where everything comes from.
- A string that will be shown to another window is not a string, it is a key.
- The data split must be idempotent or it must be run on a backup; ours was not, and the
  backup saved an afternoon.
- Docker is easy to write and hard to test on a machine without Docker; the README says so
  rather than pretending.
