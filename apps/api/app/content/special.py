"""Special-category pages (P1b-04, architecture §6.4): skipped by the crawler unless a
reviewer whitelists their path for the site.

A page whose URL path or title matches an obvious pattern for the special categories
of personal data (GDPR Art. 9: health, religion or belief, political opinions about
named people, sex life or sexual orientation, ethnic origin, trade union membership,
genetic and biometric data) or for criminal records (Art. 10) is not stored or
ingested; the crawl lists it as blocked with its category, so a content reviewer can
look at it and whitelist the path (``sites.special_category_allow``).

The match is deliberately coarse, on words of the path and the title only (never the
page text, which would block most policy reports): it stops the obvious cases and
leaves the judgement to the reviewer. The pattern list is reviewed in code review.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from fnmatch import fnmatchcase
from typing import Final
from urllib.parse import urlsplit

# Category code -> words (lower case; a trailing "*" matches any ending). A phrase is
# words separated by single spaces; path separators and hyphens count as spaces.
CATEGORIES: Final[dict[str, tuple[str, ...]]] = {
    "health": (
        "health",
        "medical",
        "patient*",
        "disease*",
        "diagnos*",
        "illness*",
        "hospital*",
        "clinic",
        "clinics",
        "disabilit*",
        "pregnan*",
        "hiv",
        "cancer",
        "mental health",
    ),
    "religion": (
        "religion*",
        "religious",
        "church*",
        "mosque*",
        "synagogue*",
        "faith",
        "worship",
        "prayer*",
    ),
    "political_person": (
        "politician*",
        "candidate*",
        "senator*",
        "mep",
        "meps",
        "party member*",
        "political views",
        "political opinion*",
    ),
    "sexual_orientation": ("sexual*", "lgbt*", "gay", "lesbian*", "transgender", "sex life"),
    "ethnic_origin": ("ethnic*", "racial", "race relations"),
    "trade_union": ("trade union*", "union member*", "union membership"),
    "genetic_biometric": ("genetic*", "genome*", "biometric*", "dna"),
    "criminal_record": ("criminal record*", "conviction*", "offender*"),
}
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def _pattern(phrase: str) -> str:
    words = [
        re.escape(word.rstrip("*")) + (r"[a-z0-9]*" if word.endswith("*") else "")
        for word in phrase.split()
    ]
    return r"\b" + r" ".join(words) + r"\b"


_MATCHERS: Final = {
    category: re.compile("|".join(_pattern(p) for p in phrases))
    for category, phrases in CATEGORIES.items()
}


def _words(text: str) -> str:
    return " ".join(_SEPARATORS.split(text.lower())).strip()


def special_category(url: str, title: str) -> str | None:
    """The first special category the page's path or title matches, or None."""
    text = f"{_words(urlsplit(url).path)} | {_words(title)}"
    for category, matcher in _MATCHERS.items():
        if matcher.search(text):
            return category
    return None


def whitelisted(url: str, patterns: Sequence[str]) -> bool:
    """True when the URL's path matches one of the reviewer's whitelist patterns."""
    path = urlsplit(url).path or "/"
    return any(fnmatchcase(path, pattern) for pattern in patterns)
