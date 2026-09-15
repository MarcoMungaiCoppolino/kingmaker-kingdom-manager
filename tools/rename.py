# -*- coding: utf-8 -*-
"""Rename identifiers, keys and files across the project from a CSV map.

    python tools/rename.py tools/rename_map.csv [--kinds name,module,...] [--dry]

The map has the columns `kind,old,new,scope,files` (header required):

kind      what `old` is                          where it is replaced
--------  -------------------------------------  -----------------------------------
module    a Python module name                   import statements and every NAME
                                                 token that resolves to the import
                                                 (the file itself moves with `file`)
name      a Python identifier                    NAME tokens, also inside f-string
                                                 expressions; `scope=var` limits the
                                                 row to bindings that are not an
                                                 imported module, `scope=module` to
                                                 the module
key       a dict/JSON key or an id/enum value    string literals exactly equal to
enum      (same treatment; `enum` rows also      `old` in .py (also inside f-string
          feed the storage migration)            expressions), JSON keys and string
                                                 values, and `\bold\b` in .js
col       a SQL column/table name                `\bold\b` inside .py string
                                                 literals of the listed `files`
wire      a name shared with the browser (JS     `\bold\b` in .js and inside .py
          globals, event names, file names)      string literals
css       a CSS class                            same as `wire`
js        a JavaScript identifier                `\bold\b` in .js only
file      a path relative to the repo root       the file is moved

`files` is a `;`-separated list of path fragments: with it the row applies only
to paths containing one of them. Whole tokens are matched, so `nome` never
touches `nome_utente`: every name needs its own row.

Python is rewritten token by token (tokenize + symtable), never with a blind
regex: a `name` row with `scope=var` leaves alone the `viaggio` that is the
module and renames the `viaggio` that is a local dict, and vice versa.
Comments and docstrings are not touched: they are rewritten by hand afterwards.
After every run: `python -m compileall -q .`, `python tools/check_names.py`
and the test suite.
"""
from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import keyword
import re
import symtable
import sys
import tokenize
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_DIRS = ("kingmaker", "prove", "tests", "docs", "tools")
PY_FILES = ("avvia.py", "avvia_prova.py", "launch.py", "launch_test.py")
JS_DIRS = ("kingmaker",)
JSON_DIRS = ("kingmaker/rules/data", "prove", "tests")
SKIP_PARTS = {"__pycache__", ".git", "scena", "scene", "node_modules"}
SKIP_FILES = {"rename.py", "rename_map.csv"}
# `hexmap.viaggio` is the module, `viaggio.get(...)` the dict: after these
# bases a dotted name is a module.
PACKAGE_BASES = {"hexmap", "mappa", "map", "kingmaker", "ui"}
# Tests name the functions they replace as strings: those strings follow the
# `name` rows too.
NAME_STRING_PATHS = ("prove", "tests")
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
               ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
SCOPE_NAMES = {ast.ListComp: "listcomp", ast.SetComp: "setcomp",
               ast.DictComp: "dictcomp", ast.GeneratorExp: "genexpr", ast.Lambda: "lambda"}


# --------------------------------------------------------------------------- map
class Row:
    __slots__ = ("kind", "old", "new", "scope", "files")

    def __init__(self, kind, old, new, scope="", files=""):
        self.kind, self.old, self.new = kind.strip(), old.strip(), new.strip()
        self.scope = scope.strip()
        self.files = [f.strip() for f in files.split(";") if f.strip()]

    def applies_to(self, path: Path) -> bool:
        if not self.files:
            return True
        p = path.as_posix()
        return any(f in p for f in self.files)


def load_map(path: Path, kinds: set[str] | None) -> list[Row]:
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        for rec in csv.DictReader(fh):
            kind = (rec.get("kind") or "").strip()
            if not kind or kind.startswith("#"):
                continue
            row = Row(kind, rec["old"], rec["new"], rec.get("scope") or "", rec.get("files") or "")
            if kinds and row.kind not in kinds:
                continue
            if row.old == row.new:
                continue
            rows.append(row)
    check_map(rows)
    return rows


