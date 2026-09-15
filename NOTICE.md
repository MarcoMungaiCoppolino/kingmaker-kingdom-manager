# Notices

## Paizo Community Use Policy

Kingmaker Kingdom Manager uses trademarks and/or copyrights owned by Paizo Inc., used
under Paizo's Community Use Policy (https://paizo.com/licenses/communityuse). We are expressly
prohibited from charging you to use or access this content. Kingmaker Kingdom Manager is
not published, endorsed, or specifically approved by Paizo. For more information about Paizo
Inc. and Paizo products, visit https://paizo.com.

Paizo's Community Use Policy requires that this project remain free. It must stay accessible to
everyone at no charge, and access must not be gated behind payment, surveys, or downloads of
unrelated products. Do not distribute a paid version of this project while it carries the
notice above.

## Identification of Open Game Content (OGL v1.0a, Section 8)

The following portions of this work are **Open Game Content**, used under the Open Game License
v1.0a — see [OPEN_GAME_LICENSE.md](OPEN_GAME_LICENSE.md) for the licence and the full Section 15
copyright notice:

- Every game rule, statistic, value, Difficulty Class, cost, trait, formula and table in
  `kingmaker/data/` and `kingmaker/data/lang/`, in both Italian and English, including the
  descriptive rules text of kingdom activities, structures, feats, vehicles and kingdom
  characteristics.
- The rules mechanics implemented in code, in particular `kingmaker/rules.py`, and the parts of
  any other module that reproduce or compute those mechanics.
- The passages of `README.md` and of `docs/` that quote, translate, transcribe or restate those
  rules.

These portions are Open Game Content because they derive, through the chain recorded in
Section 15, from material released as Open Game Content by Paizo Inc. and — for the Italian
text — from the Italian editions published by Giochi Uniti Srl, by way of Golarion Insider ::
Pathfinder Wiki (https://pf2.altervista.org). Under OGL Section 1(b) and 1(d), translations of
Open Game Content are themselves Open Game Content.

## Identification of Product Identity (OGL v1.0a, Section 7)

The following are **Product Identity** owned by Paizo Inc. They are **not** Open Game Content,
they are **not** licensed to you by the Open Game License, and they appear here only under the
Community Use Policy quoted above:

- The trademarks *Pathfinder*, *Kingmaker*, *Golarion*, *Lost Omens*, *Presagi Perduti*, the
  Paizo name and logo, and all associated trade dress.
- The Absalom Reckoning calendar in `kingmaker/data/calendar.json` and its translations: the
  month names Abadius, Calistril, Pharast, Gozran, Desnus, Sarenith, Erastus, Arodus, Rova,
  Lamashan, Neth and Kuthona; the weekday names; and the deity names given in the accompanying
  notes — Abadar, Calistria, Pharasma, Gozreh, Desna, Sarenrae, Erastil, Aroden, Rovagug,
  Lamashtu, Nethys and Zon-Kuthon.
- The character names *Linzi* and *Amiri*, referenced in the structure entries of
  `kingmaker/data/lang/*/structures.json`.
- The place name *the Stolen Lands* (*le Terre Rubate*), referenced in
  `kingmaker/data/lang/*/activities.json`.

Use of this Product Identity does not constitute a challenge to Paizo's ownership of it. Paizo
retains all rights, title and interest in and to it.

Anyone forking this project should note that Community Use Policy permission is granted to the
individual project, is revocable by Paizo, and does not pass downstream with the code. A fork
must accept the Community Use Policy on its own account, or remove the Product Identity listed
above.

## Third-party material

The screenshots of the Map screen in `docs/manuale/img/schermate/` — `mappa.jpg`,
`mappa-esagono.jpg`, `mappa-acque.jpg` and `mappa-viaggio.jpg` — show the application running
with a fan-made hex map of the Stolen Lands loaded as its background image. That map is not the
work of this project's author:

> **Map of the Stolen Lands** — created by **Dimitris Havlidis**
> (https://www.worldanvil.com/w/golarion-chronicles-dimitris/map/7825a9b1-2bd4-4783-abf5-c65affcf5c18, @dimitrisromeo), shared freely with the community.
> Published at
> https://www.reddit.com/r/Pathfinder_RPG/comments/10rs7zo/kingmaker_stolen_lands_map_truly_accurate_hd_8k/

Copyright in that map belongs to its author. It is neither Open Game Content nor covered by the
MIT licence of this project, and it appears here only as the background of those four
screenshots. No map image is distributed with this application or stored in this repository:
`assets/` ships none, and each table supplies its own (see [assets/README.md](assets/README.md)).
The Stolen Lands themselves are Paizo Product Identity, as listed above.

The map was published some years ago. If you are Dimitris Havlidis, or you hold rights in that map: 
the credit above is offered in good faith and can be changed at any time. Write to Marco Mungai 
Coppolino at marcomungaicoppolino@gmail.com and the credit will be reworded however you prefer, 
or the screenshots replaced with ones that do not show your work — whichever you would rather. 

Thank you for making it: it is a beautiful map.

## Original material

Everything that is neither Open Game Content nor Product Identity is the original work of the
author and is licensed under the MIT licence — see [LICENSE](LICENSE). This covers the
application code, the user interface, the save format, the tools and tests, the original
analysis and prose in `README.md` and `docs/`, and the figures in `docs/img/` and
`docs/manuale/img/`.

It also covers the house rules created at the table rather than taken from the rulebooks. These
are marked in the data with `"fonte": "tavolo"` (`"source": "table"`) and are flagged as such in
the interface: the travel cost of fords, the travel category assigned to ruins, and the
Trap or Hazard, Dungeon and Event terrain features.

## Sources

Game data was transcribed from Golarion Insider :: Pathfinder Wiki
(https://pf2.altervista.org) and from Archives of Nethys (https://2e.aonprd.com), which publish
this material as Open Game Content. No rules values were invented; where the table supplied a
reading the rules do not give, it is marked as described above.
