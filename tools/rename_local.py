# -*- coding: utf-8 -*-
"""Rename a local variable inside the functions of a file that bind it.

    python tools/rename_local.py <file> <old> <new>

Every function (or lambda) that *binds* `old` — assignment, loop target,
parameter, comprehension — gets every occurrence of `old` inside it renamed,
except where `old` is called as a function (`old(...)`), which is the imported
name being shadowed. Made for the `t` of `i18n` after the string extraction.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def main(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits: set[tuple[int, int]] = set()

    def binds(scope) -> bool:
        for node in ast.walk(scope):
            if isinstance(node, ast.Name) and node.id == old and isinstance(node.ctx, ast.Store):
                return True
            if isinstance(node, ast.arg) and node.arg == old:
                return True
        return False

    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if not binds(scope):
            continue
        called = {id(n.func) for n in ast.walk(scope) if isinstance(n, ast.Call)}
        for node in ast.walk(scope):
            if isinstance(node, ast.Name) and node.id == old and id(node) not in called:
                edits.add((node.lineno, node.col_offset))
            if isinstance(node, ast.arg) and node.arg == old:
                edits.add((node.lineno, node.col_offset))
    for lineno, col in sorted(edits, reverse=True):
        raw = lines[lineno - 1].encode("utf-8")
        assert raw[col:col + len(old)] == old.encode("utf-8"), (lineno, col)
        lines[lineno - 1] = (raw[:col] + new.encode("utf-8") + raw[col + len(old):]).decode("utf-8")
    path.write_text("".join(lines), encoding="utf-8")
    ast.parse("".join(lines))
    print(f"{path}: {len(edits)} occurrences")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
