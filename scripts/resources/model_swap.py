"""Replace a traffic model of a Crash event with a model used by other events.

Evidence (USA disc, all 100 Crash events):

* The game loads an event's traffic models from its six model groups: in
  savestates the runtime model table (manager +0x34390, up to 12 entries) is
  the concatenation of the groups in logical order.
* Every traffic model file is global (``PVEH/COMP/CARnn.BTV``,
  ``PVEH/HEVY/CARnn.BTV``), not stored per track.
* Inside an event block a model ID appears only in its group record and in the
  wave vehicle records that spawn it (checked for every model of every event).

A replacement therefore rewrites those 8-byte IDs and nothing else; sizes and
counts never change. A replacement must come from the same group in another
event (``CANDIDATES``), so the vehicle type the waves use stays valid. Models
never seen in a Crash event (lumber trailer HEVYCAR28, the TSPC trams) and the
player cars from the garage are not offered.

*Adding* a model (``add_models``) grows a group. In all 100 events the six
group arrays are the last referenced data of the block, and the game relocates
their start offsets when it loads the block (seen in savestate RAM), so the
writer copies the six arrays, with the new records, to the zero tail of the
block and points the group headers there. The old arrays are left untouched
(52 events keep unreferenced bytes right after them). Limits come from the
originals: at most 12 models in the runtime table (trams included) and at most
``MAX_MODEL_BYTES`` of model files, the largest total any original event loads.
"""
from __future__ import annotations

import struct

from editor.catalog import classify_model, encode_identifier
from resources.native_traffic import PHYSICAL_ORDER, RECORD, _layout, read_groups
from resources.traffic_waves import (
    TRAM_TYPE, _event_block, _used_ranges, read_waves, vehicle_record_offsets,
)

MAX_MODELS = 12            # entries of the runtime model table (manager +0x34390)
MAX_MODEL_BYTES = 2793472  # largest total of .BTV files loaded by an original event (Reiko-chet)

# Models observed in each group across the 100 USA Crash events.
CANDIDATES = (
    ("COMPCAR11", "COMPCAR12", "COMPCAR13", "COMPCAR14", "COMPCAR15", "COMPCAR16",
     "COMPCAR17", "COMPCAR18", "COMPCAR19"),
    ("HEVYCAR11", "HEVYCAR12", "HEVYCAR13", "HEVYCAR14", "HEVYCAR15", "HEVYCAR16",
     "HEVYCAR31", "HEVYCAR33", "HEVYCAR34", "HEVYCAR35"),
    ("HEVYCAR19", "HEVYCAR20", "HEVYCAR21"),
    ("HEVYCAR17", "HEVYCAR18", "HEVYCAR32"),
    ("HEVYCAR22", "HEVYCAR23"),
    ("HEVYCAR24", "HEVYCAR25", "HEVYCAR26", "HEVYCAR27", "HEVYCAR29", "HEVYCAR30"),
)
GROUP_LABELS = ("Cars", "Big cars, pickups and vans", "Buses", "Vans and gritters (type 3)", "Truck cabs", "Trailers")


def candidates_for(groups, model: str) -> tuple[str, ...]:
    """Models that can replace ``model`` in this event (same group, not loaded yet)."""
    loaded = {name for names in groups for name in names}
    for index, names in enumerate(groups):
        if model in names:
            return tuple(name for name in CANDIDATES[index] if name not in loaded)
    raise ValueError(f"{model} is not loaded by this event.")


def group_of(model: str) -> int:
    """Group index whose candidates include ``model`` (each model belongs to one group)."""
    for index, names in enumerate(CANDIDATES):
        if model in names:
            return index
    raise ValueError(f"{model} is not a traffic model used by the Crash events.")


def model_file(root, model: str):
    """Path of a traffic model file in an extracted game folder (PVEH/COMP/CAR14.BTV)."""
    from pathlib import Path
    return Path(root) / "PVEH" / model[:4] / (model[4:] + ".BTV")


def tram_models(schedule) -> tuple[str, ...]:
    """Trams the event's waves use; the game adds them to its model table too."""
    return tuple(sorted({v.model for w in schedule.waves for l in w.lanes for v in l.vehicles
                         if v.kind == TRAM_TYPE}))


def budget(groups, trams=(), root=None) -> dict:
    """How full the event's model table is: count (and bytes when ``root`` is given)."""
    names = [name for names in groups for name in names] + list(trams)
    result = {"models": len(names), "max_models": MAX_MODELS, "bytes": None, "max_bytes": MAX_MODEL_BYTES}
    if root is not None:
        try:
            result["bytes"] = sum(model_file(root, name).stat().st_size for name in names)
        except OSError:
            result["bytes"] = None
    return result


def can_add(groups, model: str, trams=(), root=None) -> str | None:
    """None when ``model`` can be added to the event, otherwise the reason it cannot."""
    try:
        group_of(model)
    except ValueError as error:
        return str(error)
    if any(model in names for names in groups):
        return f"{model} is already loaded by this event."
    room = budget(groups, trams, root)
    if room["models"] + 1 > MAX_MODELS:
        return (f"This event already loads {room['models']} models (the game keeps at most {MAX_MODELS}). "
                "Replace one instead.")
    if root is not None and room["bytes"] is not None:
        try:
            extra = model_file(root, model).stat().st_size
        except OSError:
            return f"The file of {model} was not found in the game folder."
        if room["bytes"] + extra > MAX_MODEL_BYTES:
            return (f"Adding {model} would load {(room['bytes'] + extra) // 1024} KB of models, more than any "
                    f"original event ({MAX_MODEL_BYTES // 1024} KB). Replace a model instead.")
    return None


