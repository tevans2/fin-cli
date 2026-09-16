"""Merchant-key normalization against real bank-description patterns."""

from __future__ import annotations

import pytest

from finance.classify.normalize import merchant_key

CASES = [
    ("Purchase at Yoco *Pizza Shed Cape Town ZA 622716900188", "pizza shed"),
    ("YOCO *LIQUID RAINBOW CAPE TOWN ZA", "liquid rainbow"),
    ("Purchase at THE FAT BUTCHE STELLENBOSCH ZA 623019555719", "the fat butche"),
    ("Int Purchase, with card at EPOS at GONOWONDEMAND.COM +14693173436 US", "gonowondemand com"),
    ("PayShap - Pay by Account, Chanel Ritz Aug", "chanel ritz"),
    ("PayShap - Pay by Account, Chanel Ritz 27/08", "chanel ritz"),
    ("EFT for SPLITWISE", "splitwise"),
    ("EFT for ABSA BANK Chanel Ritz Sept3", "absa bank chanel ritz"),
    ("Purchase at AANDKLAS STELLENBOSCH Stellenbosch ZA 623820584472", "aandklas"),
    ("Purchase at TOPS OAKHURST Western Cape ZA 624915125816", "tops oakhurst"),
]


@pytest.mark.parametrize("description,expected", CASES)
def test_merchant_key(description, expected):
    assert merchant_key(description) == expected


def test_same_merchant_different_refs_and_dates_collapse():
    a = merchant_key("Purchase at Yoco *Pizza Shed Cape Town ZA 622716900188")
    b = merchant_key("Purchase at Yoco *Pizza Shed Cape Town ZA 999999999999")
    c = merchant_key("YOCO *PIZZA SHED CAPE TOWN ZA")
    assert a == b == c == "pizza shed"


def test_ampersand_preserved():
    assert merchant_key("Purchase at H&M Cape Town ZA 123456") == "h&m"


def test_blank_is_empty():
    assert merchant_key("") == ""
    assert merchant_key("   ") == ""
