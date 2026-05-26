"""Classify dealerships as franchise or private from the dealer name."""
from __future__ import annotations

import re

# OEM and common franchise brand names (lowercase); matched as whole words in dealer name.
FRANCHISE_BRANDS: tuple[str, ...] = (
    "acura",
    "alfa romeo",
    "aston martin",
    "audi",
    "bentley",
    "bmw",
    "buick",
    "cadillac",
    "chevrolet",
    "chevy",
    "chrysler",
    "dodge",
    "ferrari",
    "fiat",
    "ford",
    "genesis",
    "gmc",
    "honda",
    "hummer",
    "hyundai",
    "infiniti",
    "jaguar",
    "jeep",
    "kia",
    "lamborghini",
    "land rover",
    "lexus",
    "lincoln",
    "lucid",
    "maserati",
    "mazda",
    "mercedes",
    "mercedes-benz",
    "mercury",
    "mini",
    "mitsubishi",
    "nissan",
    "oldsmobile",
    "pontiac",
    "porsche",
    "ram",
    "rivian",
    "rolls-royce",
    "saab",
    "saturn",
    "scion",
    "subaru",
    "suzuki",
    "tesla",
    "toyota",
    "volkswagen",
    "volvo",
    "vw",
)

# Longer brands first so "land rover" wins over "rover" if we add rover later.
_SORTED_BRANDS = sorted(FRANCHISE_BRANDS, key=len, reverse=True)
_BRAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (brand, re.compile(rf"\b{re.escape(brand)}\b", re.I)) for brand in _SORTED_BRANDS
]


def classify_dealer_type(dealer_name: str) -> str:
    """
    Return ``franchise`` if the name contains a known OEM brand, else ``private``.

    Returns empty string when the name is missing or blank.
    """
    name = (dealer_name or "").strip()
    if not name:
        return ""
    for brand, pattern in _BRAND_PATTERNS:
        if pattern.search(name):
            return "franchise"
    return "private"
