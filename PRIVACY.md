# Privacy and data

*Leggi questo documento in italiano: [PRIVACY.it.md](PRIVACY.it.md).*

Kingmaker Kingdom Manager is a program you run yourself. There is no service behind it: the
author operates no server, receives no data, keeps no account of who uses it, and gathers no
statistics or crash reports. Everything the app knows lives on the computer of whoever hosts
the game, in the `saves` and `assets` folders next to the program.

This page says what that is, what leaves that computer in each way of playing, and who is
responsible for it. The same text, shorter, is in the app under *Manual → Privacy & licences*,
where every player can read it.

## What the app stores

On the host's computer only:

- **Accounts** — username, a salted PBKDF2-HMAC-SHA256 hash of the password (the password itself
  is never stored), role, interface language and units, creation date and last login. No
  e-mail address, no real name, nothing else is asked.
- **The game** — the kingdom, the settlements, the map with its fog and the GM's notes, the
  characters and vehicles, the journeys, the calendar.
- **The journal** — the log of actions in the kingdom, each line with the username of whoever
  acted. When an administrator looks at the game as another account, the journal says so.
- **Images** — the map, the characters' portraits and tokens, uploaded by the table.
- **The session cookie** — a signed cookie that keeps you logged in. It is the only cookie the
  app sets, it is strictly necessary for the login to work, and it holds no tracking. Its
  content (your account id and language) is kept on the host in `.nicegui/`.
- **Login attempts** — counted in memory, by username and by address, to slow down password
  guessing. They are never written to disk and vanish when the server stops.

Save files (the zip from the Save tab, a bare `kingmaker.db`) and the copies the cloud sync
uploads contain **all of the above, password hashes included**. Treat them as private: keep
them as backups, carry them to another PC, but do not post them anywhere public.

## What leaves the host's computer

**On this computer only, or on the same network** — nothing. The pages, scripts, stylesheets
and typefaces all come from the host; a player's browser talks to no one else. The app works
with the internet unplugged.

**Online, through NiceGUI On Air** — the game traffic goes through a relay operated by
[Zauberzeug GmbH](https://zauberzeug.com/) (Germany), the makers of NiceGUI, under their
[terms](https://nicegui.io/on_air). The relay sees each player's address and the traffic passes
through it in the clear: the operator could read it. Fine for a game, not for anything you
would call a secret. The On Air token, if you use one, is stored in clear in the game folder;
with the cloud (below) it is stored in the table's folder instead, and read from there at every
start.

**With the cloud (hosting from several PCs)** — the hosting launcher uploads, to a folder in the
administrator's Dropbox: a copy of the whole database (accounts and password hashes included)
every few minutes while something changes, the images once, and a small record naming the host —
its launcher's random id, the **Windows or Linux username and the computer's name** of whoever
hosts, the game's address and the app's version. Dropbox's own
[privacy policy](https://www.dropbox.com/privacy) applies to that folder, and the Dropbox app the
administrator creates for it is theirs, under Dropbox's developer terms. Every GM marked *Can
host* receives the administrator's Dropbox credential for that app folder: it is the same
access the administrator has, and it cannot be revoked for one host without revoking it for
all (from Dropbox's *Connected apps*, after which everyone connects again). On each host's PC
the credential, and the On Air token of whoever plays online without the cloud, are stored
protected: on Windows by the system for that Windows user (DPAPI), on Linux in a file only
that user can read, outside the game folder (`~/.local/share/kingmaker-kingdom-manager/`).
The launcher's settings file holds no secret in clear, and a copied game folder carries none
that another PC can use.

**The launcher** — at every start it asks GitHub whether a newer release exists, which tells
GitHub the address of the host's PC and the app's version, nothing more. *Settings → Ask
GitHub for a newer version at start* turns it off; *Versions on GitHub…* still asks when you
press it. Downloading an update fetches the installer from GitHub and, on Windows, runs it:
the installer is not signed with a paid certificate, which is why Windows warns the first
time.

Nothing else ever leaves the machine. The typefaces used to be loaded from Google Fonts by
every player's browser, which handed Google the player's address on every page; the app now
serves them itself.

## Who is responsible

Whoever hosts the game holds the players' data, and answers for it under whatever privacy law
applies to them — in the EU, the GDPR, for which the host is the *controller*. For a table of
friends that mostly means: tell them what is above, delete what they ask you to delete, and
do not share the save. The author of the program is not a party to any of it and processes
nothing.

**Deleting.** An administrator deletes an account from the accounts dialog (the 👤⚙ icon in
the header) and replaces or removes an image from the sheet or the map where it was
uploaded. Deleting the `saves` and `assets` folders removes everything; the uninstaller asks
whether to do so.

## Licences and the game rules

The program is under the [MIT licence](LICENSE). The game rules are Open Game Content under the
[Open Game License v1.0a](OPEN_GAME_LICENSE.md), and the Pathfinder and Kingmaker names appear
under Paizo's Community Use Policy — see [NOTICE.md](NOTICE.md). This project is not published,
endorsed, or specifically approved by Paizo Inc., and it is free of charge.

The installed app bundles software by others — NiceGUI and the Python packages it rests on,
the Vue, Quasar and Tailwind libraries it serves to the browser, Python itself with Tcl/Tk,
PyInstaller's bootloader, the Material icons, and the three typefaces of the interface
(Cinzel, IBM Plex Sans and Press Start 2P, under the SIL Open Font License). Their licences
are in `THIRD_PARTY_LICENSES.txt` next to the installed program; from source,
`python packaging/third_party.py` writes the same file for your environment.