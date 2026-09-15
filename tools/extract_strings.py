# -*- coding: utf-8 -*-
"""Move the interface texts out of the code and into the language catalogs.

    python tools/extract_strings.py dump  <out_dir>     # one review file per module
    python tools/extract_strings.py apply <out_dir>     # rewrite sources + catalogs

`dump` walks every Python module of the app, finds the string literals that
look like interface text (by context — `ui.label(...)`, `theme.notify(...)`,
`.tooltip(...)` — or by language, since the code was written in Italian) and
writes one review file per module::

    ### 12 kingmaker/ui/login.py:141:22 ui.button
    it: torna a {username}
    en:
    key:

f-strings are shown with named placeholders derived from their expressions.
The reviewer fills `en:` (leaving it empty skips the string) and may set
`key:`; without a key one is derived from the module and the English text.

`apply` re-parses the sources, replaces every accepted literal with
`t("key", name=expr, ...)` (adding the import), and writes the Italian and
English catalogs in `kingmaker/locale/lang/{it,en}.json`, merging with what is there.
It is a one-off tool for release 1.0.0, kept for the record.
"""
from __future__ import annotations

import ast
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "kingmaker"
LANG = APP / "locale" / "lang"

# Calls whose given arguments are texts shown to people: name -> positional
# indices and keyword names that carry text.
TEXT_CALLS = {
    "ui.label": ([0], ["text"]), "ui.button": ([0], ["text"]),
    "ui.input": ([0], ["label", "placeholder"]), "ui.number": ([0], ["label", "placeholder"]),
    "ui.textarea": ([0], ["label", "placeholder"]), "ui.checkbox": ([0], ["text"]),
    "ui.switch": ([0], ["text"]), "ui.select": ([], ["label"]), "ui.radio": ([], ["label"]),
    "ui.toggle": ([], ["label"]), "ui.tab": ([], ["label"]), "ui.expansion": ([0], ["text", "caption"]),
    "ui.tooltip": ([0], ["text"]), "ui.badge": ([0], ["text"]), "ui.chip": ([0], ["text"]),
    "ui.menu_item": ([0], ["text"]), "ui.notify": ([0], ["message"]), "ui.markdown": ([0], ["content"]),
    "ui.upload": ([], ["label"]), "ui.date": ([], ["label"]), "ui.slider": ([], ["label"]),
    "ui.item_label": ([0], ["text"]), "ui.link": ([0], ["text"]), "ui.icon": ([], []),
    "theme.notify": ([0], ["text", "message"]), "theme.title": ([0], ["text"]),
    "theme.stat_box": ([1, 2], ["label", "tooltip"]), "theme.confirm": ([0, 1], ["text", "title"]),
    "theme.hint": ([0], ["text"]),
    "notify": ([0], []), "title": ([0], []),
    "STATE.record": ([0, 2], ["text", "detail"]), "record": ([0, 2], ["text", "detail"]),
    "ValueError": ([0], []), "PermissionError": ([0], []), "RuntimeError": ([0], []),
    "Category": ([], ["reason", "text", "label"]),
}
TEXT_METHODS = {"tooltip": [0], "set_text": [0], "append": [0], "set_label": [0],
                "notify": [0], "set_content": [0]}
# Method calls whose string argument is never text.
SKIP_METHODS = {"props", "classes", "style", "on", "get", "pop", "setdefault", "split",
                "join", "startswith", "endswith", "replace", "strip", "lstrip", "rstrip",
                "execute", "executemany", "executescript", "encode", "decode", "format",
                "debug", "info", "warning", "error", "exception", "critical", "log",
                "bind_value", "bind_visibility", "bind_text", "bind_value_from",
                "bind_value_to", "run_method", "run_javascript", "add_slot", "mark",
                "getattr", "hasattr", "setattr", "compile", "match", "search", "sub",
                "findall", "fullmatch", "read_text", "write_text", "with_name",
                "with_suffix", "joinpath", "index", "count", "find", "rfind",
                "partition", "rpartition", "removeprefix", "removesuffix", "isoformat",
                "strftime", "strptime", "update_user", "update_character", "set_meta",
                "read_meta", "keys", "items", "values"}
