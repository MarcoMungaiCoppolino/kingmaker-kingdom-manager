# -*- coding: utf-8 -*-
"""Visible text that bypasses the catalogs.

`check_i18n.py` verifies the catalogs and the `t()` calls; this one looks for
the opposite mistake — a label, a chip or an input caption written as a plain
string (or an f-string with words in it) straight into a `ui.*` / `theme.*`
call, or as the `label` of a table column. Those strings show in one language
only, whatever the viewer chose, and no catalog check can see them.

Usage:  python tools/check_texts.py        (prints the offenders, exit 1 if any)
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACKAGE = os.path.join(ROOT, "kingmaker")

WORDS = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
# markup, CSS declarations, placeholders and class names carry no visible words
NOISE = re.compile(r"<[^>]*>|&[a-z]+;|\{[^}]*\}|km-[\w-]+|var\(--[\w-]+\)|[\w-]+:[^;\"']*;?")
CSS_WORDS = {
    "px", "rem", "span", "div", "style", "class", "font", "size", "color", "auto", "none",
    "solid", "flex", "center", "middle", "left", "right", "top", "bottom", "true", "false",
    "svg", "text", "path", "circle", "rect", "line", "url", "data", "image", "xml", "utf",
    "cinzel", "georgia", "serif", "bold", "normal", "block", "inline", "wrap", "nowrap",
    "pointer", "opacity", "stroke", "fill", "width", "height", "dashed", "dotted",
    "underline", "min", "max", "gap", "items", "row", "col", "full", "dense", "flat",
    "outline", "round", "icon", "props", "cols", "value", "name",
}
KEY = re.compile(r"^[a-z_]+(\.[a-z0-9_]+)+$")          # a catalog key, not a text
KINDS = {"negative", "warning", "info", "positive", "maximized"}
SKIP_CALLS = {
    "ui.run_javascript", "ui.add_head_html", "ui.add_css", "ui.keyboard", "ui.timer",
    "ui.page", "ui.on", "ui.icon", "ui.radio", "ui.run", "theme.register_refresh",
    "theme.requires", "theme.protected", "theme.esc", "theme.with_prefix", "theme.active_tab",
    "theme.stat_panels",
}
SKIP_FILES = {"legacy_names.py", "migrations.py", "archive.py"}
TEXT_KEYWORDS = ("label", "text", "title", "placeholder", "caption")


def visible_words(s: str) -> list[str]:
    rest = NOISE.sub(" ", s)
    return [w for w in WORDS.findall(rest) if w.lower() not in CSS_WORDS]


def call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Attribute):
        base = f.value
        b = base.id if isinstance(base, ast.Name) else (base.attr if isinstance(base, ast.Attribute) else "")
        return f"{b}.{f.attr}"
    return f.id if isinstance(f, ast.Name) else ""


def literal_text(node: ast.AST) -> str | None:
    """The constant part of a string argument, or None if it is not a string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    if isinstance(node, ast.BinOp):
        # only the pieces glued together, not what sits inside a t() call or a subscript
        parts = []
        for side in (node.left, node.right):
            piece = literal_text(side)
            if piece and not KEY.match(piece.strip()):
                parts.append(piece)
        return " ".join(parts) if parts else None
    return None


def check(path: str) -> list[str]:
    problems = []
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    rel = os.path.relpath(path, ROOT)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = call_name(node)
            if not (name.startswith(("ui.", "theme.")) or name in ("notify", "title", "show_result")):
                continue
            if name in SKIP_CALLS or name.startswith("ui.tab"):
                continue
            targets = list(node.args) + [k.value for k in node.keywords if k.arg in TEXT_KEYWORDS]
            for a in targets:
                s = literal_text(a)
                if s is None or s in KINDS or KEY.match(s.strip()):
                    continue
                if visible_words(s) not in ([], ["Kingmaker"]):
                    problems.append(f"{rel}:{node.lineno}: {name}: {s.strip()[:90]!r}")
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value in ("label", "title")
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)
                        and visible_words(v.value)):
                    problems.append(f"{rel}:{node.lineno}: column label: {v.value[:90]!r}")
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    problems = []
    for dirpath, _dirs, files in os.walk(PACKAGE):
        for f in sorted(files):
            if f.endswith(".py") and f not in SKIP_FILES:
                problems.extend(check(os.path.join(dirpath, f)))
    for p in problems:
        print(p)
    print(f"{len(problems)} problems" if problems else "no problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
