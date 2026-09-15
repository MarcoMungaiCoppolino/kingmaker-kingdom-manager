# -*- coding: utf-8 -*-
"""Download the Kingmaker entries of Archives of Nethys, for the English texts.

    python tools/fetch_aon.py <out_dir>

Queries the public search index of Archives of Nethys
(https://elasticsearch.aonprd.com) and saves one JSON file per kind, with
the raw `_source` of every hit: kingdom structures, kingdom activities (the
actions with the Leadership, Region, Civic, Commerce, Upkeep and Army traits),
kingdom feats, vehicles and the rules pages of the Kingmaker Adventure Path.
The texts are OGL / Community Use Policy content by Paizo; the transcription
into `kingmaker/rules/data/lang/en/` is done by `tools/aon_to_texts.py`.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://elasticsearch.aonprd.com/aon/_search"
QUERIES = {
    "structures": "category:kingdom-structure",
    "activities": "category:action AND (trait:Leadership OR trait:Region OR trait:Civic "
                  "OR trait:Commerce OR trait:Upkeep OR trait:Army)",
    "feats": "category:feat AND trait:Kingdom",
    "vehicles": "category:vehicle",
    "rules": "category:rules AND source:Kingmaker*",
}


def fetch(query: str, size: int = 300) -> list[dict]:
    url = f"{ENDPOINT}?q={urllib.parse.quote(query)}&size={size}"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hits = payload["hits"]["hits"]
    return [h["_source"] for h in hits]


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, query in QUERIES.items():
        rows = fetch(query)
        (out_dir / f"{kind}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{kind}: {len(rows)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