def check_map(rows: list[Row]) -> None:
    problems = []
    seen: dict[tuple, Row] = {}
    for r in rows:
        if r.kind in ("name", "module"):
            if not r.new.isidentifier() or keyword.iskeyword(r.new):
                problems.append(f"{r.kind} {r.old}: '{r.new}' is not a valid identifier")
            if not r.old.isidentifier():
                problems.append(f"{r.kind} {r.old}: not an identifier")
        family = "key" if r.kind in ("key", "enum") else r.kind
        key = (family, r.old, r.scope, tuple(r.files))
        if key in seen and seen[key].new != r.new:
            problems.append(f"{r.kind} {r.old}: mapped to both {seen[key].new} and {r.new}")
        seen[key] = r
    if problems:
        sys.exit("map errors:\n  " + "\n  ".join(problems))


# ------------------------------------------------------------------ file lists
def iter_files(suffix: str, dirs, extra=()) -> list[Path]:
    out = []
    for d in dirs:
        base = ROOT / d
        if base.exists():
            for p in sorted(base.rglob(f"*{suffix}")):
                if not (set(p.parts) & SKIP_PARTS) and p.name not in SKIP_FILES:
                    out.append(p)
    for e in extra:
        p = ROOT / e
        if p.exists():
            out.append(p)
    return out


# ------------------------------------------------------------- python scopes
class Scopes:
    """Which symtable scope a source position belongs to, and how a name
    resolves there: 'var' (a binding of this program), 'module' (an imported
    module) or 'unknown'."""

    def __init__(self, source: str, filename: str):
        tree = ast.parse(source, filename)
        self.table = symtable.symtable(source, filename, "exec")
        # (start, end, table) for every nested scope; innermost first at lookup
        self.ranges: list[tuple[tuple[int, int], tuple[int, int], symtable.SymbolTable]] = []
        self._collect(tree, self.table)

    @staticmethod
    def _direct_scopes(node):
        """Scope nodes directly inside `node` (without crossing another scope)."""
        found = []
        stack = list(ast.iter_child_nodes(node))
        while stack:
            n = stack.pop()
            if isinstance(n, SCOPE_NODES):
                found.append(n)
            else:
                stack.extend(ast.iter_child_nodes(n))
        return sorted(found, key=lambda n: (n.lineno, n.col_offset))

    def _collect(self, node, table):
        by_line = defaultdict(list)
        for t in table.get_children():
            by_line[t.get_lineno()].append(t)
        used = set()
        for n in self._direct_scopes(node):
            want = getattr(n, "name", None) or SCOPE_NAMES[type(n)]
            kind = "class" if isinstance(n, ast.ClassDef) else "function"
            match = next((t for t in by_line.get(n.lineno, [])
                          if id(t) not in used and t.get_type() == kind and t.get_name() == want),
                         None)
            if match is None:
                continue
            used.add(id(match))
            self.ranges.append(((n.lineno, n.col_offset), (n.end_lineno, n.end_col_offset), match))
            self._collect(n, match)

    def tables_at(self, line: int, col: int) -> list[symtable.SymbolTable]:
        pos = (line, col)
        inner = [r for r in self.ranges if r[0] <= pos < r[1]]
        inner.sort(key=lambda r: (r[1][0] - r[0][0], r[1][1] - r[0][1]))   # smallest first
        return [r[2] for r in inner] + [self.table]

    def resolve(self, name: str, line: int, col: int) -> str:
        for t in self.tables_at(line, col):
            try:
                sym = t.lookup(name)
            except KeyError:
                continue
            if t.get_type() == "module":
                if sym.is_imported():
                    return "module"
                return "var"
            if sym.is_parameter():
                return "var"
            if sym.is_imported():
                return "module"
            if sym.is_local() and (sym.is_assigned() or sym.is_namespace()):
                return "var"
            # global or free: keep walking outwards
        return "unknown"


# ----------------------------------------------------------- python rewrite
STRING_HEAD = re.compile(r"^([A-Za-z]*)('''|\"\"\"|'|\")")


def split_string_token(tok: str) -> tuple[str, str, str]:
    m = STRING_HEAD.match(tok)
    prefix, quote = m.group(1), m.group(2)
    return prefix, quote, tok[len(prefix) + len(quote):-len(quote)]


