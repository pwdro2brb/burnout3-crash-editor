"""Inspect and reorder model IDs within the USA Crash event's six traffic groups."""
from __future__ import annotations

import struct

from editor.catalog import classify_model, decode_identifier, encode_identifier


SECTOR = 0x800
STAGE_POINTERS = 0x198
DIRECTORY = 0x260
RESOURCE_PAIRS = 0x3BC
EVENT_RESOURCE = 1
GROUP_HEADERS = 0x54
RECORD = struct.Struct("<Q4I")
# Arrays are adjacent on disk in this order, including empty arrays.
PHYSICAL_ORDER = (0, 1, 3, 4, 2, 5)


def stage_offsets(data: bytes) -> tuple[int, ...]:
    if len(data) < SECTOR or struct.unpack_from("<I", data)[0] != 9:
        raise ValueError("Incompatible track header.")
    count, first, end = struct.unpack_from("<3I", data, DIRECTORY)
    if (not 1 <= count <= (DIRECTORY - STAGE_POINTERS) // 4
            or first < SECTOR or first % SECTOR
            or end != first + count * SECTOR or end > len(data)):
        raise ValueError("The limits of the track's event directory are invalid.")
    stages = struct.unpack_from(f"<{count}I", data, STAGE_POINTERS)
    if stages != tuple(range(first, end, SECTOR)):
        raise ValueError("The pointers of the track's event directory disagree.")
    return stages


def _event_size(data: bytes, offset: int) -> int:
    if type(offset) is not int or offset <= 0 or offset % SECTOR:
        raise ValueError("Incompatible event offset.")
    stages = stage_offsets(data)
    end = stages[-1] + SECTOR
    sections = []
    target = None
    for stage in stages:
        for index in range(4):
            size, start = struct.unpack_from("<2I", data, stage + RESOURCE_PAIRS + index * 8)
            stop = start + size
            if not size or size % SECTOR or start % SECTOR or not end <= start < stop <= len(data):
                raise ValueError("A directory resource goes beyond the track file.")
            sections.append((start, stop))
            if index == EVENT_RESOURCE and start == offset:
                key = decode_identifier(struct.unpack_from("<Q", data, stage + 0x398)[0])
                if target is not None or len(key) != 12 or not key.startswith("1G"):
                    raise ValueError("The chosen block does not belong to a single Crash event.")
                target = stop
    if target is None or sum(a < target and b > offset for a, b in sections) != 1:
        raise ValueError("The event block is missing or shared with another resource.")
    return target - offset


def _layout(data: bytes, event_offset: int):
    size = _event_size(data, event_offset)
    if struct.unpack_from("<I", data, event_offset + 0x28)[0] != 8:
        raise ValueError("The event block format is incompatible.")
    ranges = []
    for group in range(6):
        start, count, capacity = struct.unpack_from(
            "<3I", data, event_offset + GROUP_HEADERS + group * 12)
        stop = start + count * RECORD.size
        if count != capacity or start % 8 or not 0xC0 <= start <= stop <= size:
            raise ValueError("A model group has invalid limits or counts.")
        ranges.append((start, stop))
    physical = [ranges[i] for i in PHYSICAL_ORDER]
    if any(left[1] != right[0] for left, right in zip(physical, physical[1:])):
        raise ValueError("The model lists overlap or are not contiguous.")

    groups = []
    seen = set()
    for start, stop in ranges:
        names = []
        for pos in range(event_offset + start, event_offset + stop, RECORD.size):
            value, *auxiliary = RECORD.unpack_from(data, pos)
            if tuple(auxiliary) != (100, 0, 1, 0):
                raise ValueError("The model record contains unknown auxiliary fields.")
            model = classify_model(value)
            if not model["verified"] or value in seen:
                raise ValueError("The event contains an unknown or repeated model.")
            seen.add(value)
            names.append(model["asset_id"])
        groups.append((event_offset + start, tuple(names)))
    return groups


def read_groups(bgd: bytes, event_offset: int) -> tuple[tuple[str, ...], ...]:
    """Return the six model lists in logical group order, preserving empty lists."""
    return tuple(names for _, names in _layout(bgd, event_offset))


def reorder_groups(bgd: bytes, event_offset: int, orders: tuple[tuple[str, ...], ...]) -> bytes:
    """Return a copy with only eight-byte model IDs permuted inside each group."""
    groups = _layout(bgd, event_offset)
    if not isinstance(orders, (list, tuple)) or len(orders) != len(groups):
        raise ValueError("Give the six model groups of the event.")
    result = bytearray(bgd)
    for (start, current), order in zip(groups, orders):
        if (not isinstance(order, (list, tuple)) or len(order) != len(current)
                or not all(isinstance(name, str) for name in order) or set(order) != set(current)):
            raise ValueError("Each group only accepts its own original models, once each.")
        for index, name in enumerate(order):
            if current[index] != name:
                struct.pack_into("<Q", result, start + index * RECORD.size, encode_identifier(name))
    result = bytes(result)
    if read_groups(result, event_offset) != tuple(tuple(order) for order in orders):
        raise ValueError("Re-reading the edited groups did not match the request.")
    return result