SKIP_CALLS = {"getattr", "hasattr", "setattr", "open", "print", "isinstance", "Path",
              "re.compile", "re.match", "re.search", "re.sub", "re.findall", "log.debug",
              "log.info", "log.warning", "log.error", "log.exception", "logging.getLogger",
              "os.environ.get", "environ.get", "ui.run", "ui.run_javascript",
              "ui.add_head_html", "ui.add_body_html", "ui.add_css", "app.add_static_files",
              "app.add_media_files", "ui.page", "ui.image", "ui.interactive_image",
              "ui.keyboard", "ui.timer", "ui.query", "ui.element", "ui.row", "ui.column",
              "ui.card", "ui.grid", "ui.space", "ui.separator", "ui.context_menu",
              "ui.navigate.to", "ui.download", "ui.page_title", "theme.esc", "esc",
              "html.escape", "json.dumps", "json.loads", "dict", "set", "frozenset",
              "sorted", "tuple", "list", "str", "int", "float", "round", "len", "zip",
              "range", "enumerate", "map", "filter", "min", "max", "sum", "any", "all",
              "Slot", "Client", "hexgrid.border_key", "border_key", "node_key",
              "key_text", "STATE.hex", "theme.register_refresh", "register_refresh",
              "theme.requires", "requires", "theme.protected", "protected",
              "permissions.can", "can", "helpers.silence", "_silence", "_set_field",
              "theme.with_prefix", "with_prefix", "theme.refresh_panels", "refresh_panels",
              "theme.mark_dirty", "mark_dirty", "ui.tab_panel", "ui.tabs", "ui.tab_panels",
              "ui.dialog", "theme.dialog", "dialog", "ui.html", "ui.icon"}
SKIP_KWARGS = {"icon", "color", "format", "props", "classes", "style", "name", "key",
               "kind", "category", "id", "mode", "value", "orientation", "sortable",
               "align", "field", "src", "href", "target", "on_change", "on_click",
               "encoding", "sep", "suffix", "prefix", "path", "type", "step", "min",
               "max", "precision", "default", "size", "direction", "status", "source",
               "role", "action", "table", "column", "pattern", "flags", "font", "family"}

ITALIAN_WORDS = {
    "il", "lo", "la", "gli", "le", "un", "una", "uno", "di", "del", "della", "dei",
    "delle", "degli", "dello", "al", "alla", "ai", "alle", "allo", "agli", "da", "dal",
    "dalla", "dai", "dalle", "nel", "nella", "nei", "nelle", "nello", "negli", "con",
    "col", "su", "sul", "sulla", "sui", "sulle", "per", "tra", "fra", "non", "che",
    "chi", "cosa", "come", "dove", "quando", "se", "ma", "anche", "ancora", "già",
    "più", "meno", "molto", "poco", "tutto", "tutti", "tutte", "ogni", "questo",
    "questa", "quello", "quella", "sono", "è", "sei", "ha", "hanno", "essere",
    "avere", "fatto", "senza", "prima", "dopo", "sopra", "sotto", "dentro", "fuori",
    "verso", "nuovo", "nuova", "nome", "regno", "mappa", "viaggio", "giorno",
    "giorni", "esagono", "esagoni", "turno", "attività", "livello", "città", "qui",
    "qua", "là", "così", "solo", "sola", "stesso", "stessa", "altro", "altra",
    "altri", "altre", "nessuno", "nessuna", "niente", "nulla", "può", "puoi",
    "deve", "devi", "vuoi", "vuole", "c'è", "non", "sì", "no", "ok", "oppure",
    "acqua", "fiume", "lago", "ponte", "guado", "sponda", "riva", "confine",
    "personaggio", "personaggi", "gruppo", "compagnia", "veicolo", "veicoli",
    "barca", "carro", "giocatore", "giocatori", "utente", "password", "accesso",
    "salva", "salvato", "annulla", "conferma", "elimina", "modifica", "aggiungi",
    "togli", "chiudi", "apri", "entra", "esci", "crea", "cerca", "scegli",
    "insediamento", "struttura", "strutture", "lotto", "lotti", "talento",
    "talenti", "abilità", "competenza", "malcontento", "rovine", "risorse",
    "commercio", "fama", "infamia", "governo", "regione", "civiche", "terreno",
    "terreni", "colonna", "riga", "vertice", "vertici", "centro", "segnalino",
    "tondo", "freccia", "righello", "piano", "tratta", "tappe", "tappa", "costo",
    "costa", "paga", "pagare", "scende", "risale", "corrente", "verso", "gomma",
    "pennello", "nebbia", "velo", "orologio", "tempo", "ora", "ore", "mese",
    "anno", "settimana", "calendario", "manuale", "regia", "trasporti", "stalla",
    "rimessa", "aggiorna", "aggiornato", "letto", "letta", "scritto", "scritta",
    "vero", "vera", "falso", "falsa", "errore", "avviso", "avvisi", "attenzione",
    "servono", "serve", "manca", "mancano", "troppo", "troppi", "troppe", "pochi",
    "poche", "questi", "queste", "quelli", "quelle", "cui", "quale", "quali",
    "perché", "perche'", "finché", "mentre", "invece", "quindi", "allora",
    "adesso", "subito", "sempre", "mai", "spesso", "bene", "male", "meglio",
    "peggio", "grande", "piccolo", "lungo", "corto", "alto", "basso", "aperto",
    "chiuso", "aperta", "chiusa", "pronto", "pronta", "vuoto", "vuota",
}
ACCENTS = "àèéìòùÀÈÉÌÒÙ"
APOSTROPHE = re.compile(r"\b(l|d|un|c|s|n|dall|nell|all|quell|dell|sull|dov|com|po|e)'[a-zA-Zàèéìòù]", re.I)
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/\\-]*$")