def fstring_parts(body: str):
    """Split an f-string body into ('text', s) and ('expr', s) pieces; the
    braces stay in the text pieces, `{{`/`}}` are text."""
    i, n, last = 0, len(body), 0
    while i < n:
        ch = body[i]
        if ch == "{":
            if i + 1 < n and body[i + 1] == "{":
                i += 2
                continue
            depth, j, quote = 1, i + 1, None
            while j < n and depth:
                c = body[j]
                if quote:
                    if c == quote:
                        quote = None
                elif c in "'\"":
                    quote = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                j += 1
            yield "text", body[last:i + 1]
            yield "expr", body[i + 1:j - 1]
            last = j - 1
            i = j
        elif ch == "}" and i + 1 < n and body[i + 1] == "}":
            i += 2
        else:
            i += 1
    yield "text", body[last:]


def expr_head(expr: str) -> int:
    """Length of the expression before a top-level conversion (`!r`) or
    format spec (`:...`)."""
    depth, quote, i, n = 0, None, 0, len(expr)
    while i < n:
        c = expr[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and c == "!" and i + 1 < n and expr[i + 1] in "rsa" and (
                i + 2 == n or expr[i + 2] == ":"):
            return i
        elif depth == 0 and c == ":":
            return i
        i += 1
    return n


class PyRewriter:
    def __init__(self, rows: list[Row]):
        self.name_rows: dict[str, list[Row]] = defaultdict(list)
        self.literal_rows: dict[str, list[Row]] = defaultdict(list)
        self.word_rows: list[Row] = []
        for r in rows:
            if r.kind in ("name", "module"):
                self.name_rows[r.old].append(r)
            elif r.kind in ("key", "enum"):
                self.literal_rows[r.old].append(r)
            elif r.kind in ("wire", "css", "col"):
                self.word_rows.append(r)
        self.warnings: list[str] = []
        self._word_cache: dict[Path, re.Pattern | None] = {}

    # ---- lookups
    def new_name(self, old: str, binding: str, path: Path, in_import: bool) -> str | None:
        rows = [r for r in self.name_rows.get(old, ()) if r.applies_to(path)]
        if not rows:
            return None
        module_rows = [r for r in rows if r.kind == "module" or r.scope == "module"]
        var_rows = [r for r in rows if r.scope == "var"]
        any_rows = [r for r in rows if r.kind == "name" and not r.scope]
        if in_import or binding == "module":
            if module_rows:
                return module_rows[0].new
            return any_rows[0].new if any_rows else None
        if var_rows:
            return var_rows[0].new
        if any_rows:
            return any_rows[0].new
        return None                      # only a module row, but this is a variable

    def new_literal(self, old: str, path: Path) -> str | None:
        rows = self.literal_rows.get(old)
        if not rows:
            if any(part in NAME_STRING_PATHS for part in path.parts) and old.isidentifier():
                plain = [r for r in self.name_rows.get(old, ()) if r.kind == "name" and not r.scope]
                return plain[0].new if plain else None
            return None
        for r in rows:
            if r.files and r.applies_to(path):
                return r.new
        for r in rows:
            if not r.files:
                return r.new
        return None

    def words_in_string(self, body: str, path: Path) -> str:
        if path not in self._word_cache:
            table = {}
            for r in self.word_rows:
                if r.applies_to(path):
                    table.setdefault(r.old, r.new)
            self._word_cache[path] = (re.compile(
                r"(?<![A-Za-z0-9_])(" + "|".join(
                    re.escape(k) for k in sorted(table, key=len, reverse=True)) + r")(?![A-Za-z0-9_])"),
                table) if table else None
        cached = self._word_cache[path]
        if not cached:
            return body
        pattern, table = cached
        return pattern.sub(lambda m: table[m.group(1)], body)

    # ---- one file
    def rewrite(self, path: Path, source: str) -> str:
        try:
            scopes = Scopes(source, str(path))
        except SyntaxError as e:
            self.warnings.append(f"{path}: not parsed ({e})")
            return source
        edits: list[tuple[tuple[int, int], tuple[int, int], str]] = []
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
        existing = {t.string for t in toks if t.type == tokenize.NAME}
        applied: dict[str, str] = {}
        logical_start, in_import, prev_sig = True, False, None
        for idx, tok in enumerate(toks):
            if tok.type == tokenize.NEWLINE:
                logical_start, in_import, prev_sig = True, False, None
                continue
            if tok.type in (tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT,
                            tokenize.ENDMARKER):
                continue
            if logical_start:
                in_import = tok.type == tokenize.NAME and tok.string in ("import", "from")
                logical_start = False
            if tok.type == tokenize.NAME and not keyword.iskeyword(tok.string):
                after_dot = prev_sig is not None and prev_sig.type == tokenize.OP and prev_sig.string == "."
                nxt = toks[idx + 1] if idx + 1 < len(toks) else None
                is_kwarg = (nxt is not None and nxt.type == tokenize.OP and nxt.string == "="
                            and prev_sig is not None and prev_sig.type == tokenize.OP
                            and prev_sig.string in ("(", ","))
                base = toks[idx - 2].string if after_dot and idx >= 2 else None
                if in_import or (after_dot and base in PACKAGE_BASES):
                    binding = "module"
                elif after_dot or is_kwarg:
                    binding = "var"
                else:
                    binding = scopes.resolve(tok.string, tok.start[0], tok.start[1])
                new = self.new_name(tok.string, binding, path, in_import)
                if new is not None and new != tok.string:
                    edits.append((tok.start, tok.end, new))
                    applied[tok.string] = new
            elif tok.type == tokenize.STRING:
                new = self.rewrite_string(tok, path, scopes)
                if new is not None and new != tok.string:
                    edits.append((tok.start, tok.end, new))
            prev_sig = tok
        self._check_scopes(path, scopes, applied)
        return apply_edits(source, edits)

    def _check_scopes(self, path: Path, scopes: Scopes, applied: dict[str, str]) -> None:
        """A real collision: `old` and its `new` are both bound in the same
        scope (attributes and keyword names are not symbols, so a local
        `value` next to `el.value` is fine)."""
        if not applied:
            return
        tables = [scopes.table] + [r[2] for r in scopes.ranges]
        for t in tables:
            bound = {s.get_name() for s in t.get_symbols()
                     if s.is_assigned() or s.is_parameter() or s.is_imported() or s.is_namespace()}
            for old, new in applied.items():
                if old in bound and new in bound and new not in applied:
                    self.warnings.append(
                        f"{path.relative_to(ROOT)}: scope {t.get_name()}: {old} -> {new} but {new} is bound there")
            by_new: dict[str, list[str]] = defaultdict(list)
            for old, new in applied.items():
                if old in bound:
                    by_new[new].append(old)
            for new, olds in by_new.items():
                if len(olds) > 1:
                    self.warnings.append(
                        f"{path.relative_to(ROOT)}: scope {t.get_name()}: {' and '.join(sorted(olds))} both -> {new}")

    def rewrite_string(self, tok, path: Path, scopes: Scopes) -> str | None:
        prefix, quote, body = split_string_token(tok.string)
        if "f" in prefix.lower():
            out = []
            for kind, piece in fstring_parts(body):
                if kind == "text":
                    out.append(self.words_in_string(piece, path))
                else:
                    head = expr_head(piece)
                    out.append(self.rewrite_expr(piece[:head], path, scopes, tok.start) + piece[head:])
            return prefix + quote + "".join(out) + quote
        if len(quote) == 3 and "\n" in body:
            # docstrings and long texts are rewritten by hand; SQL and JS
            # blocks still get their column and wire names
            new_body = self.words_in_string(body, path)
            return prefix + quote + new_body + quote if new_body != body else None
        new = self.new_literal(body, path)
        if new is not None:
            return prefix + quote + new + quote
        new_body = self.words_in_string(body, path)
        return prefix + quote + new_body + quote if new_body != body else None

    def rewrite_expr(self, expr: str, path: Path, scopes: Scopes, pos) -> str:
        try:
            toks = list(tokenize.generate_tokens(io.StringIO(expr).readline))
        except (tokenize.TokenError, SyntaxError, IndentationError):
            return expr
        line_starts = [0]
        for i, ch in enumerate(expr):
            if ch == "\n":
                line_starts.append(i + 1)

        def off(p):
            return line_starts[p[0] - 1] + p[1] if p[0] - 1 < len(line_starts) else len(expr)

        pieces, last, prev_sig = [], 0, None
        for tok in toks:
            if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.COMMENT):
                continue
            new = None
            if tok.type == tokenize.NAME and not keyword.iskeyword(tok.string):
                after_dot = prev_sig is not None and prev_sig.string == "."
                binding = "var" if after_dot else scopes.resolve(tok.string, pos[0], pos[1])
                new = self.new_name(tok.string, binding, path, False)
            elif tok.type == tokenize.STRING:
                p, q, b = split_string_token(tok.string)
                lit = self.new_literal(b, path)
                if lit is not None:
                    new = p + q + lit + q
            if new is not None and new != tok.string:
                s, e = off(tok.start), off(tok.end)
                pieces.append(expr[last:s])
                pieces.append(new)
                last = e
            prev_sig = tok
        pieces.append(expr[last:])
        return "".join(pieces)


