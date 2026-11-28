"""Which Crash events start at the same place, and the game's numbering of the events.

Each event descriptor in a track's GAMEDATA.BGD lists four resources at +0x3BC
(size, offset pairs). The event loader (USA FUN_0014f050, a state machine) reads
them in order:

* resource 0 (0x800 bytes): start grid and preview camera route; relocated by
  FUN_003a20e0 (see docs/event-cameras.md). Transform 0 at +0x00 is where the
  player's car starts (rotation 3x4, position at +0x30);
* resource 1: the event block (traffic waves and model lists), loaded right
  after resource 0 and relocated by FUN_00269fa0;
* resource 2: the traffic paths. After FUN_00269f10 relocates it, the loader
  points every path descriptor (0x52288C + i*0x4C) at its 0x14-byte entries,
  count at resource 2 + 8;
* resource 3: further data handed to FUN_00271920 and to globals at
  0x64D344..0x64D368 (not decoded yet).

Resources 2 and 3 are the same for every event of a track file (all ten events
of US_C2_V1 point at the same two), so they describe the track, not one
junction. What makes two events "the same place" is their start: levels 5, 25
and 82 (Demolition, Wrecks City, Grid Locked) start within 15 units of each
other. Starts closer than ``SAME_START`` units are grouped; the original starts
fall into two clear sets (within 36 units, or 59 units and more apart).

The level number is the event's position in the game's progression order
(PRGDATA.BIN), which matches the numbering players use.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

from resources.crash_events import bgd_path

RESOURCE_PAIRS = 0x3BC
START_POSITION = 0x30  # position of transform 0 (the player's start) inside resource 0
SAME_START = 50.0


def event_resources(data: bytes, descriptor: int) -> tuple[tuple[int, int], ...]:
    """The four (size, offset) resource pairs of the event descriptor at ``descriptor``."""
    return tuple(struct.unpack_from("<2I", data, descriptor + RESOURCE_PAIRS + 8 * index) for index in range(4))


def start_position(data: bytes, descriptor: int) -> tuple[float, float, float]:
    """World position where the player's car starts (resource 0, transform 0)."""
    size, offset = event_resources(data, descriptor)[0]
    if size < START_POSITION + 12 or offset + size > len(data):
        raise ValueError("The event's resource 0 is outside the track file.")
    return struct.unpack_from("<3f", data, offset + START_POSITION)


def level_numbers(events) -> dict[str, int]:
    """In-game level number (1..100) of each event key, from the progression order."""
    return {event.key: number for number, event in enumerate(sorted(events, key=lambda e: e.progression_index), 1)}


def places(root: Path, events, radius: float = SAME_START) -> dict[str, dict]:
    """For each event key: its place id, start position and the other events starting there.

    Events whose track file cannot be read are left out.
    """
    cache, found = {}, {}
    for event in events:
        try:
            path = bgd_path(root, event.track)
            data = cache.get(path)
            if data is None:
                data = cache[path] = path.read_bytes()
            found[event.key] = (event.track, start_position(data, event.bgd_stage_offset),
                                event_resources(data, event.bgd_stage_offset))
        except (OSError, struct.error, ValueError):
            continue
    numbers = level_numbers(events)
    groups: list[tuple[str, list[str]]] = []
    for key in sorted(found, key=lambda k: numbers.get(k, 0)):
        track, position, _resources = found[key]
        joined = [g for g in groups if g[0] == track
                  and any(math.dist(position, found[other][1]) < radius for other in g[1])]
        if joined:
            joined[0][1].append(key)
            for extra in joined[1:]:  # a start can link two groups
                joined[0][1].extend(extra[1])
                groups.remove(extra)
        else:
            groups.append((track, [key]))
    result = {}
    for index, (track, keys) in enumerate(groups, 1):
        for key in keys:
            result[key] = {"place": index, "track": track, "start": found[key][1], "resources": found[key][2],
                           "shared_with": sorted((k for k in keys if k != key), key=lambda k: numbers.get(k, 0))}
    return result
