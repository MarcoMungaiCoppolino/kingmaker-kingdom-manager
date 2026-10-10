# Security

Kingmaker Kingdom Manager is a self-hosted app: the person who runs it holds accounts with
password hashes, a session-signing secret, and — with the cloud sync — a Dropbox credential.

## What counts

Anything that lets a player see or do what their role does not allow — a hex under the fog, a
GM note, another account's session, the administrator's powers — and anything that reaches the
host's machine from the network beyond the pages the app serves: the launcher routes, the
upload of images, the save file loaded from a zip, the pairing of another host's launcher, and
what the launcher takes from the cloud folder — a snapshot is loaded only if it passes the
same checks as a zip, and an image only under a path inside the images folder, with the bytes
its name promises, and only if it is an image. The launcher also checks that the table's public
address answers from its own server (a proof made with a secret of that start alone), at start
and every five minutes while hosting, and warns when another program holds it; that is
detection, not prevention — the relay gives the address to whichever program connected last
with the token, silently, so whoever holds the token can take the address until the
administrator renews it. The launcher's secrets
(the two Dropbox keys, the launcher's signing seed, the On Air token of whoever plays online
without the cloud) rest protected by Windows for the user (DPAPI) or in an owner-only file
outside the game folder on Linux; that keeps them from a copied folder and from other users
of the PC, not from a program running as you.

What a key holder can do in the folder is bounded by signatures, since Dropbox cannot bound
it: every launcher signs the record it holds and the copies it uploads with a key of its own,
the administrator signs the table's file and the list of launchers it vouches for, and a
launcher loads only what a vouched-for launcher signed (see *Trust in the folder* in the
manual's chapter 13). A stolen key reads the folder; it cannot feed the table a copy, take the
seat, or pass as a host. Installers are signed by the owner's offline key and refused by the
launcher otherwise; an account may ask a one-time code after its password. Reports of a way
around any of these are the ones most worth sending.

Out of scope: what the documentation already says is not protected. The On Air relay can read
the traffic; a host's disk holds the whole game; whoever has the database file can rewrite a
password; a rented server needs an HTTPS proxy in front. See *Hosting and security* in the
[README](README.md#hosting-and-security) and [PRIVACY.md](PRIVACY.md).

## Supported versions

The latest release only. The launcher says when a newer one exists, and *Settings → Versions on
GitHub…* installs it over the current copy, keeping the game.
