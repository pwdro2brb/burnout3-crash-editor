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
"""
from __future__ import annotations

import struct

from editor.catalog import classify_model, encode_identifier
from resources.native_traffic import RECORD, _layout, read_groups
from resources.traffic_waves import read_waves, vehicle_record_offsets

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