def add_models(bgd: bytes, event_offset: int, models, *, trams=()) -> bytes:
    """Return a copy of the track file whose event also loads ``models``.

    Each model joins the group it belongs to (``CANDIDATES``). The six group
    arrays are rewritten, contiguous and in their physical order, into the zero
    tail of the event block; nothing else in the block changes.
    """
    models = list(models)
    if not models:
        return bytes(bgd)
    layout = _layout(bgd, event_offset)
    groups = [list(names) for _start, names in layout]
    for model in models:
        reason = can_add(groups, model, trams)
        if reason:
            raise ValueError(reason)
        groups[group_of(model)].append(model)
    block = _event_block(bgd, event_offset)
    scripted, other = _used_ranges(block)
    last_used = max(stop for _start, stop in scripted + other)
    last_byte = max((i + 1 for i in range(block.size - 1, -1, -1) if block.data[i]), default=0)
    start = (max(last_used, last_byte) + 15) & ~15
    need = sum(len(names) for names in groups) * RECORD.size
    if start + need > block.size:
        raise ValueError(f"Not enough free space at the end of this event block for the model lists "
                         f"({start + need - block.size} more bytes needed).")
    auxiliary = RECORD.unpack_from(bgd, layout[0][0] if layout[0][1] else
                                   next(s for s, n in layout if n))[1:]
    result = bytearray(bgd)
    cursor = start
    for group in PHYSICAL_ORDER:
        names = groups[group]
        struct.pack_into("<3I", result, event_offset + 0x54 + group * 12, cursor, len(names), len(names))
        for name in names:
            RECORD.pack_into(result, event_offset + cursor, encode_identifier(name), *auxiliary)
            cursor += RECORD.size
    result = bytes(result)
    if read_groups(result, event_offset) != tuple(tuple(names) for names in groups):
        raise ValueError("Re-reading the enlarged model groups did not match the request.")
    if read_waves(result, event_offset).waves != read_waves(bgd, event_offset).waves:
        raise ValueError("Adding a model must not change the waves.")
    return result


def apply_to_groups(groups, swaps: dict) -> tuple[tuple[str, ...], ...]:
    """Group lists with ``swaps`` (original name -> new name) applied, after checking them."""
    _check(groups, swaps)
    return tuple(tuple(swaps.get(name, name) for name in names) for names in groups)


def _check(groups, swaps) -> None:
    if not isinstance(swaps, dict):
        raise ValueError("Give the replacements as original model -> new model.")
    where = {name: index for index, names in enumerate(groups) for name in names}
    for old, new in swaps.items():
        if old not in where:
            raise ValueError(f"{old} is not loaded by this event.")
        if not isinstance(new, str) or new not in CANDIDATES[where[old]]:
            raise ValueError(f"{new} cannot replace {old}: use a model from the same group "
                             f"({GROUP_LABELS[where[old]].lower()}) of another event.")
        if not classify_model(encode_identifier(new))["verified"]:
            raise ValueError(f"{new} is not a known traffic model.")
    final = [swaps.get(name, name) for names in groups for name in names]
    if len(set(final)) != len(final):
        raise ValueError("Each model can be loaded only once per event.")


def replace_models(bgd: bytes, event_offset: int, swaps: dict) -> bytes:
    """Return a copy of the track file with the event's models replaced.

    Only the 8-byte model IDs in the group records and in the wave records
    change. The result is re-read and compared before it is returned.
    """
    if not swaps:
        return bytes(bgd)
    groups = read_groups(bgd, event_offset)
    _check(groups, swaps)
    before = read_waves(bgd, event_offset)
    codes = {encode_identifier(old): encode_identifier(new) for old, new in swaps.items()}
    result = bytearray(bgd)
    changed = []
    for (start, names) in _layout(bgd, event_offset):
        for index, name in enumerate(names):
            if name in swaps:
                position = start + index * RECORD.size
                struct.pack_into("<Q", result, position, encode_identifier(swaps[name]))
                changed.append(position)
    for position in vehicle_record_offsets(bgd, event_offset):
        for field in (0, 8):
            value = struct.unpack_from("<Q", result, position + field)[0]
            if value in codes:
                struct.pack_into("<Q", result, position + field, codes[value])
                changed.append(position + field)
    result = bytes(result)
    expected_groups = apply_to_groups(groups, swaps)
    if read_groups(result, event_offset) != expected_groups:
        raise ValueError("Re-reading the replaced model groups did not match the request.")
    after = read_waves(result, event_offset)
    renamed = rename_schedule(before, swaps)
    if after.waves != renamed.waves:
        raise ValueError("Re-reading the waves after the replacement did not match.")
    if len(result) != len(bgd):
        raise ValueError("The track file size must not change.")
    # Put the original IDs back: everything else must be byte-identical.
    restored = bytearray(result)
    for position in changed:
        restored[position:position + 8] = bgd[position:position + 8]
    if bytes(restored) != bytes(bgd):
        raise ValueError("The replacement changed bytes other than model IDs.")
    return result


def rename_schedule(schedule, swaps: dict):
    """The same wave schedule with model and trailer names replaced (for the editor UI)."""
    from dataclasses import replace
    if not swaps:
        return schedule
    waves = tuple(replace(wave, lanes=tuple(replace(lane, vehicles=tuple(
        replace(vehicle, model=swaps.get(vehicle.model, vehicle.model),
                trailer=swaps.get(vehicle.trailer, vehicle.trailer) if vehicle.trailer else None)
        for vehicle in lane.vehicles)) for lane in wave.lanes)) for wave in schedule.waves)
    models = {swaps.get(name, name): group for name, group in schedule.models.items()}
    return replace(schedule, waves=waves, models=models)
