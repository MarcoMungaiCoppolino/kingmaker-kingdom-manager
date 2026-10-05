# -*- coding: utf-8 -*-
"""Two windows, two languages: every window reads texts and rules in its own.

The catalogs are flat dictionaries of dotted keys; English is the reference
and a missing text falls back to it. The language is a property of the
window, like the identity, so a panel redrawn for another window speaks that
window's language — and the rules tables answer the same way.
"""
import subprocess
import sys

from kingmaker.locale import i18n
from kingmaker import rules, travel
from kingmaker.locale.i18n import t, tn
from kingmaker.ui import hexmap, theme
from kingmaker.ui.hexmap import drawing, ruler

results = []

# --- 1. the catalogs ------------------------------------------------------
results.append(("English is the default", i18n.current() == "en"))
results.append(("a key reads in English", t("tabs.map") == "Map"))
results.append(("and in Italian when asked", i18n.text("tabs.map", "it") == "Mappa"))
results.append(("a missing key shows itself", t("no.such.key") == "no.such.key"))
results.append(("placeholders are filled", t("language.switch_tooltip", language="X") == "Switch the interface to X"))
results.append(("a bad placeholder does not blow up",
              t("language.switch_tooltip", wrong="X") == i18n.text("language.switch_tooltip")))
results.append(("plurals pick the form", tn("drawing.days", 1) == "1 day" and tn("drawing.days", 3) == "3 days"))
results.append(("t_in speaks the language it is given", i18n.tn_in("it", "drawing.days", 3) == "3 giorni"))

# --- 2. what the browser asks for -----------------------------------------
results.append(("Accept-Language is normalised", i18n.normalize("it-IT,it;q=0.9,en;q=0.8") == "it"))
results.append(("an unsupported language is nothing", i18n.normalize("fr-FR,de;q=0.5") is None))
results.append(("the preference wins", i18n.resolve("it", "en", "en") == "it"))
results.append(("then the browser", i18n.resolve(None, "it-CH", "en") == "it"))
results.append(("then the server", i18n.resolve(None, "fr", "it") == "it"))
results.append(("and English last", i18n.resolve(None, None, None) == "en"))

# --- 3. one language per window --------------------------------------------
real_window = theme._window
theme._WINDOWS["fake-it"] = {"lang": "it"}
theme._WINDOWS["fake-en"] = {"lang": "en"}
try:
    theme._window = lambda: "fake-it"
    results.append(("the Italian window reads Italian", t("tabs.map") == "Mappa"))
    results.append(("and its rules tables too", rules.BY_ID["structure"]["brewery"]["name"] == "Distilleria"))
    results.append(("through the derived tables as well",
                  travel.CATEGORIES["open"]["name"] == "Terreno aperto"))
    results.append(("and the vehicles catalogue", rules.BY_ID["vehicle"]["barca_a_remi"]["name"] == "Barca a Remi"))
    theme._window = lambda: "fake-en"
    results.append(("the English window reads English", t("tabs.map") == "Map"))
    results.append(("and its rules tables are the English ones",
                  rules.BY_ID["structure"]["brewery"]["name"] == "Brewery"
                  and rules.BY_ID["vehicle"]["barca_a_remi"]["name"] == "Rowboat"
                  and travel.CATEGORIES["open"]["name"] == "Open terrain"))
    results.append(("the mechanics are the same in both",
                  rules.data("it")["BY_ID"]["structure"]["brewery"]["cost"]
                  == rules.data("en")["BY_ID"]["structure"]["brewery"]["cost"]))

    # The Unrest step's chip of the overcrowded settlements was Italian in
    # every window, and the names went into its HTML as typed.
    from kingmaker.ui.tabs import turn
    from kingmaker.ui.tabs.city import new_settlement
    crowded = [new_settlement('Nova<script>x()</script>')]
    chip_en = turn.overcrowded_chip(crowded)
    theme._window = lambda: "fake-it"
    chip_it = turn.overcrowded_chip(crowded)
    results.append(("the overcrowded chip reads English in an English window",
                  "Overcrowded:" in chip_en and "Residential" in chip_en
                  and "Sovrappopolati" not in chip_en and "Residenziali" not in chip_en))
    results.append(("and Italian in an Italian one",
                  "Sovrappopolati:" in chip_it and "Residenziali" in chip_it))
    results.append(("a settlement's name is escaped in it",
                  "<script>" not in chip_en and "&lt;script&gt;" in chip_en))
finally:
    theme._window = real_window
    theme._WINDOWS.pop("fake-it", None)
    theme._WINDOWS.pop("fake-en", None)


# --- 4. what goes to other windows is rendered for each of them -----------
class FakePlan:
    days, total_cost, max_estimate, possible = 3, 7, False, True


results.append(("the plan label is English by default", drawing.plan_text(FakePlan()) == "7 act · 3 days"))
results.append(("and Italian for an Italian window", drawing.plan_text(FakePlan(), lang="it") == "7 att · 3 giorni"))
results.append(("a trace label is rendered per viewer",
              ruler._label_text(("Aldric", FakePlan(), False), "it") == "Aldric · 7 att · 3 giorni"))
results.append(("and so is its title",
              ruler._title_text({"name": "gm", "verb": "ruler.verb_tracing"}, "it") == "gm sta tracciando"))

# --- 5. the checkers that keep the catalogs whole --------------------------
for tool in ("tools/check_i18n.py", "tools/check_data.py", "tools/check_texts.py"):
    run = subprocess.run([sys.executable, tool], capture_output=True, text=True, encoding="utf-8")
    results.append((f"{tool} finds no problems", run.returncode == 0 and "no problems" in run.stdout))

for name, ok in results:
    print(f"  {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
