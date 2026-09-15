"""Moving from the old JSON save to the database, and every migration since.

It runs on its own at the first start after an update and only once: if the
database already holds a game, the JSON file is left where it is and never
read again. The file is not deleted: it stays as a backup until you decide to
remove it.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Callable

from kingmaker.geometry import hexgrid
from kingmaker.geometry import sections as sections_mod

log = logging.getLogger(__name__)

# Four «hex features» on the sheet are not list entries but hex fields. They
# used to be saved both ways, and the two copies diverged: the list entry even
# showed the generic icon.
FIELD_OF_FEATURE = {
    "roads": "roads",
    "fortification": "fortified",
    "farmland": "farmland",
    "work_site": "work_site",
}


# Structures used to be saved by their Italian name inside the settlement
# lots; today they have an id. The map serves `normalize`.
LEGACY_STRUCTURE_NAMES = {
    "Casamenti": "tenement",
    "Macerie": "rubble",
    "Bettola": "tavern_dive",
    "Case": "houses",
    "Cimitero": "cemetery",
    "Distilleria": "brewery",
    "Emporio": "general_store",
    "Erbario": "herbalist",
    "Granaio": "granary",
    "Locanda": "inn",
    "Mura di Legno": "wooden_wall",
    "Santuario": "shrine",
    "Biblioteca": "library",
    "Discarica": "dump",
    "Mulino": "mill",
    "Municipio": "town_hall",
    "Orfanotrofio": "orphanage",
    "Ponte": "bridge",
    "Prigione": "jail",
    "Attività Commerciale": "trade_shop",
    "Caserma": "barracks",
    "Conceria": "tannery",
    "Deposito di Legname": "lumberyard",
    "Fonderia": "foundry",
    "Fortezza": "keep",
    "Fucina": "smithy",
    "Laboratorio Alchemico": "alchemy_laboratory",
    "Molo": "pier",
    "Monumento": "monument",
    "Parco": "park",
    "Recinto del Bestiame": "stockyard",
    "Salone per le Feste": "festival_hall",
    "Stalla": "stable",
    "Tagliapietre": "stonemason",
    "Taverna Popolare": "tavern_popular",
    "Torre di Guardia": "watchtower",
    "Artigiano Specializzato": "specialized_artisan",
    "Mercato": "marketplace",
    "Strade Lastricate": "paved_streets",
    "Banca": "bank",
    "Boschetto Sacro": "sacred_grove",
    "Gilda dei Ladri": "thieves_guild",
    "Guarnigione": "garrison",
    "Lampioni Magici": "magical_streetlamps",
    "Magione": "mansion",
    "Mura di Pietra": "stone_wall",
    "Museo": "museum",
    "Sede della Gilda": "guildhall",
    "Torre dell'Arcanista": "arcanists_tower",
    "Bottega di Lusso": "luxury_store",
    "Magazzino Sicuro": "secure_warehouse",
    "Mercato Nero": "illicit_market",
    "Sistema Fognario": "sewer_system",
    "Tempio": "temple",
    "Ambasciata": "embassy",
    "Bottega di Magia": "magic_shop",
    "Zona Portuale": "waterfront",
    "Arena": "arena",
    "Castello": "castle",
    "Ospedale": "hospital",
    "Taverna di Lusso": "tavern_luxury",
    "Teatro": "theater",
    "Villa Nobiliare": "noble_villa",
    "Accademia": "academy",
    "Cantiere": "construction_yard",
    "Tipografia": "printing_house",
    "Accademia Militare": "military_academy",
    "Serraglio": "menagerie",
    "Bottega dell'Occulto": "occult_shop",
    "Arena Gladiatoria": "gladiatorial_arena",
    "Cattedrale": "cathedral",
    "Palazzo": "palace",
    "Taverna Internazionale": "tavern_world_class",
    "Teatro Lirico": "opera_house",
    "Università": "university",
    "Zecca": "mint",
}


def normalize(data: dict, empty_schema: Callable[[], dict]) -> dict:
    """Completes a save with the keys that did not exist back then.

    The old `load()` did exactly this: it started from the empty kingdom and
    wrote the file over it, so a new version of the app did not break on an
    old save.
    """
    if is_legacy_document(data):
        data = translate_document(data)
    base = empty_schema()
    base.update(data)
    # Nested keys are merged separately, or a "map" block saved before a field
    # was added would come back without that field.
    for key in ("map", "clock"):
        merged = empty_schema()[key]
        merged.update(data.get(key, {}))
        base[key] = merged

    # Roles are a dictionary of dictionaries: here the merge goes two levels
    # deep, or a save predating `character_id` would drop it with the rest.
    roles_model = empty_schema()["roles"]
    roles = {}
    for rid, model in roles_model.items():
        entry = dict(model)
        entry.update(data.get("roles", {}).get(rid, {}))
        roles[rid] = entry
    base["roles"] = roles

    # Settlement lots: from the structure's Italian name to its id.
    for sett in base.get("settlements") or []:
        for grid in sett.get("grids") or []:
            for block_ in grid:
                for lot in block_:
                    name = lot.get("structure")
                    if name in LEGACY_STRUCTURE_NAMES:
                        lot["structure"] = LEGACY_STRUCTURE_NAMES[name]
    return base


def ensure_characters(archive, campaign_id: str, k: dict) -> int:
    """Turns the PC names typed by hand in the roles into characters.

    Before the migration a role was just a string, and two roles were "the same
    person" only because the name matched: that is exactly the criterion used
    here to avoid duplicates. Roles with the PC box unticked stay NPCs and do
    not become characters.

    Returns how many characters it created.
    """
    to_create: dict[str, list[str]] = {}
    for rid, entry in k.get("roles", {}).items():
        if not entry.get("pc") or entry.get("character_id") or not entry.get("name"):
            continue
        to_create.setdefault(entry["name"].strip(), []).append(rid)
    if not to_create:
        return 0

    existing_ones = {p["name"]: p["id"] for p in archive.list_characters(campaign_id)}
    created_ones = 0
    for name, roles in to_create.items():
        char_id = existing_ones.get(name)
        if char_id is None:
            char_id = uuid.uuid4().hex[:12]
            archive.create_character({
                "id": char_id,
                "campaign_id": campaign_id,
                "user_id": None,
                "name": name,
                "speed_m": 7.5,
                "con_mod": 0,
                "color": "#d7b263",
                "active": 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            existing_ones[name] = char_id
            created_ones += 1
        for rid in roles:
            k["roles"][rid]["character_id"] = char_id

    if created_ones:
        log.info("created %d characters from the names already written in the roles", created_ones)
    return created_ones


WATER_TERRAINS = ("lake", "river")


def drop_water_terrains(kingdom: dict) -> bool:
    """Lake and River are no longer terrains (release 1.0.0): water is drawn
    on top of the terrain, and the drawn lines are what travel looks at. A hex
    marked Lake in an old save loses that mark; whatever dry terrain it also
    had stays, and a hex left without terrain counts as never explored."""
    changed = False
    for hexagon in (kingdom.get("hexes") or {}).values():
        terrains = list(hexagon.get("terrains") or ())
        dry = [tid for tid in terrains if tid not in WATER_TERRAINS]
        if dry != terrains:
            hexagon["terrains"] = dry
            changed = True
    return changed


def unify_fields(k: dict) -> int:
    """Moves the old equivalent list entries into the hex fields.

    Roads, fortification, farmland and work site have their own controls: the
    twin entry among the features was a leftover that showed the wrong icon
    and could contradict the field.

    Returns how many entries it converted.
    """
    converted = 0
    for hexagon in (k.get("hexes") or {}).values():
        remaining = []
        for el in hexagon.get("features", []):
            field = FIELD_OF_FEATURE.get(el.get("kind"))
            if field is None:
                remaining.append(el)
                continue
            if field == "work_site":
                if not hexagon.get("work_site"):
                    hexagon["work_site"] = {"commodity": el.get("name") or "lumber",
                                              "doubled": False}
            else:
                hexagon[field] = True
            converted += 1
        if converted:
            hexagon["features"] = remaining
    if converted:
        log.info("converted %d list entries into the matching fields", converted)
    return converted


def ensure_visibility(archive, campaign_id: str, k: dict) -> int:
    """Makes the already explored hexes visible to the party.

    Before this version the whole map was visible to everyone: starting from
    scratch, on first start the players would find themselves without the
    territory they have known for months. So everything that is not "unknown"
    is born revealed, and only what the party has not really explored yet
    stays hidden.

    Runs once: if the table already has rows for this campaign the GM has
    arranged it themself, and we do not touch it.
    """
    if archive.count_visible(campaign_id) > 0:
        return 0
    coords = [(e["col"], e["row"]) for e in (k.get("hexes") or {}).values()
                  if e.get("status") and e["status"] != "unknown"]
    if not coords:
        return 0
    archive.reveal(campaign_id, coords, "*")
    log.info("made %d already explored hexes visible to the party", len(coords))
    return len(coords)


def water_on_edge(archive, campaign_id: str, k: dict) -> int:
    """Zero-width shores become Water Borders, which is where they belong.

    Some hexes carried a shore made of **a single side**: the map reading had
    found the river running parallel to an edge, just inside, and concluded
    that from that side one cannot reach the others. In the old model that
    shore existed — as a zero-width strip, with no centroid — and did its job
    as a wall. In the new model it does not exist at all: a line drawn *on* a
    side of the hex does not divide its inside, because the inside is all on
    the same side.

    Simply dropping it would remove a wall that was there, and change the
    routes at the table. But the model already has that wall, and a better one:
    a river flowing along the edge is inside neither hex, it lies **between**
    the two, and that is a Water Border. Here it is moved there.

    It is not a rule change disguised as a migration: the passage was already
    impossible. Whoever entered from that side ended up in the strip and could
    only go back — a dead end. Writing it as a border says the same thing in
    the place where it is read.
    """
    if archive.read_meta("acqua_sul_bordo"):
        return 0
    orient = (k.get("map") or {}).get("orientation") or "pointy"
    mapping = k.get("map") or {}
    columns, rows = int(mapping.get("columns") or 0), int(mapping.get("rows") or 0)
    drawings = archive.bank_points(campaign_id)
    borders = archive.campaign_borders(campaign_id)
    moved = 0
    for coord, groups in archive.campaign_banks(campaign_id).items():
        sides = _edge_sides(sections_mod.cuts_from_groups(groups))
        if not sides:
            continue
        for side in sides:
            near = hexgrid.neighbours(coord[0], coord[1], orient)[side]
            if not (0 <= near[0] < columns and 0 <= near[1] < rows):
                continue
            if hexgrid.border_key(coord, near) in borders:
                continue
            archive.set_border(campaign_id, coord, near, "water",
                                     source="traced")
            moved += 1
        # The shores go, the drawing stays: the GM (or the map reading) put
        # that line there, and making it disappear is not ours to do.
        archive.set_banks(campaign_id, coord, [],
                              points=drawings.get(coord) or [])
    archive.write_meta("acqua_sul_bordo", "1")
    if moved:
        log.info("%d zero-width banks turned into water borders", moved)
    return moved


def _edge_sides(cuts) -> list:
    """The sides of the hex one of these cuts lies on.

    Two neighbouring vertices in the ring are the two ends of a side: the
    chord between them **is** that side, and the side between vertex `k` and
    `k+1` is direction `SIDE_RING[k+1]`.
    """
    outside = []
    for one, two in cuts or ():
        if one is None or two is None:
            continue
        if (two - one) % 6 == 1:
            outside.append(hexgrid.SIDE_RING[(one + 1) % 6])
        elif (one - two) % 6 == 1:
            outside.append(hexgrid.SIDE_RING[(two + 1) % 6])
    return sorted(set(outside))


def renumber_sections(archive, campaign_id: str, k: dict) -> int:
    """The saved shore numbers, re-read with the face model.

    A shore was a **group of sides** and is now a **face**, and between the two
    numbers there is no correspondence to write: they count different things.
    But the old shore had a place — the centroid of its piece, which is exactly
    where the marker was drawn — and that place today falls inside a single
    face. It is translated by **where**, not by number, and that is the only
    way that moves nobody: whoever is on this side of the river stays there.

    Runs once, and the mark cannot be the schema version: that is raised as
    soon as the database opens, before this function exists in time. No column
    is added here, numbers are rewritten, and doing it twice would ruin them.
    """
    if archive.read_meta("sezioni_facce"):
        return 0
    orient = (k.get("map") or {}).get("orientation") or "pointy"
    old_items = archive.campaign_banks(campaign_id)
    faces = archive.campaign_sections(campaign_id, orient)
    changed_ones = 0
    for char in archive.list_characters(campaign_id, active_only=False):
        where = (char.get("hex_col"), char.get("hex_row"))
        new = _translated_bank(old_items, faces, where, char.get("bank"), orient)
        if new is not None and new != int(char.get("bank") or 0):
            archive.update_character(char["id"], bank=new)
            changed_ones += 1
    for entry in archive.list_stable(campaign_id):
        where = (entry.get("hex_col"), entry.get("hex_row"))
        new = _translated_bank(old_items, faces, where, entry.get("bank"), orient)
        if new is not None and new != int(entry.get("bank") or 0):
            archive.update_stable_vehicle(entry["id"], bank=new)
            changed_ones += 1
    archive.write_meta("sezioni_facce", "1")
    if changed_ones:
        log.info("renumbered %d banks with the faces model", changed_ones)
    return changed_ones


def _translated_bank(old_items: dict, faces: dict, where, index, orient: str):
    """The new number of that shore, or None if there is nothing to translate."""
    if where is None or where[0] is None or where[1] is None:
        return None
    coord = (int(where[0]), int(where[1]))
    groups, pieces = old_items.get(coord), faces.get(coord)
    if not groups or not pieces:
        return 0 if int(index or 0) else None
    return sections_mod.remap_bank(groups, pieces, int(index or 0), orient)


def marker_spots(archive, campaign_id: str, k: dict) -> int:
    """The saved shore number becomes a **spot** inside the hex.

    This is the step that closes the circle. As long as the disk held an
    index, a GM redrawing the water moved people without touching them: the
    same number pointed to another piece of hex, and the marker jumped across
    the river. With a point that cannot happen — the point stays where it is,
    and the section is recomputed around it.

    The spot is that of the shore the marker already stood on: nobody moves,
    only the way it is written changes. Whoever is in a hex the water does not
    cut stays without a point, which means «in the middle», as it always has.
    """
    if archive.read_meta("posti_dei_segnalini"):
        return 0
    orient = (k.get("map") or {}).get("orientation") or "pointy"
    faces = archive.campaign_sections(campaign_id, orient)
    written = 0
    for char in archive.list_characters(campaign_id, active_only=False):
        where = _spot_of(faces, char)
        if where is None:
            continue
        archive.update_character(char["id"], pos_x=where[0], pos_y=where[1])
        written += 1
    for entry in archive.list_stable(campaign_id):
        where = _spot_of(faces, entry)
        if where is None:
            continue
        archive.update_stable_vehicle(entry["id"], pos_x=where[0],
                                         pos_y=where[1])
        written += 1
    archive.write_meta("posti_dei_segnalini", "1")
    if written:
        log.info("wrote the spot inside the hex for %d markers", written)
    return written


def _spot_of(faces: dict, entry: dict):
    """The point of the shore that entry is written on, or None."""
    col, row = entry.get("hex_col"), entry.get("hex_row")
    if col is None or row is None:
        return None
    pieces = faces.get((int(col), int(row)))
    if not pieces:
        return None
    return sections_mod.section_spot(pieces, int(entry.get("bank") or 0))


def crossings_on_point(archive, campaign_id: str, k: dict) -> int:
    """Crossings move from the pair of sides to the point on the water.

    The pair of sides held as long as every shore touched the hex edge. A shore
    closed in the middle — which now exists — has no sides, and a bridge
    reaching it could not even be written. The point where one hops over,
    everyone has.

    The translation goes through geometry: from the two sides back to the two
    sections they joined, and from their shared border the midpoint is taken. A
    bridge whose two sides ended up on the same section crossed nothing even
    before, and is lost here instead of at every pathfinder step.
    """
    old_ones = archive.stashed_rows("crossings_to_translate")
    if not old_ones:
        return 0
    orient = (k.get("map") or {}).get("orientation") or "pointy"
    faces = archive.campaign_sections(campaign_id, orient)
    carried, lost_ones = 0, 0
    for r in old_ones:
        if r.get("campaign_id") != campaign_id:
            continue
        coord = (int(r["col"]), int(r["row"]))
        found = _bridge_ends(faces.get(coord), r)
        if found is None:
            lost_ones += 1
            continue
        ends, above = found
        archive.set_crossing(campaign_id, coord, ends, above,
                               kind=r.get("kind") or "bridge",
                               difficulty=r.get("difficulty"),
                               source=r.get("source") or "gm",
                               note=r.get("note") or "")
        carried += 1
    archive.drop_stash("crossings_to_translate")
    log.info("crossings translated into points: %d carried over, %d with "
             "nothing left to hop over", carried, lost_ones)
    return carried


def _bridge_ends(faces, row: dict):
    """The shores and the spot of a crossing, from how it was written before.

    Two notations to translate, not one. The first is the **pair of sides**,
    which accompanied crossings since they exist. The second is the **point on
    the border**, which lasted the time it took to find out that a junction
    breaks it: from there one goes back to the two sections that point touches
    and takes their points, which is exactly the translation needed.
    """
    if not faces:
        return None
    if row.get("side_a") is not None and row.get("side_b") is not None:
        found = sections_mod.hop_between_sides(faces, int(row["side_a"]),
                                                int(row["side_b"]))
        return None if found is None else (found[0], found[1])
    if row.get("pos_x") is not None and row.get("pos_y") is not None:
        point = (float(row["pos_x"]), float(row["pos_y"]))
        which_ones = sections_mod.border_faces(faces, point)
        if len(which_ones) != 2:
            return None
        return ((faces[which_ones[0]].point, faces[which_ones[1]].point), point)
    if row.get("a_x") is not None:
        return (((float(row["a_x"]), float(row["a_y"])),
                 (float(row["b_x"]), float(row["b_y"]))), None)
    return None


def import_json(archive, campaign_id: str, path: Path,
                 empty_schema: Callable[[], dict]) -> dict | None:
    """Brings `path` into the database, if needed and if possible.

    Returns the imported kingdom, or None if there was nothing to do.
    """
    if archive.campaign_exists(campaign_id):
        return None
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # Better to start from an empty kingdom than not to start at all: the
        # file stays on disk and can be looked at calmly.
        log.exception("save %s unreadable: the game was not imported",
                      path)
        return None
    if not isinstance(data, dict):
        log.error("unexpected save %s (%s instead of an object)",
                  path, type(data).__name__)
        return None

    kingdom = normalize(data, empty_schema)
    archive.write(campaign_id, kingdom)
    log.info("imported %s into the database: %d hexes, %d settlements",
             path, len(kingdom.get("hexes") or {}), len(kingdom.get("settlements") or []))
    print(f"Save imported from {path.name} into the database "
          f"({len(kingdom.get('hexes') or {})} hexes). "
          f"The JSON file stays as a backup copy.")
    return kingdom


def journal_into_table(archive, campaign_id: str, k: dict) -> int:
    """The log moves from the kingdom document to the `log` table.

    The rows lived in `k["log"]`, newest first: they are inserted oldest first,
    so the order by id is the order of time. Runs once, because the key leaves
    the document.
    """
    rows = k.pop("log", None)
    if rows is None:
        return 0
    for entry in reversed(list(rows)):
        archive.record(campaign_id, {
            "logged_at": str(entry.get("t") or ""), "turn": entry.get("turn") or 0,
            "category": entry.get("category") or "info",
            "text": entry.get("text") or "", "detail": entry.get("detail") or ""})
    if rows:
        log.info("moved %d rows into the log table", len(rows))
    return len(rows) + 1


# --------------------------------------------------------------------------
# Schema 27: the storage speaks English
# --------------------------------------------------------------------------
# Version 1.0.0 renamed everything, saves included. A database written before
# that is translated once, in place, the first time it is opened: tables and
# columns first (so the schema script and every query find what they expect),
# then the rows, field by field. A copy of the file is taken before touching
# anything, next to it, as `kingmaker.db.pre-v27.bak`.
from kingmaker.storage import legacy_names as _legacy

RENAMED_TABLES = {
    "campagne": "campaigns", "regni": "kingdoms", "esagoni": "hexes",
    "esagoni_gm": "hexes_gm", "visibilita": "visibility", "personaggi": "characters",
    "utenti": "users", "stalla": "stable", "viaggi": "journeys", "registro": "log",
    "laghi": "lakes", "correnti": "currents", "confini": "borders", "rive": "banks",
    "ponti": "crossings", "ponti_da_tradurre": "crossings_to_translate",
}
OLD_INDEXES = ("idx_esagoni_stato", "idx_visibilita_destinatario", "idx_personaggi_campagna",
               "idx_stalla_campagna", "idx_viaggi_stato", "idx_registro_campagna")
_COMMON = {"campagna_id": "campaign_id", "riga": "row", "nome": "name", "creato_il": "created_at",
           "fonte": "source", "tipo": "kind", "nota": "note", "punti": "points",
           "ritratto": "portrait", "hex_riga": "hex_row", "dove_x": "pos_x", "dove_y": "pos_y",
           "riva": "bank", "velocita_m": "speed_m", "stalla_id": "stable_id"}
RENAMED_COLUMNS = {
    "meta": {"chiave": "key", "valore": "value"},
    "campaigns": {"creata_il": "created_at", **_COMMON},
    "kingdoms": {"documento": "document", "aggiornato_il": "updated_at", **_COMMON},
    "hexes": {"stato": "status", "terreni": "terrains", "elementi": "features", "strade": "roads",
              "fortificato": "fortified", "terreno_agricolo": "farmland", "sito_lavoro": "work_site",
              "insediamento": "settlement", **_COMMON},
    "hexes_gm": {"note_gm": "gm_notes", "elementi_nascosti": "hidden_features",
                 "difficolta_gm": "gm_difficulty", "campi_nascosti": "hidden_fields", **_COMMON},
    "visibility": {"destinatario": "recipient", "rivelato_il": "revealed_at", **_COMMON},
    "characters": {"utente_id": "user_id", "mod_costituzione": "con_mod", "colore": "color",
                   "attivo": "active", "bonus_velocita_m": "speed_bonus_m",
                   "velocita_nuoto_m": "swim_speed_m", **_COMMON},
    "users": {"nome_utente": "username", "hash_pw": "pw_hash", "iterazioni": "iterations",
              "ruolo": "role", "attivo": "active", "deve_cambiare_pw": "must_change_pw",
              "ultimo_accesso": "last_login", **_COMMON},
    "stable": {"veicolo": "vehicle", "disponibile": "available", "posti": "seats", **_COMMON},
    "journeys": {"personaggi": "characters", "partenza": "departure", "arrivo": "arrival",
                 "percorso": "path", "costo_attivita": "activity_cost", "giorni": "days",
                 "marcia_forzata": "forced_march", "costi": "costs",
                 "attivita_giorno": "activities_per_day", "progresso": "progress",
                 "giorno_partenza": "departure_day", "tratte": "legs", "stato": "status",
                 "turno_creato": "turn_created", "turno_risolto": "turn_resolved",
                 "creato_da": "created_by", **_COMMON},
    "log": {"quando": "logged_at", "turno": "turn", "categoria": "category", "testo": "text",
            "dettaglio": "detail", **_COMMON},
    "lakes": {"celle": "cells", **_COMMON},
    "currents": {"tratto": "stretch", "monte": "upstream", "valle": "downstream", **_COMMON},
    "borders": {"riga_a": "row_a", "riga_b": "row_b", **_COMMON},
    "banks": {"gruppi": "groups", **_COMMON},
    "crossings": {"sopra_x": "at_x", "sopra_y": "at_y", "difficolta": "difficulty", **_COMMON},
    "crossings_to_translate": {"lato_a": "side_a", "lato_b": "side_b", "difficolta": "difficulty",
                               **_COMMON},
}


def _rename_keys(obj, table=_legacy.DOCUMENT_KEYS):
    """Every dictionary key of `obj`, recursively, through `table`."""
    if isinstance(obj, dict):
        return {table.get(k, k): _rename_keys(v, table) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename_keys(v, table) for v in obj]
    return obj


def _map(value, table):
    return table.get(value, value) if isinstance(value, str) else value


def _map_keys(d, table):
    return {table.get(k, k): v for k, v in d.items()} if isinstance(d, dict) else d


def translate_features(features):
    """A list of hex features: keys and kinds."""
    out = []
    for f in features or []:
        if isinstance(f, dict):
            f = _rename_keys(f)
            f["kind"] = _map(f.get("kind"), _legacy.FEATURE_KINDS)
        out.append(f)
    return out


def translate_hex(h: dict) -> dict:
    """One hex as stored in the document (keys, status, terrains, features)."""
    h = _rename_keys(h)
    if "status" in h:
        h["status"] = _map(h["status"], _legacy.HEX_STATUS)
    if isinstance(h.get("terrains"), list):
        h["terrains"] = [_map(t, _legacy.TERRAINS) for t in h["terrains"]]
    if h.get("features"):
        h["features"] = translate_features(h["features"])
    site = h.get("work_site")
    if isinstance(site, dict):
        site["commodity"] = _map(site.get("commodity"), _legacy.COMMODITY_IDS)
    return h


def is_legacy_document(doc: dict) -> bool:
    return isinstance(doc, dict) and any(k in doc for k in ("malcontento", "esagoni",
                                                             "caratteristiche", "insediamenti"))


def translate_document(doc: dict) -> dict:
    """A kingdom document written in Italian, as it is now."""
    L = _legacy
    # The roles come first: `maestro` is the Magister here and the Master
    # proficiency everywhere else, and the generic key map knows only one.
    roles = doc.get("ruoli", doc.get("roles"))
    if isinstance(roles, dict):
        doc = {**doc, "ruoli": {L.ROLE_IDS.get(k, k): v for k, v in roles.items()}}
        doc.pop("roles", None)
    d = _rename_keys(doc)
    d["abilities"] = _map_keys(d.get("abilities"), L.ABILITY_IDS)
    d["ruins"] = _map_keys(d.get("ruins"), L.RUIN_IDS)
    if isinstance(d.get("proficiencies"), dict):
        d["proficiencies"] = {L.SKILL_IDS.get(k, k): _map(v, L.PROFICIENCY_IDS)
                              for k, v in d["proficiencies"].items()}
    for key in ("commodities", "storage_extra"):
        d[key] = _map_keys(d.get(key), L.COMMODITY_IDS)
    d["charter"] = _map(d.get("charter"), L.CHARTER_IDS)
    d["charter_free_boost"] = _map(d.get("charter_free_boost"), L.ABILITY_IDS)
    d["government"] = _map(d.get("government"), L.GOVERNMENT_IDS)
    d["government_free_boost"] = _map(d.get("government_free_boost"), L.ABILITY_IDS)
    d["heartland"] = _map(d.get("heartland"), L.HEARTLAND_IDS)
    d["final_boosts"] = [_map(a, L.ABILITY_IDS) for a in d.get("final_boosts") or []]
    d["reputation"] = _map(d.get("reputation"), L.REPUTATION)
    d["current_phase"] = _map(d.get("current_phase"), L.PHASE_IDS)
    d["feats"] = [_map(f, L.FEAT_IDS) for f in d.get("feats") or []]
    d["milestones"] = [_map(m, L.MILESTONE_IDS) for m in d.get("milestones") or []]
    d["turn_activities"] = _map_keys(d.get("turn_activities"), L.ACTIVITY_IDS)
    for m in d.get("modifiers") or []:
        if isinstance(m, dict):
            m["skill"] = _map(m.get("skill"), L.SKILL_IDS)
            m["ability"] = _map(m.get("ability"), L.ABILITY_IDS)
    for s in d.get("settlements") or []:
        if not isinstance(s, dict):
            continue
        s["kind"] = _map(s.get("kind"), L.SETTLEMENT_TYPES)
        if isinstance(s.get("borders"), dict):
            s["borders"] = {L.COMPASS.get(k, k): _map(v, L.SIDE_KINDS)
                            for k, v in s["borders"].items()}
    for entry in d.get("log") or []:
        if isinstance(entry, dict):
            entry["category"] = _map(entry.get("category"), L.LOG_CATEGORIES)
    if isinstance(d.get("hexes"), dict):
        d["hexes"] = {k: translate_hex(h) if isinstance(h, dict) else h
                      for k, h in d["hexes"].items()}
    for key in ("abilities", "ruins", "roles", "commodities", "storage_extra", "turn_activities"):
        if d.get(key) is None:
            d.pop(key, None)
    return d


def _json_column(conn, table, column, fn):
    """Rewrite a JSON column row by row with `fn`."""
    if column not in _columns(conn, table):
        return                     # a table or column this save never had
    rows = conn.execute(f"SELECT rowid, {column} FROM {table}").fetchall()
    for row in rows:
        raw = row[1]
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        new = fn(value)
        conn.execute(f"UPDATE {table} SET {column}=? WHERE rowid=?",
                     (json.dumps(new, ensure_ascii=False, separators=(",", ":")), row[0]))


def _values(conn, table, column, table_map):
    if column not in _columns(conn, table):
        return
    for old, new in table_map.items():
        conn.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new, old))


def _columns(conn, table) -> set:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except Exception:              # pragma: no cover - a table that is not there
        return set()


def _tables(conn) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def upgrade_storage_v27(conn, db_path: Path) -> None:
    """Translate a pre-1.0 database in place. Safe to run twice."""
    tables = _tables(conn)
    if not any(t in tables for t in RENAMED_TABLES):
        return
    backup = Path(db_path).with_name(Path(db_path).name + ".pre-v27.bak")
    if not backup.exists():
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
        import shutil
        shutil.copy2(db_path, backup)
        log.info("copy of the save before the translation: %s", backup.name)
    for index in OLD_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {index}")
    for old, new in RENAMED_TABLES.items():
        if old in tables and new not in tables:
            conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
    for table, cols in RENAMED_COLUMNS.items():
        present = _columns(conn, table)
        if not present:
            continue
        for old, new in cols.items():
            if old in present and new not in present:
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    conn.execute("UPDATE meta SET key='schema_version' WHERE key='schema_versione'")
    L = _legacy
    _json_column(conn, "kingdoms", "document",
                 lambda d: translate_document(d) if isinstance(d, dict) else d)
    _values(conn, "hexes", "status", L.HEX_STATUS)
    _json_column(conn, "hexes", "terrains",
                 lambda v: [_map(t, L.TERRAINS) for t in v] if isinstance(v, list) else v)
    _json_column(conn, "hexes", "features", translate_features)
    _json_column(conn, "hexes", "work_site",
                 lambda s: translate_hex({"work_site": s})["work_site"])
    _json_column(conn, "hexes", "extra", _rename_keys)
    _json_column(conn, "hexes_gm", "hidden_features", translate_features)
    _json_column(conn, "hexes_gm", "hidden_fields",
                 lambda v: [_map(f, L.HIDDEN_FIELDS) for f in v] if isinstance(v, list) else v)
    _values(conn, "hexes_gm", "gm_difficulty", L.DIFFICULTIES)
    _values(conn, "users", "role", L.USER_ROLES)
    _values(conn, "stable", "kind", L.VEHICLE_KINDS)
    _values(conn, "journeys", "status", L.JOURNEY_STATUS)
    _json_column(conn, "journeys", "legs", _rename_keys)
    _values(conn, "log", "category", L.LOG_CATEGORIES)
    _values(conn, "borders", "kind", L.BORDER_KINDS)
    _values(conn, "crossings", "kind", L.BORDER_KINDS)
    _values(conn, "crossings", "difficulty", L.DIFFICULTIES)
    for table in ("borders", "crossings", "banks", "lakes", "currents"):
        _values(conn, table, "source", L.SOURCES)
    conn.commit()
    log.info("save translated to schema 27 (English names)")


ASSET_FOLDERS = {"personaggi": "characters", "veicoli": "vehicles"}
THUMBNAIL_FOLDERS = {"miniature": "thumbnails"}


def rename_asset_folders(assets_dir: Path) -> None:
    """`assets/personaggi` becomes `assets/characters`, and so on: the images
    stay where the app looks for them after the rename."""
    assets_dir = Path(assets_dir)
    if not assets_dir.exists():
        return
    for old, new in ASSET_FOLDERS.items():
        src, dst = assets_dir / old, assets_dir / new
        if src.is_dir() and not dst.exists():
            src.rename(dst)
            log.info("folder %s renamed to %s", old, new)
    for folder in ASSET_FOLDERS.values():
        for old, new in THUMBNAIL_FOLDERS.items():
            src, dst = assets_dir / folder / old, assets_dir / folder / new
            if src.is_dir() and not dst.exists():
                src.rename(dst)
