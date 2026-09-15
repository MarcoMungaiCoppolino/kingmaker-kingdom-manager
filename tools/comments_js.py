# -*- coding: utf-8 -*-
"""Dump and re-apply the comments of a JavaScript file (see `comments.py`).

    python tools/comments_js.py dump kingmaker/ui/static/travel_drag.js > x.txt
    python tools/comments_js.py apply kingmaker/ui/static/travel_drag.js x.txt

Blocks are runs of full-line `//` comments, trailing `//` comments and
`/* ... */` blocks. Comment markers inside string and template literals are
ignored. Code is never touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARK = "### "


def _comment_spans(source: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) of every comment, kind 'line' or 'block'.

    Strings and template literals are skipped, `${...}` inside a template
    included: a nested template in there must not flip the quote state.
    """
    spans: list[tuple[int, int, str]] = []
    n = len(source)

    def skip_string(i: int, quote: str) -> int:
        i += 1
        while i < n:
            c = source[i]
            if c == "\\":
                i += 2
                continue
            if c == quote:
                return i + 1
            if quote == "`" and c == "$" and source[i + 1:i + 2] == "{":
                i = scan_code(i + 2, stop_at_brace=True)
                continue
            i += 1
        return n

    def skip_regex(i: int) -> int:
        """A regex literal: quotes inside it are not strings."""
        i += 1
        in_class = False
        while i < n:
            c = source[i]
            if c == "\\":
                i += 2
                continue
            if in_class:
                if c == "]":
                    in_class = False
            elif c == "[":
                in_class = True
            elif c == "/":
                return i + 1
            elif c == "\n":
                return i
            i += 1
        return n

    def scan_code(i: int, stop_at_brace: bool = False) -> int:
        depth = 0
        while i < n:
            c = source[i]
            if c in "'\"`":
                i = skip_string(i, c)
                continue
            if c == "/" and source[i + 1:i + 2] == "/":
                j = source.find("\n", i)
                j = n if j < 0 else j
                spans.append((i, j, "line"))
                i = j
                continue
            if c == "/" and source[i + 1:i + 2] == "*":
                j = source.find("*/", i + 2)
                j = n if j < 0 else j + 2
                spans.append((i, j, "block"))
                i = j
                continue
            if c == "/" and _regex_starts_here(source, i):
                i = skip_regex(i)
                continue
            if stop_at_brace:
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 0:
                        return i + 1
                    depth -= 1
            i += 1
        return n

    scan_code(0)
    spans.sort()
    return spans


_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")


def _regex_starts_here(source: str, i: int) -> bool:
    """A `/` opens a regex when what precedes it cannot end an expression."""
    j = i - 1
    while j >= 0 and source[j] in " \t":
        j -= 1
    if j < 0 or source[j] in _REGEX_BEFORE or source[j] == "\n":
        return True
    k = j
    while k >= 0 and (source[k].isalnum() or source[k] == "_"):
        k -= 1
    word = source[k + 1:j + 1]
    return word in ("return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw")


def blocks(source: str) -> list[dict]:
    line_start = [0]
    for idx, ch in enumerate(source):
        if ch == "\n":
            line_start.append(idx + 1)

    def line_of(pos):
        lo, hi = 0, len(line_start) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_start[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    out: list[dict] = []
    run: list[tuple[int, int]] = []

    def flush():
        if run:
            s = line_start[line_of(run[0][0])]
            e = run[-1][1]
            out.append({"kind": "comment", "start": s, "end": e, "text": source[s:e]})
            run.clear()

    for s, e, kind in _comment_spans(source):
        ln = line_of(s)
        full_line = source[line_start[ln]:s].strip() == ""
        if kind == "line" and full_line:
            if run and line_of(run[-1][0]) != ln - 1:
                flush()
            run.append((s, e))
        else:
            flush()
            if kind == "block" and full_line:
                s2 = line_start[ln]
                out.append({"kind": "block", "start": s2, "end": e, "text": source[s2:e]})
            else:
                out.append({"kind": "inline", "start": s, "end": e, "text": source[s:e]})
    flush()
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
    changed = 0
    for i in sorted(range(len(found)), reverse=True):
        b = found[i]
        new = translated[i].strip("\n")
        if new == b["text"].rstrip("\n"):
            continue
        if b["kind"] == "comment" and any(
                l.strip() and not l.lstrip().startswith("//") for l in new.splitlines()):
            sys.exit(f"block {i}: every comment line must start with //")
        if b["kind"] == "inline" and not (new.lstrip().startswith("//") or (
                new.lstrip().startswith("/*") and new.rstrip().endswith("*/"))):
            sys.exit(f"block {i}: an inline comment must be // or /* */")
        if b["kind"] == "block" and not (new.lstrip().startswith("/*") and new.rstrip().endswith("*/")):
            sys.exit(f"block {i}: a block comment must keep /* */")
        source = source[:b["start"]] + new + source[b["end"]:]
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
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
