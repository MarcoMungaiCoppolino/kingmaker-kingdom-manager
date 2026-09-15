# -*- coding: utf-8 -*-
"""Dump and re-apply the comments and docstrings of a Python module.

    python tools/comments.py dump kingmaker/rules.py > rules.txt
    ... translate rules.txt, keeping every `### n` marker ...
    python tools/comments.py apply kingmaker/rules.py rules.txt

The dump lists every block that is prose: a docstring, a run of full-line
comments, or a trailing comment, each under a `### <n> <kind>` marker with its
original indentation. `apply` replaces block n with the text that follows its
marker, so a translation can be longer or shorter than the original. Code is
never touched: the tool only ever rewrites comment tokens and docstrings.
"""
from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

MARK = "### "


def _docstring_positions(source: str) -> set[tuple[int, int]]:
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                found.add((body[0].value.lineno, body[0].value.col_offset))
    return found


def blocks(source: str) -> list[dict]:
    """Every prose block: {'kind', 'start': (line, col), 'end': (line, col), 'text'}."""
    lines = source.splitlines(keepends=True)
    docs = _docstring_positions(source)
    out: list[dict] = []
    run: list = []          # consecutive full-line comments

    def flush():
        if run:
            first, last = run[0], run[-1]
            text = "".join(lines[first.start[0] - 1:last.end[0]])
            out.append({"kind": "comment", "start": (first.start[0], 0),
                        "end": (last.end[0], len(lines[last.end[0] - 1].rstrip("\r\n"))),
                        "text": text})
            run.clear()

    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            full_line = tok.line[:tok.start[1]].strip() == ""
            if full_line:
                if run and tok.start[0] != run[-1].start[0] + 1:
                    flush()
                run.append(tok)
            else:
                flush()
                out.append({"kind": "inline", "start": tok.start, "end": tok.end, "text": tok.string})
        elif tok.type == tokenize.STRING and tok.start in docs:
            flush()
            out.append({"kind": "docstring", "start": tok.start, "end": tok.end, "text": tok.string})
        elif tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            continue
        else:
            flush()
    flush()
    out.sort(key=lambda b: b["start"])
    return out


def dump(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    parts = []
    for i, b in enumerate(blocks(source)):
        parts.append(f"{MARK}{i} {b['kind']}\n{b['text'].rstrip(chr(10))}\n")
    return "\n".join(parts)


def parse_dump(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    current, buf = None, []
    for line in text.splitlines():
        if line.startswith(MARK):
            if current is not None:
                out[current] = "\n".join(buf).rstrip("\n")
            current = int(line[len(MARK):].split()[0])
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).rstrip("\n")
    return out


def apply(path: Path, dump_path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    translated = parse_dump(dump_path.read_text(encoding="utf-8"))
    found = blocks(source)
    missing = [i for i in range(len(found)) if i not in translated]
    if missing:
        sys.exit(f"{dump_path}: blocks missing: {missing[:10]}...")
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))
    changed = 0
    for i in sorted(range(len(found)), reverse=True):
        b = found[i]
        new = translated[i].strip("\n")
        old = b["text"].rstrip("\n")
        if new == old:
            continue
        if b["kind"] == "docstring" and not (new.startswith(('"""', "'''", 'r"""')) and new.endswith(('"""', "'''"))):
            sys.exit(f"block {i}: a docstring must keep its quotes")
        if b["kind"] in ("comment", "inline") and any(
                l.strip() and not l.lstrip().startswith("#") for l in new.splitlines()):
            sys.exit(f"block {i}: every comment line must start with #")
        s = offsets[b["start"][0] - 1] + b["start"][1]
        e = offsets[b["end"][0] - 1] + b["end"][1]
        source = source[:s] + new + source[e:]
        changed += 1
    path.write_text(source, encoding="utf-8", newline="")
    return changed


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "dump":
        sys.stdout.reconfigure(encoding="utf-8")
        print(dump(Path(argv[1])))
        return 0
    if len(argv) >= 3 and argv[0] == "apply":
        n = apply(Path(argv[1]), Path(argv[2]))
        print(f"{argv[1]}: {n} blocks rewritten")
        compile(Path(argv[1]).read_text(encoding="utf-8"), argv[1], "exec")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
