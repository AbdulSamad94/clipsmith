"""Keyword and emoji highlights for burned-in captions (Submagic-style).

Everything here is rule-based and offline: no AI model is needed to decide
which words in a caption group deserve a highlight."""
from __future__ import annotations

import re

# Words that never get highlighted, however long they are.
STOPWORDS = frozenset("""
a an the and or but so if then than that this these those there their they them
is am are was were be been being have has had do does did will would can could
should shall may might must i me my we us our you your he him his she her it its
of in on at to for from by with about into over under up down out off as just
like really very also because something everything everyone someone anything
nothing actually basically literally gonna wanna yeah okay ok um uh what when
where which who whom whose why how not no yes all any some more most much many
""".split())

# Words people lean on for emphasis.
EMPHASIS = frozenset("""
never always best worst secret secrets huge insane crazy free money biggest
massive impossible shocking dangerous instantly forever everybody nobody
million millions billion billions thousand hundred percent double triple
mistake mistakes wrong truth hack hacks easy hardest fastest cheapest
""".split())

# A small local keyword -> emoji map. Used only when emoji highlights are on.
EMOJI = {
    "money": "\U0001F4B0", "cash": "\U0001F4B5", "rich": "\U0001F4B0", "dollars": "\U0001F4B5",
    "fire": "\U0001F525", "insane": "\U0001F92F", "crazy": "\U0001F92F", "shocking": "\U0001F631",
    "love": "❤️", "heart": "❤️", "laugh": "\U0001F602", "funny": "\U0001F602",
    "idea": "\U0001F4A1", "secret": "\U0001F92B", "secrets": "\U0001F92B", "time": "⏰",
    "win": "\U0001F3C6", "winner": "\U0001F3C6", "best": "\U0001F3C6", "goal": "\U0001F3AF",
    "rocket": "\U0001F680", "growth": "\U0001F4C8", "grow": "\U0001F4C8", "fast": "⚡",
    "warning": "⚠️", "mistake": "❌", "wrong": "❌", "right": "✅",
    "brain": "\U0001F9E0", "think": "\U0001F914", "food": "\U0001F354", "music": "\U0001F3B5",
    "phone": "\U0001F4F1", "car": "\U0001F697", "world": "\U0001F30D", "happy": "\U0001F604",
    "sad": "\U0001F622", "angry": "\U0001F620", "dead": "\U0001F480", "strong": "\U0001F4AA",
}

# Keyword colours (ASS &HBBGGRR&); the first one that isn't the style's
# active-word colour is used, so a keyword never looks like the spoken word.
_KEY_COLOURS = ("&H5CFF4D&", "&H00F6FF&")

_NUMBER = re.compile(r"\d")
_CLEAN = re.compile(r"[^\w$%']+")


def _clean(word: str) -> str:
    return _CLEAN.sub("", word).strip("'")


def score(word: str) -> int:
    """How strongly a single word stands out. 0 means never highlight it."""
    raw = _clean(word)
    w = raw.lower()
    if not w or w in STOPWORDS:
        return 0
    if _NUMBER.search(w):
        return 5
    if w in EMPHASIS:
        return 4
    s = min(max(len(w) - 4, 0), 3)  # long words are usually the rarer, meatier ones
    if len(raw) > 1 and raw.isupper():
        s += 2  # the transcript already shouts it
    return s


def pick_keywords(words: list[str], max_n: int = 1, threshold: int = 3) -> list[int]:
    """Indices (in reading order) of up to `max_n` words worth highlighting."""
    scored = [(score(w), i) for i, w in enumerate(words)]
    best = sorted((x for x in scored if x[0] >= threshold), key=lambda x: (-x[0], x[1]))
    return sorted(i for _, i in best[:max_n])


def emoji_for(word: str) -> str | None:
    return EMOJI.get(_clean(word).lower())


def key_colour(active: str) -> str:
    return next(c for c in _KEY_COLOURS if c != active)