# --------------------------------------------------------------------------
LOOSE = False
STRONG_WORDS = {
    "della", "degli", "delle", "nella", "nelle", "sulla", "sulle", "dal", "dalla", "che",
    "non", "una", "uno", "per", "con", "senza", "anche", "ancora", "dove", "come",
    "quando", "cosa", "tutto", "tutti", "tutte", "ogni", "questo", "questa", "quello",
    "quella", "sono", "essere", "viene", "fatto", "fatta", "prova", "regno", "esagono",
    "esagoni", "viaggio", "acqua", "fiume", "sponda", "sponde", "tratto", "tratti",
    "verso", "tavolo", "wiki", "terreno", "giorno", "giorni", "attivita", "scelta",
    "scelto", "nessun", "nessuno", "nessuna", "niente", "puoi", "devi", "serve",
    "servono", "manca", "solo", "adesso", "prima", "dopo", "ancora", "sempre", "mai",
    "gruppo", "veicolo", "mezzo", "barca", "carro", "personaggio", "personaggi",
    "giocatore", "giocatori", "ruolo", "ruoli", "posti", "pagina", "conta", "contati",
    "inserita", "inserisci", "decisa", "deciso", "categoria", "difficile", "aperto",
    "ferma", "corrente", "monte", "valle", "ponte", "guado", "lago", "confine", "confini",
    "riva", "rive", "segnato", "segnati", "clicca", "cliccare", "scendere", "salire",
    "espandi", "aggiunge", "fase", "scegliere", "consumo", "penalita", "assenza",
    "controllo", "prodotto", "rovina", "malcontento", "fama", "infamia", "turno",
    "livello", "lotti", "lotto", "isolato", "struttura", "strutture", "insediamento",
    "capitale", "citta", "paese", "villaggio", "metropoli", "abilita", "talento",
    "talenti", "risorse", "commercio", "mappa", "griglia", "nebbia", "segnalino",
    "segnalini", "tondo", "freccia", "righello", "piano", "tratta", "tappe", "tappa",
    "costo", "costa", "paga", "quanto", "quanti", "quante", "gente", "chiedi", "chiede",
    "lascia", "lasciare", "vuoto", "vuota", "pieno", "piena", "attivi", "attiva",
    "temporanei", "validi", "magazzino", "persi", "tornano", "aggiunta", "attesa",
    "conferma", "confermare", "compresi", "mano", "secondo", "elenco", "finiscono",
    "circostanza", "esperto", "espansione", "determinata", "nessuna", "decide",
    "risalirlo", "risalgono", "attraversa", "attraversano", "scendere", "fatica",
}


def looks_italian(text: str, loose: bool = False) -> bool:
    """Whether a text was written in Italian (or is worth a look)."""
    if any(ch in ACCENTS for ch in text):
        return True
    if APOSTROPHE.search(text):
        return True
    words = re.findall(r"[a-zA-Zàèéìòù']+", text.lower())
    if not words:
        return False
    if loose and any(w.replace("'", "") in STRONG_WORDS for w in words):
        return True
    hits = sum(1 for w in words if w in ITALIAN_WORDS)
    if len(words) == 1:
        return hits == 1
    return hits >= 1 and hits * 3 >= len(words) or hits >= 2


