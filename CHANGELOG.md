# Changelog

All notable changes to Kingmaker Kingdom Manager are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The narrative behind each version — what was tried,
what broke, what was learned — is in [docs/devlog.md](docs/devlog.md).

The versions before 1.0.0 were never tagged: the app was played from a working copy and the
numbers below were assigned afterwards, one per day of development, from the session history.

## [1.3.0] — 2026-10-06

The cloud stops lying, and the table gets a file of its own: one version for every host, the
On Air token read from the folder instead of copied to every PC, and a check that the table's
address really answers from the host.

### Added
- **The table's file, `table.json`.** Created in the cloud folder by the first launcher of this
  version that hosts; it names the table, pins the version the table plays on, and holds the
  On Air token. Any member can write it, so the launcher's manners (the administrator changes
  the version and the token) are a convention, which the manual says.
- **One version for every host.** To host, the launcher's version must equal the table's,
  exactly: the same save format has carried different rules, and two hosts on different
  versions played different games on the same file. A launcher on another version is refused
  before anything is claimed and offered *Install {version}*, which fetches that release from
  GitHub (Windows: the installer runs; Linux: the release page). The administrator on a newer
  version is asked whether to move the table to it; on an older one, the move down happens
  only after the cloud's newest copy proved readable by it. "Hosted by X" now says the
  version, and marks a launcher too old to know the table's.
- **The On Air token lives in the table's folder.** Every host reads it at Start and hands it
  to the server for that run; no copy is kept on a host's disk. At the first start after the
  upgrade the administrator's launcher moves its token into the file and forgets it locally;
  a GM's launcher forgets its copy once the file has one. *Lost the token?* now writes the new
  token into the folder as well, so the other hosts get it at their next Start with nothing to
  do — before, every other host kept a dead token and started at a random address. The launcher
  shows "from the table's folder" in place of the field, and only the administrator sees the
  renewal door.
