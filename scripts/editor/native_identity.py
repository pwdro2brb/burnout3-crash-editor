"""Read the loaded Crash event identifier from the USA EE memory profile."""
from __future__ import annotations

import re

from .catalog import IDENTIFIER_LIMIT, decode_identifier


EVENT_IDENTIFIER = 0x51AD68
STAGE_RESOURCE_PATH = 0x51ADAC
LOADED_RESOURCE_PATH = 0x6485F8
PATH_WINDOW = 48
TRACK_PATH = re.compile(rb"TRACKS/(AS|EU|US)/([CMP][1-9])_(V[12])/GAMEDATA\.BGD")
CRASH_EVENT = re.compile(r"1G[0-9A-Z]{4}")


def read_identity(memory) -> dict[str, str] | None:
    """Require the event's track suffix and two complete resource paths to agree.

    Only call with a snapshot of the supported USA build. These are loaded
    scene fields and do not indicate whether a gameplay round is running.
    """
    raw = memory.read_bytes(EVENT_IDENTIFIER, 8)
    if len(raw) != 8:
        return None
    value = int.from_bytes(raw, "little")
    if value >= IDENTIFIER_LIMIT:
        return None
    key = decode_identifier(value)
    if len(key) != 12 or not CRASH_EVENT.fullmatch(key[:6]):
        return None

    paths = []
    for address in (STAGE_RESOURCE_PATH, LOADED_RESOURCE_PATH):
        raw = memory.read_bytes(address, PATH_WINDOW)
        path, terminator, _ = raw.partition(b"\0")
        if len(raw) != PATH_WINDOW or not terminator:
            return None
        paths.append(path.upper())
    if paths[0] != paths[1]:
        return None
    match = TRACK_PATH.fullmatch(paths[0])
    if not match:
        return None
    region, course, variant = (part.decode("ascii") for part in match.groups())
    if key[6:] != region + course + variant:
        return None
    return {
        "event_key": key,
        "track": f"{region}/{course}_{variant}",
        "resource_path": paths[0].decode("ascii"),
    }