def apply_edits(source: str, edits) -> str:
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))
    out, last = [], 0
    for (l0, c0), (l1, c1), new in sorted(edits):
        s, e = offsets[l0 - 1] + c0, offsets[l1 - 1] + c1
        if s < last:
            continue
        out.append(source[last:s])
        out.append(new)
        last = e
    out.append(source[last:])
    return "".join(out)


# --------------------------------------------------------------- js and json
def rewrite_words(text: str, rows: list[Row], path: Path) -> str:
    table = {}
    for r in rows:
        if r.applies_to(path):
            table.setdefault(r.old, r.new)
    if not table:
        return text
    pattern = re.compile(r"(?<![A-Za-z0-9_$])(" + "|".join(
        re.escape(k) for k in sorted(table, key=len, reverse=True)) + r")(?![A-Za-z0-9_$])")
    return pattern.sub(lambda m: table[m.group(1)], text)


def rewrite_json(text: str, rows: list[Row], path: Path) -> str:
    table = {}
    for r in rows:
        if r.applies_to(path):
            table.setdefault(r.old, r.new)
    if not table:
        return text
    data = json.loads(text)
    changed = False

    def walk(obj):
        nonlocal changed
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                nk = table.get(k, k)
                changed |= nk != k
                out[nk] = walk(v)
            return out
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        if isinstance(obj, str) and obj in table:
            changed = True
            return table[obj]
        return obj

    new = walk(data)
    if not changed:
        return text
    m = re.search(r"\n( +)\"", text)
    indent = len(m.group(1)) if m else 1
    return json.dumps(new, ensure_ascii=False, indent=indent) + "\n"


