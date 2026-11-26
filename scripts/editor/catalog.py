"""Verified USA traffic identifiers and categories, without game assets.

The 64-bit identifiers encode up to twelve characters in base 40. These are
not random choices or cryptographic hashes. The names/categories below are
research metadata from the USA game's traffic-ID and localized-label tables.
Category verification does not imply that spawning a model is validated.
"""
from __future__ import annotations

ALPHABET = " -/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
IDENTIFIER_LENGTH = 12
IDENTIFIER_LIMIT = 40 ** IDENTIFIER_LENGTH

# Same ordinal order as the 40-entry USA traffic table at 0x004cdc00.
# Label indices are from its parallel table at 0x004cdd40, resolved through
# GLOBALUS.BIN. Category codes and English labels are our UI vocabulary.
_ROWS = (
    ("COMPCAR11", 1894, "car", "Car"),
    ("COMPCAR12", 1895, "car", "Car"),
    ("COMPCAR13", 1896, "car", "Car"),
    ("COMPCAR14", 1897, "car", "Car"),
    ("COMPCAR15", 1898, "taxi", "Taxi"),
    ("COMPCAR16", 1899, "taxi", "Taxi"),
    ("COMPCAR17", 1900, "taxi", "Taxi"),
    ("COMPCAR18", 1901, "tuk_tuk", "Tuk-tuk"),
    ("COMPCAR19", 1902, "car", "Car"),
    ("HEVYCAR11", 1903, "car", "Car"),
    ("HEVYCAR12", 1904, "car", "Car"),
    ("HEVYCAR13", 1905, "car", "Car"),
    ("HEVYCAR14", 1906, "pickup", "Pickup"),
    ("HEVYCAR15", 1907, "pickup", "Pickup"),
    ("HEVYCAR16", 1908, "van", "Van"),
    ("HEVYCAR17", 1909, "van", "Van"),
    ("HEVYCAR18", 1910, "van", "Van"),
    ("HEVYCAR19", 1911, "bus", "Bus"),
    ("HEVYCAR20", 1912, "bus", "Bus"),
    ("HEVYCAR21", 1913, "bus", "Bus"),
    ("HEVYCAR22", 1914, "big_rig", "Articulated truck"),
    ("HEVYCAR23", 1915, "big_rig", "Articulated truck"),
    ("HEVYCAR24", 1916, "freight_container", "Freight container"),
    ("HEVYCAR25", 1917, "freight_container", "Freight container"),
    ("HEVYCAR26", 1918, "freight_container", "Freight container"),
    ("HEVYCAR27", 1919, "flatbed", "Flatbed trailer"),
    ("HEVYCAR28", 1920, "lumber_trailer", "Lumber trailer"),
    ("HEVYCAR29", 1921, "tanker", "Tanker trailer"),
    ("HEVYCAR30", 1922, "covered_trailer", "Covered trailer"),
    ("HEVYCAR31", 1923, "minibus", "Minibus"),
    ("HEVYCAR32", 1924, "gritting_truck", "Gritting truck"),
    ("HEVYCAR33", 1925, "van", "Van"),
    ("HEVYCAR34", 1926, "motorhome", "Motorhome"),
    ("HEVYCAR35", 1927, "van", "Van"),
    ("TSPCCAR1", 1928, "tram", "Tram"),
    ("TSPCCAR2", 1928, "tram", "Tram"),
    ("TSPCCAR3", 1928, "tram", "Tram"),
    ("TSPCCAR4", 1928, "tram", "Tram"),
    ("TSPCCAR5", 1928, "tram", "Tram"),
    ("TSPCCAR6", 1928, "tram", "Tram"),
)


def encode_identifier(name: str) -> int:
    """Encode the supported twelve-character model-ID vocabulary exactly.

    Unlike the game's general helper, invalid or overlong names are rejected
    instead of silently accepting unsupported punctuation/truncating input.
    Lowercase ASCII is normalized, matching the game's identifier helper.
    """
    if not isinstance(name, str) or len(name) > IDENTIFIER_LENGTH:
        raise ValueError("Model identifier must contain at most 12 characters")
    upper = name.upper()
    if (any(ord(c) > 127 for c in name) or len(upper) != len(name)
            or any(c not in ALPHABET for c in upper)):
        raise ValueError("Model identifier contains unsupported characters")
    value = 0
    for char in upper.ljust(IDENTIFIER_LENGTH):
        value = value * 40 + ALPHABET.index(char)
    return value


def decode_identifier(value: int) -> str:
    """Decode a base-40 game identifier; trailing padding spaces are removed."""
    if type(value) is not int or not 0 <= value < IDENTIFIER_LIMIT:
        raise ValueError("Identifier is outside the twelve-character base-40 range")
    chars = [" "] * IDENTIFIER_LENGTH
    for index in range(IDENTIFIER_LENGTH - 1, -1, -1):
        value, digit = divmod(value, 40)
        chars[index] = ALPHABET[digit]
    return "".join(chars).rstrip(" ")


_CATALOG = {
    encode_identifier(asset): (ordinal, asset, string_index, category, label)
    for ordinal, (asset, string_index, category, label) in enumerate(_ROWS)
}


def classify_model(value: int) -> dict:
    """Return proven category metadata; never guess an unknown model's type.

    ``verified`` concerns the identifier/category mapping only. Callers must
    separately establish that the model is loaded and has an eligible active
    independent traffic type before offering an add operation.
    """
    name = decode_identifier(value)
    row = _CATALOG.get(value)
    if row is None:
        return {"model_id": value, "asset_id": name,
                "label": name or "Unknown model", "category": "unknown",
                "category_label": "Unknown category", "verified": False,
                "traffic_ordinal": None, "localized_label_index": None}
    ordinal, asset, string_index, category, label = row
    return {"model_id": value, "asset_id": asset,
            "label": f"{label} — {asset}", "category": category,
            "category_label": label, "verified": True,
            "traffic_ordinal": ordinal, "localized_label_index": string_index}


def traffic_catalog() -> list[dict]:
    """Return fresh metadata dictionaries for the 40 verified traffic IDs."""
    return [classify_model(encode_identifier(row[0])) for row in _ROWS]