- **The address check.** Once the server is on air, the launcher asks the table's public
  address who answers there (`/_launcher/whoami`, a proof only this start's secret can make):
  "the table's address answers from this PC", or a warning that another program holds it. A
  refused token (the relay handed out an anonymous device) is named for what it is. When
  nobody hosts, *Who is hosting?* also probes the address: something of ours answering there
  means somebody else holds the token.
- **Two copies of the game: the launcher asks.** When the cloud has a newer copy but this PC's
  copy changed since it last matched the cloud (an evening hosted without the cloud, a server
  that died before its last upload), a dialog asks which one is the game: load the cloud's,
  yours kept next to it as `.bak`, or keep yours and upload it as the newest. Before, the
  cloud's copy replaced yours with one line in the log. The save now records the document's
  revision with the marks of the copy it matches (`meta.sync_marks.krev`), which is how the
  launcher tells "behind" from "diverged".
- **A living record with this launcher's identity: the launcher asks.** A game folder copied
  to another PC carries the same identity, and the copy used to take the game from a host
  that was still playing, without a word.
- **Hosting without the cloud says what it is.** The offer names the fork, the server starts
  with no token (a random address, never the table's) and with no credential to hand out, the
  Cloud box says so while it runs, and the day is remembered for the next cloud start's
  question.

### Fixed
- **An older launcher could roll the whole table back.** A copy written by a newer version of
  the app was skipped for the next readable one, which was then loaded and uploaded as the
  newest. The pull now stops there, loads nothing, says which version wrote the copy and
  offers the Versions window.
- **A host with nothing new to say looked dead after three quiet minutes.** Dropbox keeps an
  upload of identical bytes as the same revision, so the heartbeat did not move the record's
  time; another Start could then take the game from a table that was only talking. Every
  heartbeat now changes the record (`beat`).
- **Images from the cloud were written wherever the manifest said.** A path that leaves the
  images folder, a file whose bytes are not the hash it is named after, or a file that is not
  an image is now refused and noted in the log, as the zip restore and the uploads already
  did. A copy whose epoch no host ever had is ignored too.
- **The first-start password reached the launcher's log pane** through the server's console
  block; it is no longer printed under the launcher, and any `password:` line is masked.
- **The launcher's settings are written whole**, through a sibling file moved into place, and
  on Linux readable by their owner only; a crash half-way used to leave the credential gone.
- **Stop asks Dropbox three times to release the record** before giving up quietly.

## [1.2.1] — 2026-10-06

The save knows where it has been, and a newer one is never opened by an older app.

### Added
- **The save records the versions of the app that opened it.** `meta.app_history` lists them
  oldest first, each with the save format it found and the date; a new save starts with the
  version that created it. The format number (the schema) still decides how a file is read.
  The list is for bug reports and for comparing hosts in the cloud. Saves written before this
  version start their list at the first version that opens them.
- `tests/fixtures/v29.db`, a save of today's format built from the test scene, and
  `tests/test_save_formats.py`, which opens a save of every format the app has shipped.

### Fixed
- **A save from a newer version was opened anyway at start.** Only *Load a save* and the cloud
  checked the format; a normal start opened the file, stamped it with the older format number
  and kept writing to it. The launcher's warning before installing an older version said such a
  save would be refused, and it was not. Now the server refuses it before writing anything,
  exits with code 3, and says in the launcher's log which version wrote it.
- **Loading a save from before 1.0.0** with *Load a save* stopped with a database error instead
  of converting it. The check read the format number in English column names, which a save of
  that age doesn't have.
- **The launcher went deaf when the Versions window was closed before GitHub answered.** The
  list arrived for a window that no longer existed, the error stopped the loop that reads the
  server's output, and from then on the status line never changed. The late answer is now
  dropped, and no single event can stop that loop any more.

## [1.2.0] — 2026-10-06

The kingdom rules, checked against the book: Fame and Infamy spent, the kingdom feats and the
vacant roles applied, the structures' bonuses in the rolls, the level-up choices, the activity
limits, and the data and texts audited against Archives of Nethys.

### Added
- **Spending Fame or Infamy.** The points were earned and then lost at the end of each turn,
  with nothing to spend them on. Now they can be spent the two ways the rules give:
  - **1 point rerolls a Kingdom check.** The activities, the hex activities, Build a Structure and
    the sheet's rolls wait on their result screen while you have points: keep the result, or
    reroll it once and keep the second. The other windows see both rolls.
  - **All the points stave off Anarchy or a Ruin penalty.** When Unrest reaches Anarchy, or a
    Ruin crosses its threshold, the app asks whether to spend them. Unrest then stops 1 below
    Anarchy, or the Ruin stops at its threshold with the penalty it had.
- **Famous and infamous structures move the points.** Building a structure of the kingdom's kind
  gives 1 point, and one of the opposite kind takes 1 away. *Place without a check* moves nothing.
- **Kingdom feats now do what they say.** Before, only Endure Anarchy's threshold and Fortified
  Fiefs' bonus to Fortify Hex were applied; every other feat was just a tick on the sheet. Now
  each one works:
  - **Bonuses:** Insider Trading (also +1 Resource Die each turn), Practical Magic (also Magic in
    place of Engineering, and Hire Adventurers for 1 RP), Civil Service, Inspiring Entertainment,
    Free and Fair (with its reroll for 2 RP), Fortified Fiefs on the walls and military buildings;
  - **On the result:** Pull Together, Fame and Fortune, Focused Attention's bonus (+3 with
    Cooperative Leadership, and its 11th-level degrees);
  - **Other:**
    - Kingdom Assurance, with a button that takes 10 + proficiency;
    - Muddle Through on the Ruin thresholds;
    - Endure Anarchy's extra −1 Unrest;
    - Quality of Life's extra Luxury;
    - Crush Dissent and Liquidate Resources, offered when they can be used;
    - Quick Recovery, Fortified Fiefs and Crush Dissent on event checks, through a new choice
      in the sheet's roll dialog.

  The feats that ask for a choice (Civil Service's role, Kingdom Assurance's skills, Muddle
  Through's Ruins) get it under the feats list.
- **Vacant leadership roles have their penalties.** Only the Ruler's +2 to the Control DC was
  applied. Now:
  - the Ruler also gives −1 to every check, and a button in Upkeep rolls its 1d4 Unrest;
  - the Counselor, Emissary, Treasurer and Viceroy give −1 to their ability's checks;
  - the General and Magister give −4 to Army activities, the Warden −4 to Region activities.
- **Bonuses stack by the rules.** Of each type (status, circumstance, item) only the best bonus
  and the worst penalty count. For example, Expansion Expert's +2 no longer adds to another
  circumstance bonus.
- **Every milestone is awarded however it happens:**
  - a Landmark or Refuge marked on a hex already claimed;
  - a hex claimed from the hex editor;
  - a settlement's type set by hand.

  The first Diplomatic Relation and Trade Agreement were never awarded. They now come from Send
  Diplomatic Envoy's and Establish Trade Agreement's successes.
- **Level-up choices.** Raising the kingdom's level used to add only the level. A dialog now
  asks for what the new level grants, and the Event phase keeps a button while a choice is left:
  - ability boosts at 5th, 10th, 15th and 20th level;
  - a skill increase at every odd level from 3rd (master from 7th, legendary from 15th);
  - Ruin Resistance at 5th, 8th, 11th, 14th, 17th and 20th level;
  - Civic Planning (12th) and Envy of the World (20th) are applied by themselves.
- **Structures that raise storage or lower Consumption.**
  - Each Granary, Lumberyard, Foundry, Stonemason and Secure Warehouse raises its commodity's
    storage by 1.
  - A Stockyard, a Sewer System and a Mill (with a water border) each lower their settlement's
    Consumption by 1.
  - Each settlement has an input for any other Consumption adjustment.
- **Consumption paid in part.** Food pays what it can; the rest costs 5 RP per point or 1d4
  Unrest. The step shows what is still due.
- **Effects counted per unit.** "1 per trade agreement", "2 per point spent" and "1 RP per hex"
  get a count on the outcome screen. RP owed "at the start of the next turn" (Request Foreign
  Aid, Manage Trade Agreements) arrive with the next Resource Dice.

### Fixed
- **The header showed another window's disguise.** When an administrator wore another account,
  the header's "looking as" line was read from the session of whoever had just acted, not from
  the window being drawn. So after one player's click, another player's header could show that
  player's disguise, or none. Each window now records its own when its page is built.
- **The windows test could hang at exit.** A redraw asked for the session of a window that had
  just closed (the header, above); the exception skipped the test's teardown, and the windows left
  open kept the process alive. The test now closes every window whatever happens, says where it
  got stuck if it ever does, and checks the closed-window case on every run. Fame and feat offers
  are no longer shown on a window that is closing.
- **The structures' item bonuses never reached the rolls.** The Inn's +1 to Hire Adventurers,
  and every other structure's bonus, was only text. They now count in the check they help and
  show in its breakdown before the roll:
  - the capital's structures help everywhere, another settlement's only in its influence;
  - identical structures in one settlement add up to its maximum item bonus, and different
    ones do not.

  For activities not on the map, an *Attempted in* choice appears when a settlement other than
  the capital would help.
- **Create a Masterpiece.**
  - The extra point of a critical success now arrives at the start of the next turn; it used to
    be added at once, and lost with the turn.
  - On a critical failure, the 1d4 Unrest is ticked only when there is no point to lose.
- **The DC typed in an activity's dialog was ignored**: the roll used the default DC.
- **The activity limits applied only in the Kingdom Turn tab.** On the map and in the city you
  could claim, build roads or build structures past the limits, and during Anarchy. Now the
  buttons wait and say why:
  - 3 Region activities a turn, and Claim Hex once a turn (twice from 4th level, three times
    from 9th);
  - one Civic activity per settlement;
  - nothing but Quell Unrest in Anarchy.
- **Claim Hex's critical outcomes.** A critical success allows one more Region activity; a
  critical failure gives −1 to Stability checks until the end of the next turn.
- **Smaller rules:**
  - a Ruin already at 0 that would go lower gets its DC 16 flat check to lower the penalty;
  - Quell Unrest can't use the skill it used last turn;
  - a hex lost and claimed again gives no XP;
  - the creation's two final boosts must go to different abilities.
- **Hard-coded Italian in the Ruin penalty's name.** It said "(Oggetto)" in English windows too.
- **The Monument showed an item bonus it does not have**: "+1 a Fare il Raccolto" in Italian. In
  English, its effect was shown as an item bonus.
- **The Turn tab broke once the Leadership activities were used up.** It looked up a step called
  "government" that does not exist, so the card meant to say why crashed instead. The hints of
  the Leadership, Region and Civic steps were never shown, for the same reason.
- **The clock's end of the month did not start the new turn.** The permission check found no
  account in the timer and refused in silence; the turn, the Fame and the activities stayed
  where they were.
- **Resource Dice.** Rolled from the sheet, the bonus dice were not used up, so they counted again
  every turn. The penalty dice were never used up from either button.
- **Fame above its maximum.** The quick adjustment and the sheet now stop at it.
- **Unrest typed on the sheet** now offers the Fame stave-off too, like the quick adjustments.
- **A Ruin threshold of 0** typed on the sheet could freeze the app at the next Ruin change. The
  threshold is now at least 1.
- **Structure data, checked against Archives of Nethys:**
  - the Sacred Grove took 11 lots, so it could never be built: it takes 1;
  - the Occult Shop cost 68 RP instead of 38, and the Printing House 14 Lumber instead of 12;
  - the Arcanist's Tower cost Stone instead of Ore;
  - the Bridge and the Watchtower charged Lumber **and** Stone: they cost one or the other;
  - the walls' upgrade went from stone to wood instead of from wood to stone;
  - the Barracks and the Magical Streetlamps proposed no Unrest or Crime reduction once built;
  - the Dive Tavern and the University had the wrong traits. The University counted as
    infamous, so an Infamy kingdom gained a point building it instead of losing one;
  - the "Building" and "Edifice" trait names were swapped.
  - A critical success on Build a Structure gives back half the commodities only within the
    storage limit.
- **Activity data:**
  - Capital Investment's critical failure asked for a Ruin of your choice instead of Crime;
  - Abandon Hex's Bandit Activity came in the Activity phase instead of the next Event phase;
  - Send Diplomatic Envoy's milestone sentence sat in the critical failure;
  - the Recover Army table showed raw markup;
  - three Italian activities had the wrong traits.
- **Texts:**
  - effect labels said "PR" and "PE" in English;
  - Italian left in the English interface: the map's compass directions, "Terra", "Segreto",
    "Scoperti/Coperti" in the journal, the clock speeds, "Ritratto", "Immagine";
  - Italian accents written as apostrophes ("e'", "piu'", "attivita'") in about 140 places;
  - Italian Luxury Store and Magic Shop effects were empty;
  - several Italian typos and missing apostrophes;
  - four Italian vehicle prices and rarities were swapped between pairs;
  - the Flying Cauldron moved on land;
  - the English activities lacked 28 costs and requirements the Italian ones had;
  - English plurals ("day", "days", "hexes") inside Italian sentences;
  - the city's "Espandi" button and border labels, and the launcher's log, were in one language
    only;
  - several English and Italian typos, and differences between the two languages in the vehicles.

## [1.1.7] — 2026-10-06

The app on smaller screens.

### Fixed
- **The app on smaller screens.** On a smaller screen, or in a narrower window, the tabs ran
  off the right edge or squeezed a column into an unreadable strip: the Kingdom sheet's skills
  and abilities, the Kingdom Turn's activities, the city, the map's side panel. The app had no
  rule for narrow windows at all. Now:
  - below 900 px the side-by-side columns of a tab stack at full width;
  - the skills take as many columns as their panel has room for;
  - the ability and Ruin rows go to two lines when the column is narrow;
  - in a very narrow window the dialogs fit it;
  - the tab bars show arrows when their tabs do not fit.

  All of it is in the stylesheet: no element added, nothing that runs on a resize, no second
  layout to draw or send, and the text keeps its size.
- **The activity cards of the Kingdom Turn ran out of their step**, on wide screens too. Each
  step's row of cards had no width of its own: inside its panel it took the width of its
  texts. In English that meant one card per line; in Italian, whose texts are longer, the row
  came out wider than the panel and the last cards stuck out over the journal. The row now
  takes the full width of its step and wraps there, and nothing inside a panel can be wider
  than the panel any more.

  Checked on every tab, in Italian, with every collapsible section opened, at window widths
  from 1775 down to 390 px: nothing sticks out of the screen or of its panel.
- The "Release" runs started by hand on the Actions page now show the version they build,
  not just "Release".

## [1.1.6] — 2026-10-05

Farmland by the book, and every roll seen by the whole table.

### Added
- **Everybody at the table sees the rolls.** When someone rolls, the result screen opens
  read-only in every other open window, with the name of whoever rolled. That covers the
  kingdom-turn activities, the skill checks of the sheet, the hex activities and building a
  structure. It also covers the plain dice: Resource Dice (sheet, turn, activity effects), the
  random-event check, the flat check for losing a hex, the 1d10 of Ruin points, the 1d4 of
  Unrest for unpaid Consumption, and the d6 of founding a settlement, now on the check's own
  screen. Each window reads it in its own language. The effects to apply stay with whoever
  rolled. A roll on a hex a player cannot see is not shown to that player.

### Changed
- **Establish Farmland asks for what the rules ask**: a hex in a settlement's influence (a
  village influences only its own hex, a town the adjacent ones too), mainly plains or hills.
  Elsewhere the button is disabled and says why, and the action refuses even when triggered
  from the browser console. Ticking Farmland by hand stays possible, for the GM.
- The cost and DC of Establish Farmland follow the hex's main terrain, the first listed. A
  plains hex with some hills used to be charged as hills (2 RP, DC + 5) because "hills"
  appeared anywhere in its list; it is now attempted as plains.
- **A critical success on Establish Farmland gives two adjacent hexes**, as the rules say. The
  app asks which adjacent hex gets the second, among those that qualify: claimed, in influence,
  no settlement or Farmland yet, plains (or hills, for an attempt in hills).
- "Fattorie" in the Italian Consumption breakdown is now "terreni agricoli", the word the rest
  of the app uses ("farms" became "farmland" in English).

### Fixed
- **Farmland that does not reduce Consumption now says so.** A Farmland hex next to a village
  read as "farmland 0", which looked like a bug, though the count followed the rules. The
  Consumption in the turn, the City tab and the sheet now adds how much Farmland lies outside
  every settlement's influence, and the hex panel notes it next to the box.
- The turn step and the header no longer show stale figures to whoever edits a hex. After
  ticking Farmland or changing a hex's status, the Consumption in the Turn tab and the kingdom
  size in the header stayed old until a reload, in the window that made the change only.
- The 1d4 of Unrest for unpaid Consumption showed nothing, not even to whoever rolled; it went
  only into the journal. It now has its screen like every other roll.
- The journal line of Resource Dice rolled by an activity's effect was always in Italian
  ("PR spesi/guadagnati"), whatever the language: a local variable in `apply_effect` hid the
  translation function. It now speaks the roller's language.
- The Unrest step of the Kingdom Turn listed the overcrowded settlements in Italian
  ("Sovrappopolati", "Residenziali") whatever the language; it now reads the window's.
- Settlement names were written into that chip, and into the City tab's overcrowded chip, as
  typed: a name containing HTML would have been run as HTML in every window showing it. They
  are now escaped, like every other name in the app.
- `tests/test_windows.py` could hang after passing, waiting forever at exit (about one run in
  three once rolls reached every window). A NiceGUI window's outbox loop could swallow the
  cancellation at shutdown, through `asyncio.wait_for` on Python 3.10. The simulation tests
  now close their windows first, so the loops end on their own.

## [1.1.5] — 2026-10-05

The launcher on a laptop's screen, every window of it.

### Fixed
- **The launcher on a laptop's screen.** The set-up wizards asked for more height than a
  small screen has, and their *Next* went below its bottom edge: step 4 of *Set up Dropbox…*
  (the App key) and step 6 of *Set up On Air…* (a new token) could not be passed. The main
  window had the same problem, with the log open or in online mode: the links, the log and
  on the smallest screens *Start* were out of reach. Now every launcher window fits in the
  screen less its taskbar. The content scrolls when it has to, with the wheel or by tabbing
  onto a control. The buttons that close a dialog stay pinned at the bottom. The wizards'
  pictures shrink to the room there is before anything needs to scroll.
- The list of versions in *Settings* has a scroll bar.

## [1.1.4] — 2026-09-20

The Linux build tried on a system with nothing on it, and the road to an On Air token walked
with the reader.

### Added
- **Set it up step by step…**, next to the On Air steps: the token, guided the way Dropbox
  already was. Seven steps with a picture of each screen — the On Air site, the login dialog
  it opens, GitHub's sign-in (which is where the password is typed, so that neither On Air nor
  this app ever sees it), the empty table with *+ ADD DEVICE* that a new account really meets,
  the dialog that hands out the token the moment that button is pressed, the token pasted
  back, and last the cog with its *New token*, for the day the token is lost — and the wizard
  saves the token itself. It asks nothing of the network: whether the token is good is
  answered by the first Start, as before.
