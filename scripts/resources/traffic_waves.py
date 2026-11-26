"""Read and edit the scripted Crash traffic waves stored in a track's GAMEDATA.BGD.

Research profile: Burnout 3: Takedown USA (SLUS-21050), event block version 8.

How the game releases Crash traffic (see docs/traffic-waves.md for the evidence):

* Each Crash event block holds a list of *waves* (the game calls them sets; the
  array is at block +0x4c, 0x58 bytes each, count at +0x50). Wave 0 loads when
  the event starts; wave k loads when the event clock passes its start time.
* A wave owns *lanes* (12-byte headers). A lane is bound to a traffic source
  (one entry of the source table at +0x3c) and to one slot of that source,
  which selects a road path.
* A lane lists *vehicles* (32-byte records). The first ``initial`` vehicles are
  placed on the path at their own ``distance`` as soon as the wave loads. The
  remaining vehicles enter one by one at the lane ``entry`` distance when the
  event clock reaches their ``time`` (seconds). Loading a later wave replaces
  the lane of the same source slot, discarding vehicles that never entered.

The game relocates every offset of this block by walking the same structure
(FUN_00269fa0 in the USA executable), so a writer may place new arrays in free
space inside the block as long as all offsets and counts stay consistent.
Fields whose meaning is unknown are preserved byte for byte.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import struct

from editor.catalog import classify_model, encode_identifier
from resources.native_traffic import read_groups, stage_offsets

SECTOR = 0x800
RESOURCE_PAIRS = 0x3BC
EVENT_RESOURCE = 1
BLOCK_VERSION = 8
WAVE_SIZE = 0x58
LANE_SIZE = 12
VEHICLE_SIZE = 32
MAX_WAVES = 32
MAX_VEHICLES_PER_LANE = 255
MAX_LANE_SLOTS = 4
MAX_EVENT_TIME = 600.0
# Group index of the event's model lists -> vehicle type byte used by records.
GROUP_TYPES = {0: 1, 1: 2, 2: 5, 3: 3, 4: 4}
TRUCK_TYPE = 4
TRAILER_GROUP = 5
TRAM_TYPE = 8
TRAM_GROUP = -1  # marker in WaveSchedule.models for trams the event already schedules
TYPE_NAMES = {1: "car", 2: "van", 3: "van (type 3)", 4: "truck + trailer", 5: "bus", 8: "tram"}


@dataclass(frozen=True)
class WaveVehicle:
    model: str
    trailer: str | None = None
    distance: float = 0.0
    time: float = 0.0
    kind: int = 1
    variant: int = 0
    trailer_variant: int = 0
    extra: bytes = bytes(5)


@dataclass(frozen=True)
class WaveLane:
    source: int
    slot: int
    entry: float
    initial: int
    vehicles: tuple[WaveVehicle, ...]


@dataclass(frozen=True)
class TrafficWave:
    start: float
    lanes: tuple[WaveLane, ...]


@dataclass(frozen=True)
class TrafficSource:
    paths: tuple[int, ...]
    offsets: tuple[int, ...]


@dataclass(frozen=True)
class WaveSchedule:
    waves: tuple[TrafficWave, ...]
    sources: tuple[TrafficSource, ...]
    models: dict = field(default_factory=dict)
    free_bytes: int = 0

    def lane_path(self, lane: WaveLane) -> int:
        return self.sources[lane.source].paths[lane.slot]


def _block_bounds(bgd: bytes, event_offset: int) -> int:
    """Return the size of the event block that starts at event_offset."""
    if type(event_offset) is not int or event_offset <= 0 or event_offset % SECTOR:
        raise ValueError("Incompatible event block offset.")
    for stage in stage_offsets(bgd):
        size, start = struct.unpack_from("<2I", bgd, stage + RESOURCE_PAIRS + EVENT_RESOURCE * 8)
        if start == event_offset:
            if not size or size % SECTOR or start + size > len(bgd):
                raise ValueError("The event block exceeds the track file.")
            return size
    raise ValueError("No event descriptor points to this block.")


class _Block:
    def __init__(self, data: bytes, size: int):
        self.data = data
        self.size = size

    def u8(self, offset: int) -> int:
        self._check(offset, 1)
        return self.data[offset]

    def u32(self, offset: int) -> int:
        self._check(offset, 4)
        return struct.unpack_from("<I", self.data, offset)[0]

    def f32(self, offset: int) -> float:
        self._check(offset, 4)
        return struct.unpack_from("<f", self.data, offset)[0]

    def u64(self, offset: int) -> int:
        self._check(offset, 8)
        return struct.unpack_from("<Q", self.data, offset)[0]

    def _check(self, offset: int, size: int) -> None:
        if not 0 <= offset <= self.size - size:
            raise ValueError("An offset of the event block points outside it.")

    def array(self, pointer: int, count: int, stride: int) -> tuple[int, int]:
        if count < 0 or (count and not 0 < pointer <= self.size - count * stride):
            raise ValueError("An array of the event block exceeds its limits.")
        return pointer, pointer + count * stride


def _used_ranges(block: _Block) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (scripted wave data ranges, every other referenced range).

    Mirrors the pointer fields relocated by the game (FUN_00269fa0/FUN_00269d20).
    Targets with an unknown length are recorded as at least four bytes.
    """
    u32, u8 = block.u32, block.u8
    if u32(0x28) != BLOCK_VERSION:
        raise ValueError("Unsupported event block version.")
    other = [(0, 0xC0)]
    scripted = []
    other.append(block.array(u32(0x2C), u32(0x30), WAVE_SIZE))
    other.append(block.array(u32(0x34), u32(0x38), 0x18))
    if u32(0x30) or u32(0x38) or u32(0xA8):
        raise ValueError("This event uses traffic tables not covered by the research.")
    src, nsrc = u32(0x3C), u32(0x40)
    other.append(block.array(src, nsrc, 16))
    for index in range(nsrc):
        base = src + index * 16
        lanes = u32(base + 8)
        if not 1 <= lanes <= MAX_LANE_SLOTS:
            raise ValueError("A traffic source has an unexpected lane count.")
        other.append(block.array(u32(base), lanes, 4))
        other.append(block.array(u32(base + 4), lanes, 4))
    other.append(block.array(u32(0x44), u32(0x48), 8))
    sets, nsets = u32(0x4C), u32(0x50)
    if not 1 <= nsets <= MAX_WAVES:
        raise ValueError("The event has an unexpected number of traffic waves.")
    other.append(block.array(sets, nsets, WAVE_SIZE))
    for wave in range(nsets):
        base = sets + wave * WAVE_SIZE
        n_speed, n_rate, n_e14 = u32(base + 0x40), u32(base + 0x44), u32(base + 0x48)
        b53, b54, b55 = u8(base + 0x53), u8(base + 0x54), u8(base + 0x55)
        layout = ((0x00, b53, 6), (0x04, n_speed, 4), (0x08, n_speed, 1), (0x0C, n_speed, 1),
                  (0x10, n_rate, 0x1C), (0x14, n_rate, 1), (0x18, n_rate, 1),
                  (0x1C, n_e14, 0x14), (0x20, n_e14, 1), (0x24, n_e14, 1),
                  (0x28, b54, 0x48), (0x2C, b54, 1), (0x30, b55, 0x10), (0x34, b55, 1))
        for field_offset, count, stride in layout:
            pointer = u32(base + field_offset)
            if count:
                other.append(block.array(pointer, count, stride))
        for item in range(n_e14):
            # Every original entry holds three equal offsets and two zero counts,
            # so its offsets are never dereferenced; anything else is unsupported.
            entry = u32(base + 0x1C) + item * 0x14
            if u32(entry + 12) or u32(entry + 16):
                raise ValueError("This event uses traffic tables not covered by the research.")
        lanes, nlanes = u32(base + 0x38), u32(base + 0x3C)
        if nlanes:
            scripted.append(block.array(lanes, nlanes, LANE_SIZE))
        for lane in range(nlanes):
            header = lanes + lane * LANE_SIZE
            total = u8(header + 8)
            if total:
                scripted.append(block.array(u32(header), total, VEHICLE_SIZE))
    for group in range(6):
        start, count, capacity = struct.unpack_from("<3I", block.data, 0x54 + group * 12)
        other.append(block.array(start, count, 24))
    count_9c = u32(0xA0)
    if count_9c:
        other.append(block.array(u32(0x9C), count_9c, 4))
    return scripted, other