# --------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map")
    ap.add_argument("--kinds", default="", help="comma-separated kinds to apply")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args(argv)
    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()} or None
    rows = load_map(Path(args.map), kinds)
    py_rows = [r for r in rows if r.kind in ("name", "module", "key", "enum", "wire", "css", "col")]
    js_rows = [r for r in rows if r.kind in ("js", "key", "enum", "wire", "css")]
    json_rows = [r for r in rows if r.kind in ("key", "enum")]
    file_rows = [r for r in rows if r.kind == "file"]

    changed = 0
    rewriter = PyRewriter(py_rows)
    for path in iter_files(".py", PY_DIRS, PY_FILES):
        src = path.read_text(encoding="utf-8")
        new = rewriter.rewrite(path, src)
        if new != src:
            changed += 1
            if not args.dry:
                path.write_text(new, encoding="utf-8", newline="")
    for path in iter_files(".js", JS_DIRS):
        src = path.read_text(encoding="utf-8")
        words = set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", src))
        table = {}
        for r in js_rows:
            if r.applies_to(path):
                table.setdefault(r.old, r.new)
        for old, new in table.items():
            if old in words and new in words and new not in table:
                rewriter.warnings.append(f"{path.relative_to(ROOT)}: {old} -> {new} but {new} already exists")
        new = rewrite_words(src, js_rows, path)
        if new != src:
            changed += 1
            if not args.dry:
                path.write_text(new, encoding="utf-8", newline="")
    for path in iter_files(".json", JSON_DIRS):
        src = path.read_text(encoding="utf-8")
        try:
            new = rewrite_json(src, json_rows, path)
        except json.JSONDecodeError:
            continue
        if new != src:
            changed += 1
            if not args.dry:
                path.write_text(new, encoding="utf-8", newline="\n")
    for r in file_rows:
        src, dst = ROOT / r.old, ROOT / r.new
        if src.exists():
            changed += 1
            if not args.dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
        elif not dst.exists():
            rewriter.warnings.append(f"file {r.old}: not found")
    for w in rewriter.warnings:
        print("warning:", w)
    print(f"{'would change' if args.dry else 'changed'} {changed} files with {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