- *Lost the token?*, the third button of the On Air box, opens the guide at that last step
  and nowhere else. It has to: the step before it is the one that asks for the token, so
  whoever has lost theirs could not have walked there from the beginning — the guide to
  making a new token was locked behind having one. From that step *Paste the new token…*
  goes to the field, and the closing step claims a token was saved only when one was.
- The guided part is the part nobody had written down. The old three lines said to press a
  button and "copy the token the page shows you", which is not what the page does: it shows a
  table with a cog on it, and a new account does not even have the device that cog belongs to.
  The wizard walks the one road a new account has — add the device, take the token it hands
  out — and says the two things that bite: that the token is shown once and never again, and
  that making another retires the one before. The cog and its *New token* come last, where
  they are needed: not on the way in, but the day a token is lost or a device was already
  there.

### Changed
- The two ways to a token — the wizard and *Get a token*, which opens the site — now sit
  together directly under the step that asks for them. *Get a token* used to hang at the far
  end of the box, after the field, three lines below the step that names it.

### Fixed
- *Get a token* opened `https://nicegui.io/on_air`, which answers 404: the On Air site lives
  at `https://on-air.nicegui.io/login`. The same dead address was printed by `--online` when
  it finds a token in the environment, and stood in the docstring of `main.start`.
- The launcher window could not open from the Linux tarball on a bare Ubuntu 22.04: the
  bundled Tcl/Tk asks for `libXss.so.1` and `ldd` leaves it unresolved there, because the
  X screensaver library comes with a desktop and a server, a container or WSL has no reason
  to carry it. Found by running the 1.1.3 tarball in a fresh WSL Ubuntu 22.04 — glibc 2.35,
  the oldest system the build supports. `packaging/linux/INSTALL.txt` and both READMEs now
  name the one package to install; every other library the tarball needs resolves on its own.

