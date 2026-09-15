# -*- coding: utf-8 -*-
"""Dump and re-apply the result labels of a test file.

    python tools/test_labels.py dump tests/test_atoms.py > x.txt
    python tools/test_labels.py apply tests/test_atoms.py x.txt

A label is the first element of the tuple appended to the results list —
`results.append(("what is being checked", condition))` — plus the strings
passed to `print(...)`. Each one is listed under a `### n` marker with its
quotes; `apply` replaces the literal at the same position. The condition is
never touched.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

MARK = "### "


def literals(source: str) -> list[ast.Constant]:
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Tuple) and arg.elts and isinstance(arg.elts[0], ast.Constant) \
                    and isinstance(arg.elts[0].value, str):
                found.append(arg.elts[0])
        elif isinstance(node.func, ast.Name) and node.func.id == "print":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append(arg)
                elif isinstance(arg, ast.JoinedStr):
                    found.append(arg)
    found.sort(key=lambda n: (n.lineno, n.col_offset))
    return found


def _offsets(source: str) -> list[int]:
    out = [0]
    for line in source.splitlines(keepends=True):
        out.append(out[-1] + len(line))
    return out


def _span(node, offsets, lines) -> tuple[int, int]:
    """ast columns are byte offsets in UTF-8: back to characters."""
    def chars(lineno, col_bytes):
        return len(lines[lineno - 1].encode("utf-8")[:col_bytes].decode("utf-8", "ignore"))
    return (offsets[node.lineno - 1] + chars(node.lineno, node.col_offset),
            offsets[node.end_lineno - 1] + chars(node.end_lineno, node.end_col_offset))


def dump(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    offsets = _offsets(source)
    lines = source.splitlines(keepends=True)
    parts = []
    for i, node in enumerate(literals(source)):
        s, e = _span(node, offsets, lines)
        parts.append(f"{MARK}{i}\n{source[s:e]}\n")
    return "\n".join(parts)


def parse_dump(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    current, buf = None, []
    for line in text.splitlines():
        if line.startswith(MARK):
            if current is not None:
                out[current] = "\n".join(buf).strip("\n")
            current = int(line[len(MARK):].split()[0])
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip("\n")
    return out


def apply(path: Path, dump_path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    offsets = _offsets(source)
    lines = source.splitlines(keepends=True)
    nodes = literals(source)
    translated = parse_dump(dump_path.read_text(encoding="utf-8"))
    missing = [i for i in range(len(nodes)) if i not in translated]
    if missing:
        sys.exit(f"{dump_path}: labels missing: {missing[:10]}...")
    changed = 0
    for i in sorted(range(len(nodes)), reverse=True):
        s, e = _span(nodes[i], offsets, lines)
        new = translated[i]
        if new == source[s:e]:
            continue
        try:
            ast.parse("(" + new + ")", mode="eval")
        except SyntaxError:
            sys.exit(f"label {i}: not a valid string literal: {new[:60]}")
        source = source[:s] + new + source[e:]
        changed += 1
    ast.parse(source)
    path.write_text(source, encoding="utf-8", newline="")
    return changed


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "dump":
        sys.stdout.reconfigure(encoding="utf-8")
        print(dump(Path(argv[1])))
        return 0
    if len(argv) >= 3 and argv[0] == "apply":
        n = apply(Path(argv[1]), Path(argv[2]))
        print(f"{argv[1]}: {n} labels rewritten")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
