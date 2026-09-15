# -*- coding: utf-8 -*-
"""Checks on the language catalogs and on how the code uses them.

    python tools/check_i18n.py

- every key used in `t("...")` / `tn("...")` calls exists in `lang/en.json`;
- every key of `it.json` exists in `en.json` and vice versa (no orphans);
- the `{placeholders}` of a key are the same in both languages;
- no function that calls `t(...)` also binds a local named `t` (it would
  shadow the import and blow up at runtime);
- no `t(...)` call sits at module level, where it would be evaluated once at
  import time in a single language.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "kingmaker"
LANG = APP / "locale" / "lang"
PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*)(?:![rsa])?(?::[^}]*)?\}")


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text.replace("{{", "").replace("}}", "")))


def main() -> int:
    problems = []
    en = json.loads((LANG / "en.json").read_text(encoding="utf-8"))
    it = json.loads((LANG / "it.json").read_text(encoding="utf-8"))
    for key in sorted(set(it) - set(en)):
        problems.append(f"it.json: key {key!r} missing from en.json")
    for key in sorted(set(en) - set(it)):
        problems.append(f"en.json: key {key!r} missing from it.json")
    for key in sorted(set(en) & set(it)):
        if placeholders(en[key]) != placeholders(it[key]):
            problems.append(f"{key!r}: placeholders differ: en {sorted(placeholders(en[key]))}"
                            f" vs it {sorted(placeholders(it[key]))}")
    used: set[str] = set()
    prefixes: set[str] = set()      # t(f"prefix.{x}"): every key under it is used
    for path in sorted(APP.rglob("*.py")):
        if path.name == "i18n.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # a key written as a plain string (a table of keys looked up later,
        # in any module: `units.PACE_KEYS`, `Archive.INSPECT_ERRORS`) counts
        # as used too
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in en:
                used.add(node.value)
        if not re.search(r"\bfrom (?:\.+|kingmaker\.locale\.)i18n import\b", source):
            continue
        rel = path.relative_to(ROOT).as_posix()
        # module-level calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in ("t", "tn") and node.args \
                    and isinstance(node.args[0], ast.JoinedStr):
                first = node.args[0].values[0]
                if isinstance(first, ast.Constant):
                    prefixes.add(str(first.value))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in ("t", "tn") and node.args \
                    and isinstance(node.args[0], ast.Constant):
                key = node.args[0].value
                used.add(key)
                if node.func.id == "t" and key not in en:
                    problems.append(f"{rel}:{node.lineno}: unknown key {key!r}")
                if node.func.id == "tn" and (f"{key}.one" not in en or f"{key}.other" not in en):
                    problems.append(f"{rel}:{node.lineno}: plural key {key!r} needs .one and .other")
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                            and sub.func.id in ("t", "tn") and not any(
                                isinstance(p, (ast.FunctionDef, ast.Lambda, ast.AsyncFunctionDef))
                                for p in ast.walk(node) if p is not sub and sub in ast.walk(p)):
                        problems.append(f"{rel}:{sub.lineno}: t() at module level (evaluated once at import)")
        # shadowed `t`
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                binds = set()
                args = node.args
                for a in args.args + args.kwonlyargs + args.posonlyargs:
                    binds.add(a.arg)
                if args.vararg:
                    binds.add(args.vararg.arg)
                if args.kwarg:
                    binds.add(args.kwarg.arg)
                calls = False
                for sub in ast.walk(node):
                    if sub is node:
                        continue
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store) and sub.id == "t":
                        binds.add("t")
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "t":
                        calls = True
                if "t" in binds and calls:
                    problems.append(f"{rel}:{node.lineno}: local `t` shadows the i18n import")
    for key in sorted(set(en) - used):
        if not key.endswith((".one", ".other")) and not any(key.startswith(p) for p in prefixes):
            problems.append(f"en.json: key {key!r} is not used by any t() call")
    for line in problems:
        print(line)
    print("no problems" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