## [1.1.3] — 2026-09-20

What the app tells the world about the people at the table, and the papers that say so.

### Changed
- The three typefaces of the interface (Cinzel, IBM Plex Sans, Press Start 2P) are served by
  the app itself, from `kingmaker/ui/static/fonts/`, under their SIL Open Font License. They
  used to be loaded from Google Fonts by every player's browser, which handed Google the
  player's address on every page — a request nobody at the table had chosen, and one the
  host answered for under the GDPR. A player's page now talks to the host and to nobody
  else; LAN and offline tables get the right faces too. `test_security.py` checks that the
  stylesheet names no outside host and that every font it names is shipped.
- The launcher's check for a newer release on GitHub has a switch, *Settings → Ask GitHub for
  a newer version at start*, on by default; *Versions on GitHub…* still asks when pressed.
- The installed app ships `THIRD_PARTY_LICENSES.txt` next to the program: the licences of
  every Python package frozen into it, of the browser libraries and fonts NiceGUI serves, of
  Python and Tcl/Tk, of PyInstaller's bootloader and of the typefaces, written at build time
  by `packaging/third_party.py` from the build environment.

### Added
- `PRIVACY.md` (and `PRIVACY.it.md`): what the app stores, what leaves the host's computer in
  each way of playing and to whom — the On Air relay's operator, the Dropbox folder and the
  host record with the machine's username, the GitHub check — who is responsible for the
  players' data, how to delete, and where the licences are. The same notice, shorter, is in
  the app under *Manual → Privacy & licences*, readable by every player.