def is_text_like(text: str, sure: bool = False) -> bool:
    """Rules out ids, paths, CSS and other strings that are never texts.

    In a context that surely carries text (`ui.label(...)`) a single word is
    accepted too; elsewhere a lone identifier-like word is an id.
    """
    if not text or not re.search(r"[A-Za-zàèéìòù]", text):
        return False
    stripped = text.strip()
    if sure:
        return not stripped.startswith(("/", "http", "<"))
    if IDENT.match(stripped) and " " not in stripped and not looks_italian(stripped):
        return False
    if stripped.startswith(("/", "\\", "http", "#", ".", "<style", "<script", "<svg", "<path",
                            "<g ", "<circle", "<rect", "<line", "<text", "<polyline", "<polygon")):
        return False
    if re.match(r"^[\w\-]+(\.[\w\-]+)+$", stripped):        # file.ext, dotted names
        return False
    if re.match(r"^[a-z][a-z0-9_]*(=[^ ]*)?( [a-z][a-z0-9_-]*(=[^ ]*)?)*$", stripped) \
            and not looks_italian(stripped):                # quasar props
        return False
    if re.match(r"^[\w\-]+:\s*[^;]+(;\s*[\w\-]+:\s*[^;]+)*;?$", stripped):   # css
        return False
    if re.match(r"^SELECT|^INSERT|^UPDATE|^DELETE|^CREATE|^PRAGMA|^ALTER|^DROP", stripped, re.I):
        return False
    return True


