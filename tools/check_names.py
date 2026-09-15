# -*- coding: utf-8 -*-
"""Static check: every name referenced in the package must be defined.

Walks every symbol table of every module under `kingmaker/` (and `tests/` if
present) and reports names that are read as globals but are neither module
globals, imports nor builtins. It is the check that keeps a rename or a module
split honest: a NameError in a panel that no test renders would otherwise
surface only when someone clicks it.

    python tools/check_names.py          # exit code 1 if anything is undefined
"""
import builtins
import pathlib
import symtable
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_NAMES = {"__file__", "__name__", "__doc__", "__spec__", "__package__", "__builtins__"}


def undefined_names(path: pathlib.Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    table = symtable.symtable(text, str(path), "exec")
    globals_ = {s.get_name() for s in table.get_symbols()
                if s.is_assigned() or s.is_imported() or s.is_namespace()}
    found: list[tuple[str, str]] = []

    def visit(tab) -> None:
        for sym in tab.get_symbols():
            if not sym.is_referenced():
                continue
            if tab.get_type() == "module":
                is_global = not (sym.is_assigned() or sym.is_imported() or sym.is_namespace())
            else:
                is_global = sym.is_global()
            if not is_global:
                continue
            name = sym.get_name()
            if name in globals_ or name in SKIP_NAMES or hasattr(builtins, name):
                continue
            found.append((tab.get_name(), name))
        for child in tab.get_children():
            visit(child)

    visit(table)
    return found


def main(folders: list[str]) -> int:
    problems = []
    for folder in folders:
        base = ROOT / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for scope, name in undefined_names(path):
                problems.append(f"{path.relative_to(ROOT)}: {scope}: {name}")
    if problems:
        print("\n".join(problems))
        print(f"{len(problems)} undefined name(s)")
        return 1
    print("no undefined names")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["kingmaker", "tests", "prove", "docs"]))