- `SECURITY.md`: what the app protects and what it does not, and which version is supported.
- The README and the user guide name the relay's operator, say that the cloud record carries
  the host's username and computer name and that hosting GMs hold the administrator's
  Dropbox credential, and point to the privacy notice and the licences file.

## [1.1.2] — 2026-09-17

The evening the whole table connected, and what it took to make eight windows cheap.

### Fixed
- With a full table connected — eight browser windows — every dice roll took two to four
  seconds. A roll redrew the whole interface in every window, whatever tab each had in front:
  with eight windows on the Turn tab that was 4 s of server time and 1.9 MB through the relay
  per roll, measured on a copy of the evening's database. A roll now redraws the journal and
  the fame line only (30 ms, 200 KB), and a full refresh redoes each shared panel only in the
  windows that have its tab open, once per action however many times it is asked: 0.9 s and
  1.3 MB with eight windows on the Turn tab (from 4.2 s and 1.9 MB), 1.0 s with the tabs
  mixed (from 5.7 s). The windows on other tabs catch up when they come back to the tab.
- The rebuilds are staged: once the action's handler is over, a task redoes one window per
  turn of the event loop, the actor's window first, then the windows on the map, then the
  rest. The actor sees the result at once and other players' clicks are served in between;
  a second action arriving meanwhile leaves the windows not yet redone to its own batch, so
  each is rebuilt once, with the newest state. A full refresh with eight windows on the Turn
  tab is 0.34 s of server time in total with no pause longer than 0.1 s, and 1 MB.
- A quick adjustment and the costs and effects of an activity redraw only the panels that
  show the figures they changed (`theme.PANELS_BY_STAT`): a +1 to the RP with eight windows
  costs 0.14 s and 250 KB instead of a full refresh. A new test, `tests/test_windows.py`,
  builds eight real windows, plays sixty random changes from random windows and compares
  every panel in front with a fresh render of itself, so a panel left out of the list fails
  the suite instead of going stale at the table.
- Whether a shared panel is in front is decided per copy, from the tab it sits in: the quick
  adjustments in the City tab were left stale by the first version of the fix.
- A panel whose inputs have not moved is not rebuilt: the six blocks of the Kingdom sheet and
  the quick adjustments declare what they read, and the bus keeps a fingerprint per copy. A
  full refresh with eight windows on the Kingdom sheet went from 1.45 s to 0.34 s of server
  time, with no pause over 0.1 s.
- Applying an activity's costs or effects that change nothing no longer redraws anything.
- The value typed in an effect row of the outcome dialog was ignored: the row kept it under
  the wrong key and applied the printed value instead.
- Boarding, landing, placing a marker or a vehicle, sending a vehicle back to the shed,
  taking someone off the map and cancelling a journey redrew the whole interface in every
  window. They now redraw the panels that show positions — the map, the portraits, the Travel
  box, the hex panel, the Party tab, the stable, the journeys and the journal — and nothing
  else; the window that acted draws its map at once instead of at the next tick of its timer.
  A boarding with eight windows, five on the map, went from 983 KB through the relay to 92 KB.