def _merge(ranges):
    merged = []
    for start, stop in sorted(r for r in ranges if r[1] > r[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return merged


def _free_regions(block: _Block) -> list[tuple[int, int]]:
    """Regions a writer may reuse: old scripted data plus the zero tail."""
    scripted, other = _used_ranges(block)
    others = _merge(other)
    for s0, s1 in scripted:
        for o0, o1 in others:
            if s0 < o1 and o0 < s1:
                raise ValueError("Wave data overlaps other traffic tables; editing is blocked.")
    last = max(stop for _, stop in others + scripted)
    tail = last
    for offset in range(block.size - 1, last - 1, -1):
        if block.data[offset]:
            tail = offset + 1
            break
    tail = (tail + 15) & ~15
    regions = _merge(scripted + ([(tail, block.size)] if tail < block.size else []))
    # Close small alignment gaps between scripted arrays when they hold zeros only.
    joined = []
    for start, stop in regions:
        if (joined and start - joined[-1][1] < 16 and not any(block.data[joined[-1][1]:start])
                and not any(joined[-1][1] < o1 and o0 < start for o0, o1 in others)):
            joined[-1] = (joined[-1][0], stop)
        else:
            joined.append((start, stop))
    return joined


def _vehicle(block: _Block, offset: int) -> WaveVehicle:
    model = classify_model(block.u64(offset))
    trailer_id = block.u64(offset + 8)
    trailer = classify_model(trailer_id) if trailer_id else None
    if not model["verified"] or (trailer is not None and not trailer["verified"]):
        raise ValueError("A wave vehicle uses an unknown model identifier.")
    return WaveVehicle(model["asset_id"], trailer["asset_id"] if trailer else None,
                       block.f32(offset + 0x10), block.f32(offset + 0x14), block.u8(offset + 0x18),
                       block.u8(offset + 0x19), block.u8(offset + 0x1A),
                       bytes(block.data[offset + 0x1B:offset + 0x20]))


def _event_block(bgd: bytes, event_offset: int) -> _Block:
    size = _block_bounds(bgd, event_offset)
    return _Block(bytes(bgd[event_offset:event_offset + size]), size)


def _event_models(bgd: bytes, event_offset: int) -> dict:
    groups = read_groups(bgd, event_offset)
    return {name: index for index, names in enumerate(groups) for name in names}


def read_waves(bgd: bytes, event_offset: int) -> WaveSchedule:
    """Decode every traffic wave of one Crash event."""
    block = _event_block(bgd, event_offset)
    regions = _free_regions(block)
    u32, u8, f32 = block.u32, block.u8, block.f32
    sources = []
    for index in range(u32(0x40)):
        base = u32(0x3C) + index * 16
        lanes = u32(base + 8)
        sources.append(TrafficSource(
            tuple(u32(u32(base) + 4 * k) for k in range(lanes)),
            tuple(u32(u32(base + 4) + 4 * k) for k in range(lanes))))
    waves = []
    for wave in range(u32(0x50)):
        base = u32(0x4C) + wave * WAVE_SIZE
        lanes = []
        for lane in range(u32(base + 0x3C)):
            header = u32(base + 0x38) + lane * LANE_SIZE
            total, initial = u8(header + 8), u8(header + 9)
            records = u32(header)
            lanes.append(WaveLane(u8(header + 10), u8(header + 11), f32(header + 4), initial,
                                  tuple(_vehicle(block, records + i * VEHICLE_SIZE) for i in range(total))))
        waves.append(TrafficWave(f32(base + 0x4C), tuple(lanes)))
    models = _event_models(bgd, event_offset)
    for wave in waves:
        for lane in wave.lanes:
            for vehicle in lane.vehicles:
                if vehicle.kind == TRAM_TYPE:
                    models.setdefault(vehicle.model, TRAM_GROUP)
    schedule = WaveSchedule(tuple(waves), tuple(sources), models, 0)
    used = _layout_size(schedule.waves)
    capacity = sum(stop - start for start, stop in regions)
    schedule = replace(schedule, free_bytes=max(0, capacity - used))
    validate_waves(schedule)
    return schedule


def _layout_size(waves) -> int:
    size = 0
    for wave in waves:
        size += (len(wave.lanes) * LANE_SIZE + 15) & ~15
        for lane in wave.lanes:
            size += len(lane.vehicles) * VEHICLE_SIZE
    return size


def _finite(value, low, high, message):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(message)


def validate_waves(schedule: WaveSchedule) -> None:
    """Check the rules the game relies on. Raises ValueError with an explanation."""
    waves = schedule.waves
    if not 1 <= len(waves) <= MAX_WAVES:
        raise ValueError(f"An event needs between 1 and {MAX_WAVES} waves.")
    if waves[0].start != 0.0:
        raise ValueError("Wave 1 must start at 0 seconds (it loads with the event).")
    previous = -1.0
    for number, wave in enumerate(waves, 1):
        _finite(wave.start, 0.0, MAX_EVENT_TIME, f"Wave {number} has an invalid start time.")
        if number > 1 and wave.start <= previous:
            raise ValueError("Wave start times must increase from one wave to the next.")
        previous = wave.start
        seen = set()
        for lane in wave.lanes:
            if not 0 <= lane.source < len(schedule.sources):
                raise ValueError(f"Wave {number} uses a traffic source that does not exist.")
            if not 0 <= lane.slot < len(schedule.sources[lane.source].paths):
                raise ValueError(f"Wave {number} uses a lane slot the source does not have.")
            if (lane.source, lane.slot) in seen:
                raise ValueError(f"Wave {number} lists the same source lane twice.")
            seen.add((lane.source, lane.slot))
            _finite(lane.entry, 0.0, 1.0e6, f"Wave {number} has an invalid entry distance.")
            if not 0 <= lane.initial <= len(lane.vehicles) <= MAX_VEHICLES_PER_LANE:
                raise ValueError(f"Wave {number}: the placed count cannot exceed the lane's vehicles.")
            last_time = -1.0
            for index, vehicle in enumerate(lane.vehicles):
                _check_vehicle(schedule, vehicle, number)
                if index < lane.initial:
                    _finite(vehicle.distance, 0.0, 1.0e6, f"Wave {number} has an invalid placement distance.")
                else:
                    _finite(vehicle.time, 0.0, MAX_EVENT_TIME, f"Wave {number} has an invalid release time.")
                    if vehicle.time < last_time:
                        raise ValueError(f"Wave {number}: release times in a lane must not decrease.")
                    last_time = vehicle.time


def _check_vehicle(schedule: WaveSchedule, vehicle: WaveVehicle, number: int) -> None:
    models = schedule.models
    if not isinstance(vehicle.extra, bytes) or len(vehicle.extra) != 5:
        raise ValueError("Unknown vehicle fields must be preserved.")
    for name in (vehicle.model, vehicle.trailer):
        if name is not None:
            encode_identifier(name)
    if vehicle.kind == TRAM_TYPE:
        if vehicle.trailer is not None or models.get(vehicle.model) != TRAM_GROUP:
            raise ValueError(f"Wave {number}: only trams this event already uses can be scheduled.")
    else:
        group = models.get(vehicle.model)
        if group is None or GROUP_TYPES.get(group) != vehicle.kind:
            raise ValueError(f"Wave {number}: {vehicle.model} is not loaded by this event as that vehicle type.")
        if (vehicle.kind == TRUCK_TYPE) != (vehicle.trailer is not None):
            raise ValueError(f"Wave {number}: trucks need a trailer and other vehicles cannot have one.")
        if vehicle.trailer is not None and models.get(vehicle.trailer) != TRAILER_GROUP:
            raise ValueError(f"Wave {number}: trailer {vehicle.trailer} is not loaded by this event.")
    if not 0 <= vehicle.variant <= 7 or vehicle.trailer_variant != 0:
        raise ValueError(f"Wave {number}: use a colour variant from 0 to 7.")


def vehicle_type_for(schedule: WaveSchedule, model: str) -> int | None:
    """Type byte that this event uses for a loaded model, or None if it is not loaded."""
    group = schedule.models.get(model)
    if group == TRAM_GROUP:
        return TRAM_TYPE
    return GROUP_TYPES.get(group)


def loaded_models(schedule: WaveSchedule) -> dict[str, list[str]]:
    """Models the event loads, grouped by role: vehicles and trailers."""
    vehicles = [m for m, g in schedule.models.items() if g in GROUP_TYPES]
    trailers = [m for m, g in schedule.models.items() if g == TRAILER_GROUP]
    trams = [m for m, g in schedule.models.items() if g == TRAM_GROUP]
    return {"vehicles": vehicles + trams, "trailers": trailers}


def _pack_vehicle(vehicle: WaveVehicle, placed: bool) -> bytes:
    return (struct.pack("<QQff4B", encode_identifier(vehicle.model),
                        encode_identifier(vehicle.trailer) if vehicle.trailer else 0,
                        float(vehicle.distance) if placed else 0.0,
                        0.0 if placed else float(vehicle.time),
                        vehicle.kind, vehicle.variant, vehicle.trailer_variant, vehicle.extra[0])
            + vehicle.extra[1:])


class _Allocator:
    def __init__(self, regions):
        self.regions = [list(region) for region in regions]

    def take(self, size: int, align: int) -> int:
        for region in self.regions:
            start = (region[0] + align - 1) & ~(align - 1)
            if start + size <= region[1]:
                region[0] = start + size
                return start
        raise ValueError("Not enough free space in this event block for the requested waves "
                         f"({size} more bytes needed).")


def write_waves(bgd: bytes, event_offset: int, schedule: WaveSchedule) -> bytes:
    """Return a copy of the track file with the event's waves replaced by ``schedule``.

    When every count is unchanged the values are written in place. Otherwise the
    lane headers and vehicles are laid out again inside the event block, reusing
    the old wave data and the zero tail. The wave table moves only when the
    number of waves changes. Unknown fields are copied unchanged.
    """
    validate_waves(schedule)
    original = read_waves(bgd, event_offset)
    if original.sources != schedule.sources or original.models != schedule.models:
        raise ValueError("Sources and loaded models cannot change in a wave edit.")
    block = _event_block(bgd, event_offset)
    data = bytearray(block.data)
    u32 = block.u32
    same_shape = (len(original.waves) == len(schedule.waves) and all(
        len(a.lanes) == len(b.lanes) and all(len(x.vehicles) == len(y.vehicles) for x, y in zip(a.lanes, b.lanes))
        for a, b in zip(original.waves, schedule.waves)))
    sets = u32(0x4C)
    if same_shape:
        for number, wave in enumerate(schedule.waves):
            base = sets + number * WAVE_SIZE
            struct.pack_into("<f", data, base + 0x4C, wave.start)
            for lane_index, lane in enumerate(wave.lanes):
                header = u32(base + 0x38) + lane_index * LANE_SIZE
                struct.pack_into("<f4B", data, header + 4, lane.entry, len(lane.vehicles), lane.initial,
                                 lane.source, lane.slot)
                for index, vehicle in enumerate(lane.vehicles):
                    struct.pack_into("<32s", data, u32(header) + index * VEHICLE_SIZE,
                                     _pack_vehicle(vehicle, index < lane.initial))
    else:
        regions = _free_regions(block)
        old_sets = sets
        if len(schedule.waves) != len(original.waves):
            # The wave table moves, so its old bytes can hold lanes and vehicles.
            regions = _merge(regions + [(old_sets, old_sets + len(original.waves) * WAVE_SIZE)])
        for start, stop in regions:
            data[start:stop] = bytes(stop - start)
        allocator = _Allocator(regions)
        if len(schedule.waves) != len(original.waves):
            sets = allocator.take(len(schedule.waves) * WAVE_SIZE, 16)
            struct.pack_into("<2I", data, 0x4C, sets, len(schedule.waves))
        template = bytes(block.data[old_sets:old_sets + WAVE_SIZE])
        empty_target = old_sets  # any in-block offset is valid for an empty array
        for number, wave in enumerate(schedule.waves):
            base = sets + number * WAVE_SIZE
            if number < len(original.waves):
                if base != old_sets + number * WAVE_SIZE:
                    data[base:base + WAVE_SIZE] = block.data[old_sets + number * WAVE_SIZE:
                                                              old_sets + (number + 1) * WAVE_SIZE]
            else:
                # A new wave only schedules vehicles: every other table is empty.
                fresh = bytearray(template)
                for offset in range(0, 0x3C, 4):
                    struct.pack_into("<I", fresh, offset, empty_target)
                struct.pack_into("<4I", fresh, 0x3C, 0, 0, 0, 0)
                fresh[0x50:WAVE_SIZE] = bytes(WAVE_SIZE - 0x50)
                data[base:base + WAVE_SIZE] = fresh
            struct.pack_into("<f", data, base + 0x4C, wave.start)
            headers = allocator.take(len(wave.lanes) * LANE_SIZE, 16) if wave.lanes else empty_target
            struct.pack_into("<2I", data, base + 0x38, headers, len(wave.lanes))
            for lane_index, lane in enumerate(wave.lanes):
                records = allocator.take(len(lane.vehicles) * VEHICLE_SIZE, 16) if lane.vehicles else empty_target
                struct.pack_into("<If4B", data, headers + lane_index * LANE_SIZE, records, lane.entry,
                                 len(lane.vehicles), lane.initial, lane.source, lane.slot)
                for index, vehicle in enumerate(lane.vehicles):
                    data[records + index * VEHICLE_SIZE:records + (index + 1) * VEHICLE_SIZE] = \
                        _pack_vehicle(vehicle, index < lane.initial)
    result = bytes(bgd[:event_offset]) + bytes(data) + bytes(bgd[event_offset + block.size:])
    if len(result) != len(bgd):
        raise ValueError("The track file size must not change.")
    reread = read_waves(result, event_offset)
    expected = tuple(_normalised(wave) for wave in schedule.waves)
    if tuple(_normalised(wave) for wave in reread.waves) != expected:
        raise ValueError("Re-reading the edited waves did not match the request.")
    if read_groups(result, event_offset) != read_groups(bgd, event_offset):
        raise ValueError("A wave edit must not change the model lists.")
    return result


def _normalised(wave: TrafficWave) -> TrafficWave:
    """Fields the game ignores are stored as zero: distance for timed, time for placed."""
    lanes = []
    for lane in wave.lanes:
        vehicles = tuple(replace(v, distance=float(struct.unpack("<f", struct.pack("<f", v.distance))[0]) if i < lane.initial else 0.0,
                                 time=0.0 if i < lane.initial else float(struct.unpack("<f", struct.pack("<f", v.time))[0]))
                         for i, v in enumerate(lane.vehicles))
        lanes.append(replace(lane, entry=float(struct.unpack("<f", struct.pack("<f", lane.entry))[0]), vehicles=vehicles))
    return replace(wave, start=float(struct.unpack("<f", struct.pack("<f", wave.start))[0]), lanes=tuple(lanes))


def describe(schedule: WaveSchedule) -> list[str]:
    """Plain-text summary used by the CLI and the editor."""
    lines = []
    for number, wave in enumerate(schedule.waves, 1):
        placed = sum(lane.initial for lane in wave.lanes)
        timed = sum(len(lane.vehicles) - lane.initial for lane in wave.lanes)
        when = "event start" if number == 1 else f"{wave.start:g} s"
        lines.append(f"Wave {number} ({when}): {placed} placed, {timed} released later, {len(wave.lanes)} lanes")
        for lane in wave.lanes:
            path = schedule.lane_path(lane)
            lines.append(f"  lane source {lane.source} slot {lane.slot} (path P{path}), entry {lane.entry:.1f}")
            for index, vehicle in enumerate(lane.vehicles):
                name = vehicle.model + (" + " + vehicle.trailer if vehicle.trailer else "")
                where = (f"placed at {vehicle.distance:.1f}" if index < lane.initial
                         else f"enters at {vehicle.time:.2f} s")
                lines.append(f"    {index + 1:>2}. {name:<22} {TYPE_NAMES.get(vehicle.kind, vehicle.kind)!s:<16}"
                             f" colour {vehicle.variant}  {where}")
    return lines


# --- Shareable JSON form -----------------------------------------------------

JSON_FORMAT = "burnout3-crash-waves"
JSON_VERSION = 1


def _short(value: float) -> float:
    """Shortest decimal that stores back to the same 32-bit float."""
    target = struct.pack("<f", value)
    for digits in range(1, 10):
        candidate = float(f"{value:.{digits}g}")
        if struct.pack("<f", candidate) == target:
            return candidate
    return float(value)


def waves_to_dict(schedule: WaveSchedule, *, event_key: str | None = None) -> dict:
    """Plain data for a ``.waves.json`` file. Unknown bytes travel as hex."""
    waves = []
    for wave in schedule.waves:
        lanes = []
        for lane in wave.lanes:
            vehicles = []
            for index, vehicle in enumerate(lane.vehicles):
                item = {"model": vehicle.model, "colour": vehicle.variant}
                if vehicle.trailer:
                    item["trailer"] = vehicle.trailer
                if index < lane.initial:
                    item["placed_at"] = _short(vehicle.distance)
                else:
                    item["enters_at_s"] = _short(vehicle.time)
                if vehicle.extra != bytes(5) or vehicle.trailer_variant:
                    item["raw"] = {"trailer_variant": vehicle.trailer_variant, "extra": vehicle.extra.hex()}
                vehicles.append(item)
            lanes.append({"source": lane.source, "slot": lane.slot,
                          "path": schedule.lane_path(lane),
                          "entry_distance": _short(lane.entry), "vehicles": vehicles})
        waves.append({"start_s": _short(wave.start), "lanes": lanes})
    result = {"format": JSON_FORMAT, "version": JSON_VERSION, "waves": waves}
    if event_key:
        result["event"] = event_key
    return result


def waves_from_dict(data: dict, base: WaveSchedule) -> WaveSchedule:
    """Build a schedule for the event that ``base`` was read from."""
    if not isinstance(data, dict) or data.get("format") != JSON_FORMAT or data.get("version") != JSON_VERSION:
        raise ValueError("This is not a Burnout 3 Crash waves file (version 1).")
    raw_waves = data.get("waves")
    if not isinstance(raw_waves, list):
        raise ValueError("The waves file has no wave list.")
    waves = []
    for number, raw_wave in enumerate(raw_waves, 1):
        if not isinstance(raw_wave, dict) or not isinstance(raw_wave.get("lanes"), list):
            raise ValueError(f"Wave {number} is malformed.")
        lanes = []
        for raw_lane in raw_wave["lanes"]:
            if not isinstance(raw_lane, dict) or not isinstance(raw_lane.get("vehicles"), list):
                raise ValueError(f"A lane of wave {number} is malformed.")
            source, slot = raw_lane.get("source"), raw_lane.get("slot")
            if type(source) is not int or type(slot) is not int:
                raise ValueError(f"A lane of wave {number} needs integer source and slot values.")
            if not 0 <= source < len(base.sources) or not 0 <= slot < len(base.sources[source].paths):
                raise ValueError(f"Wave {number} uses a traffic source that this event does not have.")
            if "path" in raw_lane and raw_lane["path"] != base.sources[source].paths[slot]:
                raise ValueError(f"Wave {number}: the lane path does not match this event's track.")
            placed, released = [], []
            for raw in raw_lane["vehicles"]:
                if not isinstance(raw, dict) or not isinstance(raw.get("model"), str):
                    raise ValueError(f"A vehicle of wave {number} is malformed.")
                kind = vehicle_type_for(base, raw["model"])
                if kind is None:
                    raise ValueError(f"Wave {number}: {raw['model']} is not loaded by this event.")
                extra = raw.get("raw", {})
                try:
                    extra_bytes = bytes.fromhex(extra.get("extra", "0000000000"))
                except (AttributeError, ValueError) as error:
                    raise ValueError(f"Wave {number}: invalid raw vehicle bytes.") from error
                colour = raw.get("colour", 0)
                if type(colour) is not int:
                    raise ValueError(f"Wave {number}: colour must be an integer from 0 to 7.")
                vehicle = WaveVehicle(raw["model"], raw.get("trailer"), kind=kind, variant=colour,
                                      trailer_variant=extra.get("trailer_variant", 0), extra=extra_bytes)
                if ("placed_at" in raw) == ("enters_at_s" in raw):
                    raise ValueError(f"Wave {number}: each vehicle needs either placed_at or enters_at_s.")
                if "placed_at" in raw:
                    placed.append(replace(vehicle, distance=raw["placed_at"]))
                else:
                    released.append(replace(vehicle, time=raw["enters_at_s"]))
            for vehicle in placed + released:
                for value in (vehicle.distance, vehicle.time):
                    if type(value) not in (int, float):
                        raise ValueError(f"Wave {number}: distances and times must be numbers.")
            released.sort(key=lambda v: v.time)
            entry = raw_lane.get("entry_distance")
            if type(entry) not in (int, float):
                raise ValueError(f"A lane of wave {number} needs a numeric entry_distance.")
            lanes.append(WaveLane(source, slot, float(entry), len(placed),
                                  tuple(placed) + tuple(released)))
        start = raw_wave.get("start_s")
        if type(start) not in (int, float):
            raise ValueError(f"Wave {number} needs a numeric start_s.")
        waves.append(TrafficWave(float(start), tuple(lanes)))
    schedule = replace(base, waves=tuple(waves))
    validate_waves(schedule)
    return schedule
