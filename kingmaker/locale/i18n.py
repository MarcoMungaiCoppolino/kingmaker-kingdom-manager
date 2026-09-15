# -*- coding: utf-8 -*-
"""The interface in the viewer's language.

Every text the interface shows goes through `t("some.key")`: the catalogs in
`kingmaker/locale/lang/<code>.json` are flat dictionaries of dotted keys, one file
per language, and English is the reference — a key missing from a language
falls back to the English text, and a key missing everywhere shows itself,
so a hole is visible instead of silent.

The language is *per window*, not global: two players at the same table may
look at the same kingdom in two languages. Whoever draws a page tells this
module how to find the window's language (`language_resolver`), and `theme`
sets it from the window state — the same trick as `theme.user()`, so a panel
redrawn for another window speaks that window's language.

Plurals: `tn("travel.days", n)` picks `travel.days.one` or `travel.days.other`
and passes `n` as a placeholder. Both languages supported so far have the
same two forms.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("kingmaker.i18n")

LANGUAGES = ("en", "it")
DEFAULT = "en"
NAMES = {"en": "English", "it": "Italiano"}
LANG_DIR = Path(__file__).resolve().parent / "lang"

# Set by `theme`: answers with the language of the window being drawn, or
# None when nobody is drawing (background work, tests).
language_resolver: Callable[[], str | None] = lambda: None

_catalogs: dict[str, dict[str, str]] = {}


def catalog(lang: str) -> dict[str, str]:
    """The texts of one language, read once from disk."""
    if lang not in _catalogs:
        path = LANG_DIR / f"{lang}.json"
        try:
            _catalogs[lang] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _catalogs[lang] = {}
    return _catalogs[lang]


def reload() -> None:
    """Forgets the catalogs read so far (the tests edit them)."""
    _catalogs.clear()


def normalize(code: str | None) -> str | None:
    """A supported language code out of something like `it-IT` or an
    `Accept-Language` header, or None if nothing in there is supported."""
    if not code:
        return None
    for part in str(code).split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        base = tag.split("-")[0]
        if base in LANGUAGES:
            return base
    return None


def resolve(preferred: str | None, accept_language: str | None = None,
            fallback: str | None = None) -> str:
    """The language to use: the stated preference, then the browser's, then
    the server's default, then English."""
    for candidate in (preferred, accept_language, fallback):
        found = normalize(candidate)
        if found:
            return found
    return DEFAULT


def current() -> str:
    """The language of whoever is being drawn for right now."""
    try:
        lang = language_resolver()
    except Exception:            # a resolver must never break a page
        lang = None
    return lang if lang in LANGUAGES else DEFAULT


def other(lang: str | None = None) -> str:
    """The language the toggle offers: the one that is not in use."""
    lang = lang or current()
    for code in LANGUAGES:
        if code != lang:
            return code
    return DEFAULT


def text(key: str, lang: str | None = None) -> str:
    """The raw text of a key, without placeholders filled in."""
    lang = lang or current()
    found = catalog(lang).get(key)
    if found is None and lang != DEFAULT:
        found = catalog(DEFAULT).get(key)
    if found is None:
        log.debug("missing i18n key %r (%s)", key, lang)
        return key
    return found


def t(key: str, **params) -> str:
    """The text of a key in the current language, with `{placeholders}`
    filled from the keyword arguments (format specs work: `{n:.1f}`)."""
    raw = text(key)
    if not params:
        return raw
    try:
        return raw.format(**params)
    except (KeyError, IndexError, ValueError):
        log.debug("bad placeholders for i18n key %r: %s", key, raw)
        return raw


def tn(key: str, n, **params) -> str:
    """The singular or plural form of a key, with `n` available as `{n}`."""
    form = "one" if n == 1 else "other"
    return t(f"{key}.{form}", n=n, **params)


def t_in(lang: str | None, key: str, **params) -> str:
    """`t` in a stated language: for texts sent to *other* windows, which
    must read them in their own language, not in the sender's."""
    raw = text(key, lang if lang in LANGUAGES else DEFAULT)
    if not params:
        return raw
    try:
        return raw.format(**params)
    except (KeyError, IndexError, ValueError):
        return raw


def tn_in(lang: str | None, key: str, n, **params) -> str:
    form = "one" if n == 1 else "other"
    return t_in(lang, f"{key}.{form}", n=n, **params)