### Changed
- The Turn tab is lighter: an activity card is one element, clickable as a whole (the dice is
  drawn in it, the requirements are the browser's own tooltip), the journal is one block, and
  the quick adjustments and the journal sit beside the turn column instead of inside it, so
  redoing one does not redo the others. From 1,860 elements per window to 300.
- The quick adjustments are one element too — the same rows, the minus and plus drawn as
  icons — and so is each stat box of the header, whose tooltip is the browser's own. The
  live part of the upkeep and event steps is a panel of its own, so a figure that changed
  redoes the steps and not the column of activity cards.
- The Kingdom sheet's skills, leadership roles and feats are one element each. The
  proficiency and the character of a role are native drop-downs in the theme's colours, the
  NPC name a plain field saved when you leave it, the three ticks of a role and the tick of a
  feat icons that toggle on a click anywhere on the row; the feats are grouped under the level
  they need, the ones above the kingdom's level dimmed as before. Descriptions and hints are
  the browser's own tooltips. Same rules, same setters underneath.
- The Kingdom sheet's two columns are split three to two instead of a fixed 520 px on the
  right: the resources, the roles and the feats have the room they need, the skills lose
  nothing.
- The map is drawn in two layers. The ground — fills, fog, water, icons and names — sits in an
  element of its own under the image's SVG, which keeps what moves: markers, journeys, the
  chosen hex, a water proposal. Each layer is sent only when it changed, so a moved marker
  costs a window a couple of KB instead of the whole map (93 KB). The ruler, the other
  players' arrows and the water tools keep drawing where they did, above the markers. One
  visible difference: a journey's arrow now passes over a hex's icons and name rather than
  under them.
- The hex outlines are relative commands on whole pixels: the grid weighs a fifth less and
  two neighbours share an edge to the pixel.

## [1.1.1] — 2026-09-16

The first days with the launcher at the table: three things it showed.

### Fixed
- A boat taken back to the depot left its passengers on the water — the boat's junction, or
  the middle of a lake — where no journey could start. They now land on the nearest dry atom
  of the same hex, or of the nearest neighbour with ground (`boats.ashore_spot`).
- The uninstaller could report "some elements could not be removed": a server still running
  kept the program files locked, and the question about the game came after the removal, so
  a kept game left the folder in place. It now stops the launcher and its server first, asks
  before removing anything, and leaves nothing of the program behind either way.
- The crest and the kingdom's name in the header wrapped on two lines: they sit on one now,
  on the login page too.

### Added
- A way out for a stuck marker: the arrow next to *Who leaves* in the Travel box takes the
  chosen characters off the map, to be placed again from the Party tab. Someone on a journey
  is refused.

## [1.1.0] — 2026-09-16

The app for people without a terminal: an installer, a launcher window, and the same web app
behind it. Running from source is unchanged.

### Added
- **Installers**: a Windows setup (`Kingmaker-Kingdom-Manager-<version>-Setup.exe`, per-user,
  no administrator rights, English and Italian) and a Linux tarball, both with Python and
  every dependency inside, built by `packaging/build.py` (PyInstaller, Inno Setup) and
  attached to each release by the new GitHub Actions workflow. The uninstaller asks whether to
  delete the game too. The executable is unsigned: the README explains the SmartScreen click.
- **The launcher** (`kingmaker/launcher/`): a window that starts and stops the server, with
  *On this computer* / *On the same network* / *Online* modes, the On Air token entry with the
  steps to get one, the links to copy for the players, the first-start password in a dialog,
  a log pane, settings (port, language, browser), *Open the game folder*, *Reset the
  administrator password*, *Load a save file…* (the game of another PC, looked at and
  confirmed before it replaces the current one), and an update check against GitHub Releases
  with a one-click download on Windows, and *Versions on GitHub…* to install any release,
  an older one included. From source: `python launch.py --launcher`.
- **The Save tab** (administrators only, after the GM Screen): *Download everything (.zip)*
  — database, kingdom JSON and every image in one file (`storage/bundle.py`) — *Load a save*
  (that zip or a bare `kingmaker.db`, looked at and confirmed first, images unpacked into
  `assets/`) and *Start over*. The separate `.db` and JSON downloads of the Manual tab are
  gone; the JSON travels inside the zip.
- **Already have a save file?** on the kingdom creation page: the same *Load a save* control,
  for whoever arrives with a game played elsewhere.
- **The cloud** (`kingmaker/launcher/{dropbox,sync,wizard}.py`): the hosting moves between
  the administrator and the GMs flagged *Can host* (new checkbox in the accounts dialog,
  `users.can_host`, schema 29, `permissions.HOST_GAME`) through a folder in the
  administrator's Dropbox. One host at a time, decided by a record with a compare-and-swap
  and a heartbeat; five recent copies and thirty daily ones; the images once, by hash; the
  administrator's *Force take-over*. The launcher guides the administrator through the
  Dropbox set-up with pictures, and the other hosts receive the credential from a running
  host over `POST /_launcher/credential` with their username and password. Four more local
  routes for the launcher (`status`, `snapshot`, `synced`). Tested against a one-process
  Dropbox (`tests/fake_dropbox.py`, `tests/test_sync.py`).
- **`--serve`** and a shared command line (`kingmaker/cli.py`) for `launch.py` and the
  installed app; `KM ready` / `KM lan` / `KM admin-password` lines on stdout for the launcher;
  `POST /_launcher/shutdown`, registered only when `KINGMAKER_LAUNCHER_SECRET` is set, for a
  clean stop from the launcher (the last save is written).
- `tests/test_launcher.py`; `packaging/` (spec, Inno Setup script, build script, the icon
  cut from the crest of the author's party);
  `.github/workflows/release.yml` and `ci.yml`; chapter 12 of the manual; a *Download*
  section in the README.

- The party's crest as the face of the app: the launcher's icon, the installer's, the browser
  tab's favicon and the badge next to the kingdom's name in the header and on the login page
  (`kingmaker/ui/static/crest*.png`, `theme.crest`).
- Chapter 13 of the manual (the cloud), a "Playing from several PCs" chapter in both user
  guides, the launcher and wizard screenshots.

### Changed
- When the app is frozen, `saves/`, `assets/` and the sessions live next to the executable
  (`config._root`), so the installed folder has the same shape as the repository and an update
  or an uninstall never touches the game. From source nothing moves, and a test pins it.
- The Linux tarball is built on Ubuntu 22.04 and needs glibc 2.35 or newer (Ubuntu 22.04+,
  Debian 12+).
- The test scene brings its own map image (a placeholder in `tests/scene/assets/`) instead of
  naming the author's, so the suite passes on any machine.

## [1.0.0] — 2026-09-15

The first public release. The whole codebase, the storage and the documentation are in
English; the interface is bilingual.

### Added
- **Bilingual interface (English / Italian)** with a per-user preference: the IT/EN toggle in
  the header and on the login page; the browser's language is used before a choice is made.
  Every text of the interface lives in `kingmaker/locale/lang/`, texts sent to other windows are
  rendered in each viewer's language.
- **English rule texts** transcribed from Archives of Nethys (structures, activities, feats,
  vehicles, terrains, tables), with the source URL recorded per file; the Italian texts from
  pf2.altervista.org remain. Mechanics and texts are now separate files
  (`kingmaker/rules/data/*.json` and `kingmaker/rules/data/lang/<code>/`).
- Structures have stable ids; their kingdom effects are structured data instead of prose
  parsed at runtime.
- `README.md` / `README.it.md`, a user guide in both languages, the code manual in English,
  this changelog and the devlog.
- `LICENSE` (MIT), `OPEN_GAME_LICENSE.md` (OGL 1.0a with Section 15), `NOTICE.md` (Paizo
  Community Use Policy).
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example` — **untested**, see the
  README.
- Four checkers in `tools/`: `check_names.py` (no undefined name), `check_i18n.py`
  (catalogs complete, no `t()` at import time), `check_texts.py` (no label or caption written
  straight into a `ui.*` call, bypassing the catalogs), `check_data.py` (both languages have
  the same shape, every referenced id exists); `tests/test_i18n.py` runs the last three.
- `KINGMAKER_LANG`, `KINGMAKER_HTTPS`, `KINGMAKER_TRUST_PROXY` settings.
- **Metres or feet**, chosen per person with the m/ft button in the header (5 ft = 1.5 m;
  feet by default with the English interface). Speeds stay stored in metres; every field and
  label follows the choice, and the Travel Speed line shows miles per hour and per day.
- **Save file backup**: in the Manual tab the administrator downloads the whole database
  (`kingmaker-<date>.db`) and can load one back; the current save is copied next to itself
  before being replaced, and an old file is migrated on the way in.
- A **GM fog** slider next to the players' one, for the veil on the GM screens.
- The grid calibration accepts **typed numbers** for radius and origin, next to the sliders.
- **Lake names** are drawn on the map, above the water lines (below them while the Waters
  mode is on), with a button in the Waters box to hide them.
- Schema 28: `users.units` column.

### Changed
- **Everything renamed to English**: modules (`archivio`→`archive`, `viaggio`→`travel`,
  `ui/mappa/`→`ui/hexmap/`, …), identifiers, dictionary keys, JavaScript globals and events, CSS
  classes, comments and docstrings, the test suite (`prove/`→`tests/`), the tools.
- **Package layout by layer**: the twenty-four flat modules are grouped into `rules/`
  (loader, calendar, data), `locale/` (i18n, units, catalogs), `geometry/`, `water/`,
  `travel/`, `storage/`, `access/`, `media/`, and inside `ui/` into `tabs/`, `hexmap/` (the
  map package, facade in `__init__.py`) and `static/` (the browser scripts). Imports are
  absolute; module names are unchanged.
- **Storage schema 27**: tables, columns, document keys and stored enum values are English.
  Existing saves are migrated automatically at the first start (see *Upgrading*).
- Tabs are addressed by language-neutral ids; the refresh bus and the ruler no longer compare
  labels.
- The test scene uses neutral fantasy names; three tests that grepped the source for Italian
  literals now look for catalog keys.
- `avvia.py` → `launch.py` (`--lan`, `--port`, `--no-browser`, `--online [TOKEN]`),
  `avvia_prova.py` → `launch_test.py`; the window title is «Kingmaker Kingdom Manager».
- **Lake and River are no longer terrains**: water is drawn on top of the terrain (borders,
  cuts, lakes) and only the drawn water counts. The two entries stay in the data as `legacy`
  for the heartland table; hexes marked Lake or River in an old save lose the mark at the
  first start. The image reading no longer proposes «lake hexes».
- Asset folders renamed at first start: `assets/personaggi` → `characters`,
  `veicoli` → `vehicles`, `miniature` → `thumbnails`.

### Fixed
- **Security** (second review, each with a test in `tests/test_security.py`): usernames and
  every user-typed text escaped wherever they reach SVG or HTML markup, including the ruler
  labels drawn in the browser; usernames restricted to `[A-Za-z0-9._-]{2,32}`; every mutating
  action re-checks the permission server-side (`EDIT_KINGDOM` was never checked), so a
  spectator is read-only by construction; an open window re-reads its identity when the
  archive changes (deactivated → logged out, changed role → applied); password change refused
  while impersonating and the self-change asks the current password; login throttling behind
  a proxy (`X-Forwarded-For` only with `KINGMAKER_TRUST_PROXY`, per-address bucket off under
  On Air); ruler payloads capped and validated before use; `Secure` cookie with
  `KINGMAKER_HTTPS`; session rotation on login and logout; the background image name goes
  through the safe-name filter; the last active administrator cannot be demoted, deactivated
  or deleted, nor can one change one's own role.
- The water route drawn by hand with the ruler was replaced by the cheapest one on release:
  the payload check dropped the hex of every point, and a drawn step onto a shared vertex
  counted in the next hex did not match the server's steps. Both fixed; the drawn junctions
  are kept. On the water the direction now comes from the **line** the cursor is on and the
  steps from its junctions, each taken once the cursor has travelled two thirds of the side
  leading to it and undone when it comes back halfway, the side just travelled never being
  offered backwards (a dashed preview shows the line being entered);
  thresholds are screen pixels, and zoomed far out a line is one step. A confluence no longer
  picks a line by itself.
- A boat's route was not shown to the other windows while it was being steered or once it
  was prepared; now it is published like a land journey, and whoever can see the boat's hex
  sees its arrow.
- Hiding the water lines with the icon of the Waters button had no effect once the layer was
  cached.
- A boat could sail to the vertices of a lake cell that lie outside the drawn shape: the lake
  mesh now holds only the points inside the ring (or on it).
- `launch.py --online` ignored its token argument.
- A cosmetic rename had shadowed `hexgrid.neighbours` inside `common_vertex`.

### Upgrading
- The save is migrated to schema 27 at the first start. `Archive` checkpoints the write-ahead
  log and copies `saves/kingmaker.db` to `saves/kingmaker.db.pre-v27.bak` **before** touching
  it; keep that file until you have played a session. Old JSON exports are recognised and
  translated on import.
- Any private script that read the Italian tables or document keys must be updated
  (`legacy_names.py` holds the maps).
- `saves/regno.json` is still imported into an empty database, then left where it is.

## [0.9.0] — 2026-09-13

### Added
- The code manual (`docs/manuale/`, 11 chapters) and the figures generated from the app's
  own drawing functions; screenshots of every tab.
- **Ctrl+click** on a badge adds people and vehicles one at a time; «Take the chosen».
- Reconnoiter from the hex box (`reconnaissance_cost` wired).
- A cleanup review (`docs/manuale/11-pulizia.md`): dead code removed, duplicates merged, the
  map split into the `ui/mappa/` package with `hexmap.py` as a facade, caches keyed on the
  archive revision, the journal moved into its own table.

### Fixed
- First security pass: ruler events check `PLAN_TRAVEL`; texts from the JSON escaped in
  `ui.html`; the login brake also counts by address; `_attempts` no longer grows forever;
  «Start over» empties every campaign table.
- Frozen journey costs lost the detour inside a cut hex; a boat followed a land journey; the
  map view was built four times per redraw.

## [0.8.1] — 2026-09-12

### Fixed
- Rounding of route costs done identically by the server and the dragged arrow.
- The two rulers (land and water) send a single cost per step; the browser rebuilt paths
  through inner bridges.

### Changed
- Docstrings trimmed to the «why»; the manual chapters started.

## [0.8.0] — 2026-09-11

### Changed
- **The hex as 24 atoms**: water lines close borders between fixed pieces instead of creating
  sections; a crossing of a clean hex is exactly 4 atoms in all 15 directions, so ¼ per atom
  reproduces the rules without calibration. The travel node became `(col, row, gate)`.
- The plan charges the detour around water inside a hex; the dragged ruler counts by atoms
  with the same layered Dijkstra as the server (`bench10`, `bench11` compare the two).
- Markers drawn per piece, sized by the piece; groups show a count; the badge of a boat sits
  on its junction.

### Added
- Inner bridges and fords as reopened atom borders; fords on the whole line, bridges on the
  stretch; swimming (`swim_speed_m`) crosses without a boat.

## [0.7.0] — 2026-09-10

### Added
- Boarding and landing on the map: vehicles are placed in a hex, one boards from the same
  piece, one lands ashore; the transport tab became the depot.
- Paths may cross themselves and pass the same hex twice; the dragged arrow fades on the last
  three stretches; blocked steps flash red, vibrate and say why.
- The travel arrow is shown live to the other windows, with its author's colour.

### Fixed
- The first drag step takes the shortest way; filling a jump goes straight only.

## [0.6.0] — 2026-09-09

### Changed
- Sections are the **faces** of the planar drawing of the water (`sezioni.facce_di`), not
  groups of sides; markers and arrows have a point per section; section numbers are derived
  from saved points, never stored.
- Crossings are stored as two shore points plus the point on the water.

### Added
- The water route on atom sides: junctions (corners, center, twelve inner points), pieces and
  edges, ¼ and ½ activity, double upstream; lakes as a triangular mesh of still water.

## [0.5.0] — 2026-09-08

### Added
- Water vehicles: routes along drawn rivers, currents (upstream/downstream brush), lakes drawn
  by hand, «⛵ By river» next to the land plan.
- The water chart (JSON export/import of borders, banks, crossings, currents with the grid
  calibration), the assisted reading of the water from the image (a proposal to accept).
- Thumbnails for portraits and tokens; the On Air prefix on SVG addresses.

### Changed
- Performance: differential saves, the SVG ground layers cached per window, the refresh bus
  redraws only panels in the foreground tab.

## [0.4.0] — 2026-09-07

### Added
- Vehicles from the rules catalogue (45), depots by kind (land, water, air), «All aboard».
- Water borders (water, ford, bridge) between hexes and banks inside a hex; the Waters mode
  with its brushes and eraser.
- **SQLite** storage (`saves/regno.db`) replacing the JSON file; separate tables for hexes,
  users, characters, vehicles, journeys and water.

## [0.3.0] — 2026-09-06

### Added
- Characters with portraits and tokens, linked to accounts and to leadership roles; markers
  on the map; the row of portraits.
- Travel: Dijkstra over the hex grid with the rules' costs, activities per day from Speed,
  forced march, unknown hexes counted as the worst, the ruler dragged in the browser, the
  rendezvous of a scattered party, separate journeys.
- The clock: Absalom Reckoning calendar, days passing on the server, journeys advancing, the
  Kingdom Turn at the end of the month.

## [0.2.0] — 2026-09-05

### Added
- Accounts and roles (admin, GM, player, spectator) with PBKDF2 passwords and login
  throttling; impersonation for the administrator.
- The GM screen: fog of war per player, secret features and hidden fields, «See as the
  players».
- Grid calibration on the uploaded map image; the terrain veil; the map remembers the scroll.
- LAN and NiceGUI On Air publishing from `avvia.py`.

## [0.1.0] — 2026-09-03

### Added
- The kingdom sheet, the guided creation, the Kingdom Turn with every activity and its four
  outcomes proposed and confirmed, the settlements with the Urban Grid and the 76 structures,
  the hex map with statuses, terrains and features, the in-app Manual, JSON save.