def call_name(node: ast.AST) -> str:
    """`ui.label`, `theme.notify`, `x.tooltip`... as written."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return call_name(node.func)
    return ""


class Finder(ast.NodeVisitor):
    """Collects the string nodes worth reviewing, with their context."""

    def __init__(self):
        self.parents: list[ast.AST] = []
        self.found: list[tuple[ast.AST, str, str]] = []   # node, context, decision

    def visit(self, node):
        self.parents.append(node)
        super().visit(node)
        self.parents.pop()

    def visit_JoinedStr(self, node):
        self._consider(node)
        # do not descend into the text parts (they are this string), but do
        # look inside the expressions: `f"{x or 'testo'}"` hides a string
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self._consider(node)

    def _consider(self, node):
        parent = self.parents[-2] if len(self.parents) >= 2 else None
        grand = self.parents[-3] if len(self.parents) >= 3 else None
        context, decision = self._context(node, parent, grand)
        if decision != "no":
            self.found.append((node, context, decision))

    def _context(self, node, parent, grand) -> tuple[str, str]:
        """(context label, "yes" | "maybe" | "no")."""
        # docstrings and bare expression statements
        if isinstance(parent, ast.Expr):
            return "docstring", "no"
        # dict keys, subscripts, comparisons, default values: never text
        if isinstance(parent, ast.Dict) and node in parent.keys:
            return "dict-key", "no"
        if isinstance(parent, ast.Subscript) or isinstance(parent, ast.Compare):
            return "key", "no"
        if isinstance(parent, ast.arguments):
            return "default", "no"
        if isinstance(parent, (ast.Assign, ast.AnnAssign)) and isinstance(getattr(parent, "targets", [None])[0], ast.Name):
            name = parent.targets[0].id
            if name.isupper():
                return f"const {name}", "maybe"
        if isinstance(parent, ast.keyword):
            call = grand if isinstance(grand, ast.Call) else None
            fname = call_name(call.func) if call else ""
            short = fname.split(".")[-1]
            if parent.arg in SKIP_KWARGS:
                return f"{fname}({parent.arg}=)", "no"
            if fname in TEXT_CALLS and parent.arg in TEXT_CALLS[fname][1]:
                return f"{fname}({parent.arg}=)", "yes"
            if short in TEXT_CALLS and parent.arg in TEXT_CALLS[short][1]:
                return f"{fname}({parent.arg}=)", "yes"
            return f"{fname}({parent.arg}=)", "maybe"
        if isinstance(parent, ast.Call):
            fname = call_name(parent.func)
            short = fname.split(".")[-1]
            if node in parent.args:
                index = parent.args.index(node)
                if fname in SKIP_CALLS:
                    return fname, "no"
                if isinstance(parent.func, ast.Attribute) and short in SKIP_METHODS:
                    return fname, "no"
                if fname in TEXT_CALLS and index in TEXT_CALLS[fname][0]:
                    return fname, "yes"
                if short in TEXT_CALLS and index in TEXT_CALLS[short][0]:
                    return fname, "yes"
                if isinstance(parent.func, ast.Attribute) and short in TEXT_METHODS \
                        and index in TEXT_METHODS[short]:
                    return fname, "yes"
                return fname, "maybe"
        if isinstance(parent, ast.Dict):
            call = grand if isinstance(grand, ast.Call) else None
            fname = call_name(call.func) if call else ""
            if fname in ("ui.select", "ui.toggle", "ui.radio"):
                return f"{fname}{{}}", "yes"
            # {"name": ..., "label": "Testo"}: a table column
            index = parent.values.index(node) if node in parent.values else -1
            key = parent.keys[index] if index >= 0 else None
            if isinstance(key, ast.Constant) and key.value in ("label", "text", "title", "tooltip"):
                return f"dict[{key.value}]", "yes"
            return "dict-value", "maybe"
        if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Mod):
            return "percent-format", "maybe"
        if isinstance(parent, ast.Attribute):
            return "attribute", "no"
        return type(parent).__name__.lower() if parent else "top", "maybe"


# --------------------------------------------------------------------------
def placeholder_name(expr: ast.AST, used: set) -> str:
    """A readable name for an f-string expression."""
    base = None
    if isinstance(expr, ast.Name):
        base = expr.id
    elif isinstance(expr, ast.Attribute):
        base = expr.attr
    elif isinstance(expr, ast.Subscript):
        sl = expr.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            base = sl.value
        else:
            base = placeholder_name(expr.value, set())
    elif isinstance(expr, ast.Call):
        base = call_name(expr.func).split(".")[-1]
    if not base or not re.match(r"^[A-Za-z_]\w*$", base):
        base = "v"
    base = base.strip("_") or "v"
    name = base
    n = 2
    while name in used:
        name = f"{base}{n}"
        n += 1
    used.add(name)
    return name


def fstring_parts(node: ast.JoinedStr, source: str):
    """The text with `{name}` placeholders and the (name, expression source)
    pairs, in order."""
    used: set = set()
    text = []
    params = []
    for part in node.values:
        if isinstance(part, ast.Constant):
            text.append(str(part.value).replace("{", "{{").replace("}", "}}"))
        elif isinstance(part, ast.FormattedValue):
            name = placeholder_name(part.value, used)
            expr = ast.get_source_segment(source, part.value)
            spec = ""
            if part.format_spec is not None:
                spec = ":" + "".join(str(v.value) for v in part.format_spec.values
                                     if isinstance(v, ast.Constant))
            conv = {-1: "", 115: "!s", 114: "!r", 97: "!a"}[part.conversion]
            text.append("{" + name + conv + spec + "}")
            params.append((name, expr))
    return "".join(text), params


def literal_text(node, source: str):
    if isinstance(node, ast.JoinedStr):
        return fstring_parts(node, source)
    return node.value, []


def module_area(path: Path) -> str:
    rel = path.relative_to(APP).with_suffix("")
    parts = [p for p in rel.parts if p != "ui"]
    return ".".join(parts)


def slug(text: str, words: int = 4) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"\{[^}]*\}", " ", text)
    tokens = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in ("the", "a", "an", "of", "to", "and", "or", "in", "on", "is", "it", "for", "with", "at", "by", "as", "be")]
    return "_".join(tokens[:words]) or "text"


# --------------------------------------------------------------------------
def modules() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if p.name != "__init__.py"
                  and "lang" not in p.parts and p.name != "legacy_names.py"
                  and p.name != "i18n.py")


def dump(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for path in modules():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        finder = Finder()
        finder.visit(tree)
        rows = []
        for node, context, decision in finder.found:
            text, params = literal_text(node, source)
            if not is_text_like(text, sure=decision == "yes"):
                continue
            if decision == "maybe" and not looks_italian(text, LOOSE):
                continue
            if re.match(r"^t\(", ast.get_source_segment(source, node) or ""):
                continue
            rows.append((node, context, text, params))
        if not rows:
            continue
        rel = path.relative_to(ROOT).as_posix()
        lines = []
        for n, (node, context, text, params) in enumerate(rows):
            lines.append(f"### {n} {rel}:{node.lineno}:{node.col_offset} {context}")
            lines.append("it: " + text.replace("\n", "\\n"))
            lines.append("en: ")
            lines.append("key: ")
            lines.append("")
        name = module_area(path).replace(".", "_")
        (out_dir / f"s_{name}.txt").write_text("\n".join(lines), encoding="utf-8")
        total += len(rows)
        print(f"{rel}: {len(rows)}")
    print("total:", total)


def read_review(out_dir: Path) -> dict[str, list[dict]]:
    """file -> rows with line, col, it, en, key (only rows with an `en`).

    The English may be given inside the review file (`en:` / `key:` lines) or
    in a compact answers file `a_<module>.txt` next to it, one string per
    line: `<n>: <english text>` with an optional ` @@ <key>` at the end.
    """
    per_file: dict[str, list[dict]] = {}
    header = re.compile(r"^### (\d+) (\S+):(\d+):(\d+) (.*)$")
    answer = re.compile(r"^(\d+)\s*:\s?(.*?)(?:\s*@@\s*(\S+))?\s*$")
    for txt in sorted(out_dir.glob("s_*.txt")):
        current = None
        rows_here: dict[int, dict] = {}
        for line in txt.read_text(encoding="utf-8").splitlines():
            m = header.match(line)
            if m:
                current = {"file": m.group(2), "line": int(m.group(3)), "col": int(m.group(4)),
                           "it": "", "en": "", "key": ""}
                per_file.setdefault(current["file"], []).append(current)
                rows_here[int(m.group(1))] = current
            elif current is not None and line.startswith("it: "):
                current["it"] = line[4:].replace("\\n", "\n")
            elif current is not None and line.startswith("en:"):
                current["en"] = line[3:].strip().replace("\\n", "\n")
            elif current is not None and line.startswith("key:"):
                current["key"] = line[4:].strip()
        answers = txt.with_name("a_" + txt.name[2:])
        if answers.exists():
            for line in answers.read_text(encoding="utf-8").splitlines():
                m = answer.match(line)
                if not m or int(m.group(1)) not in rows_here:
                    if line.strip():
                        print(f"{answers.name}: unreadable line {line[:40]!r}")
                    continue
                row = rows_here[int(m.group(1))]
                row["en"] = m.group(2).replace("\\n", "\n")
                if m.group(3):
                    row["key"] = m.group(3)
    return per_file


def import_line(path: Path) -> str:
    depth = len(path.relative_to(APP).parts) - 1
    return "from " + "." * (depth + 1) + "i18n import t\n"


def add_import(source: str, path: Path) -> str:
    line = import_line(path)
    if line.strip() in source or re.search(r"^from \.+i18n import .*\bt\b", source, re.M):
        return source
    tree = ast.parse(source)
    last = None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node
        elif last is not None:
            break
    if last is None:
        return line + source
    lines = source.splitlines(keepends=True)
    end = last.end_lineno
    lines.insert(end, line)
    return "".join(lines)


def catalog_only(out_dir: Path) -> None:
    """Writes the catalog entries of every answered row without touching the
    sources: for when the sources were already rewritten but the catalogs
    were not (an interrupted run)."""
    review = read_review(out_dir)
    it_cat = json.loads((LANG / "it.json").read_text(encoding="utf-8")) if (LANG / "it.json").exists() else {}
    en_cat = json.loads((LANG / "en.json").read_text(encoding="utf-8")) if (LANG / "en.json").exists() else {}
    for rel, rows in review.items():
        area = module_area(ROOT / rel)
        used_keys: dict[str, str] = {}
        for row in rows:
            if not row["en"]:
                continue
            text = row["it"]
            key = row["key"] or f"{area}.{slug(row['en'])}"
            if key in used_keys and used_keys[key] != text or key in it_cat and it_cat[key] != text and not row["key"]:
                n = 2
                while f"{key}_{n}" in used_keys or f"{key}_{n}" in it_cat:
                    n += 1
                key = f"{key}_{n}"
            used_keys[key] = text
            it_cat[key] = text
            en_cat[key] = row["en"]
    for name, cat in (("it", it_cat), ("en", en_cat)):
        (LANG / f"{name}.json").write_text(
            json.dumps(dict(sorted(cat.items())), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    print("keys:", len(en_cat))


def apply(out_dir: Path) -> None:
    review = read_review(out_dir)
    it_cat = json.loads((LANG / "it.json").read_text(encoding="utf-8")) if (LANG / "it.json").exists() else {}
    en_cat = json.loads((LANG / "en.json").read_text(encoding="utf-8")) if (LANG / "en.json").exists() else {}
    changed = 0
    for rel, rows in review.items():
        rows = [r for r in rows if r["en"]]
        if not rows:
            continue
        path = ROOT / rel
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        by_pos = {}
        # the quote of the f-string a node sits inside, if any: the key of the
        # replacement must use the other one (Python 3.11 forbids reusing it)
        enclosing_quote: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                segment = ast.get_source_segment(source, node) or ""
                quote = segment.lstrip("fFrRbB")[:1] or '"'
                for part in node.values:
                    if isinstance(part, ast.FormattedValue):
                        for inner in ast.walk(part.value):
                            if isinstance(inner, (ast.JoinedStr, ast.Constant)):
                                enclosing_quote.setdefault(inner, quote)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                by_pos.setdefault((node.lineno, node.col_offset), node)
        area = module_area(path)
        edits = []
        used_keys: dict[str, str] = {}      # key -> it text within this module
        for row in rows:
            node = by_pos.get((row["line"], row["col"]))
            if node is None:
                print(f"{rel}:{row['line']}:{row['col']}: no string there any more")
                continue
            text, params = literal_text(node, source)
            if text != row["it"]:
                print(f"{rel}:{row['line']}: text changed, skipped: {text[:40]!r}")
                continue
            key = row["key"] or f"{area}.{slug(row['en'])}"
            if key in used_keys and used_keys[key] != text or key in it_cat and it_cat[key] != text and not row["key"]:
                n = 2
                while f"{key}_{n}" in used_keys or f"{key}_{n}" in it_cat:
                    n += 1
                key = f"{key}_{n}"
            used_keys[key] = text
            it_cat[key] = text
            en_cat[key] = row["en"]
            quoted = f"'{key}'" if enclosing_quote.get(node) == '"' else f'"{key}"'
            args = ", ".join([quoted] + [f"{n}={e}" for n, e in params])
            edits.append((node, f"t({args})"))
        if not edits:
            continue
        # A string nested in another's expression (`f"{x or 'testo'}"`) is
        # rewritten first; the outer one waits for the next round, when its
        # expression already reads `t(...)`.
        spans = [((e[0].lineno, e[0].col_offset), (e[0].end_lineno, e[0].end_col_offset)) for e in edits]
        outer = [i for i, (a, b) in enumerate(spans)
                 if any(j != i and a <= c and d <= b for j, (c, d) in enumerate(spans))]
        for i in sorted(outer, reverse=True):
            node = edits[i][0]
            print(f"{rel}:{node.lineno}: contains another string, left for the next round")
            del edits[i]
        lines = source.splitlines(keepends=True)
        # offsets: convert (line, col) in utf-8 bytes to character offsets
        starts = []
        pos = 0
        for line in lines:
            starts.append(pos)
            pos += len(line)

        def offset(lineno, col):
            line = lines[lineno - 1]
            return starts[lineno - 1] + len(line.encode("utf-8")[:col].decode("utf-8", "replace"))

        for node, new in sorted(edits, key=lambda e: (e[0].lineno, e[0].col_offset), reverse=True):
            a = offset(node.lineno, node.col_offset)
            b = offset(node.end_lineno, node.end_col_offset)
            source = source[:a] + new + source[b:]
        source = add_import(source, path)
        ast.parse(source)          # must still be valid Python
        path.write_text(source, encoding="utf-8")
        changed += len(edits)
        print(f"{rel}: {len(edits)} strings")
    for name, cat in (("it", it_cat), ("en", en_cat)):
        (LANG / f"{name}.json").write_text(
            json.dumps(dict(sorted(cat.items())), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    print("total:", changed, "| keys:", len(en_cat))


if __name__ == "__main__":
    if "--all" in sys.argv:
        LOOSE = True
        SKIP_CALLS.discard("ui.html")
        sys.argv.remove("--all")
    if len(sys.argv) != 3 or sys.argv[1] not in ("dump", "apply", "catalog"):
        sys.exit(__doc__)
    {"dump": dump, "apply": apply, "catalog": catalog_only}[sys.argv[1]](Path(sys.argv[2]))
