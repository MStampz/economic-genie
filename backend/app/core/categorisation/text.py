"""Turns a bank's transaction text into something comparable.

Bank descriptions carry a lot of noise around the part that matters: card prefixes ("V2526"),
value dates ("01/11"), times, receipt and reference numbers ("F5751231187"), and channel words
("ONLINE", "INTERNET TRANSFER"). payee_key() strips that, so the same payee reads the same on
every row, whichever bank or month it came from.
"""

import re
import unicodedata

# Channel words that say how the money moved, not to whom.
_CHANNEL = {
    "online",
    "internet",
    "transfer",
    "transfers",
    "bpay",
    "pos",
    "eftpos",
    "visa",
    "debit",
    "credit",
    "purchase",
    "authorisation",
    "authorization",
    "payment",
    "osko",
    "npp",
    "direct",
    "dd",
    "trns",
}
_COUNTRY_TAIL = re.compile(r"\b(aus|au|australia|nsw|vic|qld|wa|sa|tas|act|nt|dnk|dk|idn|usa|us|gbr|gb)\s*$")
_NOISE = [
    re.compile(r"\bezypayid_\d+\b"),  # direct-debit references
    re.compile(r"\b[a-z]?\d{4}\s+\d{2}/\d{2}\b"),  # "V2526 01/11" card prefix + value date
    re.compile(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b"),  # dates
    re.compile(r"\d{1,2}:\d{2}"),  # times, often glued to the next word
    re.compile(r"\b[a-z]{1,3}-\d{3,}\b"),  # "U-3759", "Inv-3812"
    re.compile(r"\b[a-z]{0,3}\d{6,}\b"),  # reference and receipt numbers
    re.compile(r"\b\d+(st|nd|rd|th)\b"),  # "15th" in ATM texts
    re.compile(r"\b(inv|invoice|order|deal|number|no|ref|receipt)\b([\s#:-]*\b[a-z]?-?\d+\b)?"),
]
_NON_WORD = re.compile(r"[^a-z0-9&*.'/ ]+")
_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    """Lowercase, accents removed (café -> cafe, København -> kobenhavn), whitespace collapsed."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).replace("ø", "o").replace("æ", "ae")
    return _SPACES.sub(" ", t.lower()).strip()


def clean(text: str) -> str:
    """The text with dates, times, reference numbers and channel words removed."""
    t = fold(text)
    for rx in _NOISE:
        t = rx.sub(" ", t)
    t = _NON_WORD.sub(" ", t)
    words = [w for w in t.split() if w not in _CHANNEL and not w.isdigit()]
    t = " ".join(words)
    for _ in range(2):
        t = _COUNTRY_TAIL.sub("", t).strip()
    return t


def payee_key(description: str, merchant: str | None = None) -> str:
    """A stable key for who was paid. The bank's merchant name wins when it has one."""
    if merchant and merchant.strip():
        m = clean(re.sub(r"\(.*?\)", " ", merchant))
        if m:
            return m
    return clean(description)


def similar(a: str, b: str) -> float:
    """0..1: how alike two payee keys are. Word overlap first, then character similarity."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    from difflib import SequenceMatcher

    ta, tb = a.split(), b.split()
    # The same first two words ("revo fitness ...", "on point ...") is a strong sign of the same payee.
    lead = 0.0
    if len(ta) >= 2 and len(tb) >= 2 and ta[:2] == tb[:2] and len(ta[0]) + len(ta[1]) >= 6:
        lead = 0.92
    return max(lead, SequenceMatcher(None, a, b).ratio())
