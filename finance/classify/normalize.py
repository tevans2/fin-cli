"""Reduce a noisy bank description to a stable *merchant key*.

Bank descriptions carry per-transaction noise — auth/ref numbers, dates, card
processor prefixes, city/country codes — so the same merchant looks different
every time. The merchant key strips that noise to a canonical token so rules,
history learning, and analytics can link transactions to one merchant.

    Purchase at Yoco *Pizza Shed Cape Town ZA 622716900188  ->  pizza shed
    YOCO *LIQUID RAINBOW CAPE TOWN ZA                        ->  liquid rainbow
    Int Purchase, with card at EPOS at GONOWONDEMAND.COM ... ->  gonowondemand com
    PayShap - Pay by Account, Chanel Ritz 27/08             ->  chanel ritz
    EFT for SPLITWISE                                        ->  splitwise

Every rule list here is meant to be extended (and later, augmented from config)
as new statement dialects show up. Perfect normalization is not the goal — a
*stable* key is; the history/rule layers and user confirmation handle the rest.
"""

from __future__ import annotations

import re

# Leading transaction-type prefixes (lowercase). Longer/more specific first so
# "eft for" strips before "eft". A prefix is removed only when the char after it
# is a separator or end-of-string, so "eft" never eats "eftpos".
LEADING_PREFIXES: list[str] = [
    "int purchase, with card at epos at",
    "int purchase with card at epos at",
    "int purchase, with card at",
    "card purchase at",
    "purchase at",
    "pos purchase at",
    "pos purchase",
    "payshap - pay by account,",
    "payshap - pay by shapid,",
    "payshap",
    "immediate payment to",
    "payment to",
    "transfer to",
    "transfer from",
    "debit order",
    "eft for",
    "eft",
]

# Payment-processor code that prefixes the real merchant: "YOCO *X", "PP *X", "SMC*X".
_PROCESSOR_STAR = re.compile(r"^[a-z0-9]{1,8}\s*\*\s*")

# City/location tokens stripped from the tail (extensible; later config-driven).
LOCATIONS: list[str] = [
    "cape town",
    "stellenbosch central",
    "stellenbosch",
    "western cape",
    "diep river",
    "rosebank",
    "sandton",
    "johannesburg",
    "pretoria",
    "durban",
]

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"

# Noise patterns removed anywhere in the string.
NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\+?\d[\d ]{6,}\d"),                       # phone numbers
    re.compile(r"\b\d{5,}\b"),                             # long ref/auth numbers
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),      # dates like 27/08
    re.compile(rf"\b(?:{_MONTHS})[a-z]*\d*\b"),           # month fragments: aug, sept3
    re.compile(r"\b(za|us|gb|usd|eur|zar|uk)\b"),         # country/currency codes
    re.compile(r"account no\.?"),                          # "Account No."
]


def _strip_leading_prefix(text: str) -> str:
    for prefix in LEADING_PREFIXES:
        if text.startswith(prefix) and (len(text) == len(prefix) or text[len(prefix)] in " :,-"):
            return text[len(prefix):].lstrip(" :,-")
    return text


def merchant_key(description: str, ref: str | None = None) -> str:
    """Canonical, lowercase merchant key for a description (ref reserved for future use)."""
    text = " ".join((description or "").split()).lower()
    text = _strip_leading_prefix(text)
    text = _PROCESSOR_STAR.sub("", text)
    for location in LOCATIONS:
        text = re.sub(rf"\b{re.escape(location)}\b", " ", text)
    for pattern in NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(r"[^a-z0-9&]+", " ", text)  # drop punctuation, keep & (e.g. H&M)
    return " ".join(text.split()).strip()
