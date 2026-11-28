# Traffic waves: how a Crash event releases its traffic

In many Crash events most of the traffic is already on the road when the event
starts, and a smaller batch shows up a few seconds later. This page explains
the mechanism, where the data lives on the disc, and how to edit it.

Research profile: Burnout 3: Takedown USA (`SLUS-21050`, CRC `BEBF8793`),
executable SHA-256 `e118dba952bf9fde6a04ee284bb1f06fa0bb49c9e04bbe762af1039dcc443c66`,
PCSX2 1.7.2521. Other regions or versions need their own validation.

## The short version

Crash traffic is **scripted**, not random. Each event stores a list of
**waves**:

- **Wave 1** loads when the event starts.
- **Wave 2, 3, …** load when the event clock reaches their start time
  (seconds). The 100 original events use 1 to 5 waves, starting between 1 s and 21 s.

Each wave contains **lanes**. A lane belongs to one road path of the track and
lists **vehicles** in order:

- The first vehicles of a lane are **placed**: they appear immediately at their
  own distance along the path when their wave loads. This is the "big batch".
- The remaining vehicles are **timed**: each one enters at the lane's
  **entry distance** when the event clock reaches its time. They enter one at a
  time, in list order.
- When a later wave has a lane for the same road slot, it **replaces** the old
  lane: vehicles of the old lane that had not entered yet are dropped.

Across the 100 events, wave 1 places 1,357 vehicles at the start and releases
300 more by time; later waves place 727 and release 621.

### Example: Grand Slam

| Wave | Starts | Lane (path) | Placed vehicles | Timed vehicles |
| --- | --- | --- | --- | --- |
| 1 | event start | P20, entry 537.1 | COMPCAR14, HEVYCAR33, COMPCAR12, COMPCAR13, HEVYCAR35 at 638 → 578 (15 units apart) | truck HEVYCAR22 + HEVYCAR27 at 0.53 s |
| 1 | event start | P21, entry 1305.0 | truck HEVYCAR22 + HEVYCAR27, COMPCAR13, COMPCAR12, COMPCAR14 at 1531 → 1486 | — |
| 2 | 9 s | P20, entry 537.1 | HEVYCAR20 (bus), COMPCAR14, COMPCAR13, COMPCAR12, HEVYCAR20, HEVYCAR35 at 638 → 543 | COMPCAR14 at 9.34 s |

The "first red car" investigated in earlier milestones (object 9 on path 21) is
the fourth placed vehicle of wave 1 on P21: `COMPCAR14`, colour 0, at distance
1486.08. To move it, change that distance.

Run `python scripts/waves.py show "Grand Slam" --game-root <extracted game>` to
print the same listing for any event.

## Editing waves

### In the editor window

**Traffic waves…** (top-right button of the editor, or **Project → Native events / traffic waves…**) shows the waves of the selected
event as a tree (wave → lane → vehicle) next to a small map that highlights the
lanes of the selected wave, their placed vehicles (dots) and entry points
(triangles).

- **Wave start (s)** changes when a wave loads. Wave 1 always starts at 0.
- **Add wave / Remove wave** append an empty wave after the last one or delete
  the selected one.
- **Lane entry distance** moves where timed vehicles of that lane appear.
- **Add lane** binds a new lane to a road slot that the wave does not use yet;
  it starts with one car 50 units after the entry.
- For a vehicle: model, trailer (trucks only), colour variant 0–7, and either
  **Placed at distance** or **Enters at time (s)**. **Duplicate** copies a
  placed vehicle 15 units behind, or a timed one 1 s later.
- **Export waves JSON… / Import waves JSON…** save or load the event's waves
  as a shareable file.

Every change is checked against the rules below and the free space before it
is accepted. **Export files…** or **Build ISO copy…** writes it together with
the other edits of the event.

### As a JSON file

```powershell
python scripts/waves.py export "Grand Slam" grand-slam.waves.json --game-root "<extracted game>"
```

```json
{
 "format": "burnout3-crash-waves",
 "version": 1,
 "event": "1G0007EUC3V1",
 "title": "Grand Slam",
 "waves": [
  {
   "start_s": 0.0,
   "lanes": [
    {"source": 36, "slot": 0, "path": 21, "entry_distance": 1305.004,
     "vehicles": [
      {"model": "HEVYCAR22", "trailer": "HEVYCAR27", "colour": 0, "placed_at": 1531.0778},
      {"model": "COMPCAR14", "colour": 0, "placed_at": 1486.0778},
      {"model": "HEVYCAR20", "colour": 0, "enters_at_s": 3.0}
     ]}
   ]
  }
 ]
}
```

`source` and `slot` select the road slot (`path` is informative and checked).
A vehicle has either `placed_at` (distance) or `enters_at_s` (time). Edit the
file, then build a new ISO or the edited resource files:

```powershell
python scripts/waves.py build grand-slam.waves.json --game-root "<extracted game>" --iso "<original.iso>" --out "Grand Slam - edited.iso"
```

`build` accepts several files at once, including two events that share the
same track file; both edits are kept. Use `--files-out <folder>` instead of
`--iso/--out` to get only the edited `GAMEDATA.BGD`. The original game files
and ISO are never modified, and every write is read back and verified.

### How many vehicles

The tab, `waves.py list` and `waves.py show` report how many vehicles the event can
put on the road (a truck with its trailer counts once; timed vehicles of a lane that a
later wave replaces before their time are not counted; vehicles that drive away are
not subtracted). Nothing blocks a large number: above **50** the editor warns that
the game does not work properly, and from **64** that this is where the game crashed
in tests (around 64 crashed vehicles). The warning appears only when an edit goes
beyond 50 and beyond the original event, because four original events (Neon
Nightmare, Fear Factor, Sunshine Smash, Gate Crasher) already schedule 51 to 56.

### Rules the game relies on

The editor enforces these; the JSON importer and the CLI apply the same checks.

- Wave start times increase from one wave to the next; wave 1 starts at 0.
- A wave uses each road slot (source + slot) at most once.
- Timed vehicles of a lane are in non-decreasing time order (the game releases
  them strictly in list order).
- Models must already be loaded by the event: cars, vans, buses and truck cabs
  from the event's model groups, trailers from its trailer group. A truck needs
  a trailer; other vehicles cannot have one. Trams are allowed only in events
  that already use them. Use **Models and goals** to see what an event loads.
- Colour variants are 0–7 (the exact colour per model is not mapped yet).
- Everything must fit inside the event block. Wave data is rewritten inside the
  block, reusing the old wave area and the zero padding at its end; the track
  file never changes size. Half of the original events have room for about 38
  or more extra vehicles (up to 63), but eleven have room for fewer than 10, and
  *Don't Look Down* for just one. Adding a wave also needs space for the wave
  table; *Don't Look Down*, *Out Of Control* and *Highway to Hell* are too full
  for that. Removing vehicles frees space. `python scripts/waves.py list`
  shows the room left in every event.

### Practical tips

- Distances grow in the direction of travel. In a queue, the first vehicle has
  the largest distance; original queues keep about 15 units between cars and
  more for buses and trucks.
- The entry distance of most lanes is behind the placed queue, so timed
  vehicles join from behind.
- Many vehicles at once can still overload the game (see
  [high-density experiments](high-density-experiments.md)); the pool limits are
  shared by all waves.

## Where the data is

All offsets are relative to the event block: resource 1 of the event's
descriptor in the track's `GAMEDATA.BGD` (`event_offset` in
`resources/crash_events.py`; Grand Slam: `TRACKS/EU/C3_V1/GAMEDATA.BGD` +0x66000,
0x2800 bytes). The block is version 8 (`+0x28`). Offsets inside the block are
relative to its start and are relocated by the game when it loads the block.

| Location | Content |
| --- | --- |
| block `+0x3C` / `+0x40` | traffic sources: 16 bytes each — offset of a `u32` path list, offset of a `u32` start-node list, lane count, two flag bytes |
| block `+0x4C` / `+0x50` | **waves**: 0x58 bytes each |
| wave `+0x00…+0x34` | fourteen table offsets (lane speeds, density tables, lane maps); counts at `+0x40`, `+0x44`, `+0x48`, `+0x53…+0x55` |
| wave `+0x38` / `+0x3C` | offset and count of the **lane headers** |
| wave `+0x4C` | `f32` start time in seconds |
| lane header (12 bytes) | `+0x0` offset of the vehicle records · `+0x4` `f32` entry distance · `+0x8` total vehicles · `+0x9` placed vehicles · `+0xA` source index · `+0xB` slot within the source |
| vehicle record (32 bytes) | `+0x00` `u64` model ID (base 40) · `+0x08` `u64` trailer ID or 0 · `+0x10` `f32` distance (placed) · `+0x14` `f32` time (timed) · `+0x18` type · `+0x19` colour variant · `+0x1A…+0x1F` zero in all originals (preserved) |

Vehicle types seen in the originals: 1 car, 2 van, 3 van (second van group),
4 truck cab with trailer, 5 bus, 8 tram. Model group *g* of the event maps to
type 1, 2, 5, 3, 4 for *g* = 0…4; group 5 holds trailers.

Waves after the first also change lane speeds (the speed tables of the wave),
for example Grand Slam raises one lane of P21 from 30 to 50 when wave 2 loads.
The editor keeps those tables unchanged; a new wave added by the editor only
schedules vehicles.

## How this was established

The investigation followed the project's evidence ledger (kept locally in
`.investigations/traffic-waves/`, not published). In summary:

1. **Code (static analysis, Ghidra).** `FUN_002662e0` places the first
   `header+9` records of a lane at `record+0x10` along the path.
   `FUN_00267ec0` releases the next record when `record+0x14 <= clock`, using
   the entry distance `header+4`, and advances a per-lane cursor.
   `FUN_00163700` installs a wave (`event+0x4C`, stride 0x58) and stores the
   next wave's start time; `FUN_00166160` compares it with the event clock
   (`0x00522680`, seconds). `FUN_00269fa0`/`FUN_00269d20` relocate the block by
   walking these same counts, so a writer can move arrays inside the block.
2. **Savestate RAM.** The loaded block in RAM equals the disc bytes except the
   305 relocated offsets. Across 75 savestate snapshots of several events, wave
   index and lane cursors match the clock: e.g. one event shows wave 2 pending
   at 6.8 s (start 8.0) and loaded at 8.35 s with new lane lists.
3. **Controlled mutation in an isolated PCSX2 copy.** From the same Grand Slam
   savestate (clock 5.67 s), the control run loaded wave 2 at ≈9.1 s (+6
   vehicles at once) and released the timed car at 9.37 s. In a copy where
   only that car's 4-byte time was changed from 9.34 to 12.0, wave 2 loaded the
   same way and the car entered at 12.05 s.
4. **Placement check.** In the Grand Slam intro savestate, all nine wave-1
   placed vehicles sit within 0.5–2.5 units of the position predicted from
   their distance on the path's own distance table.
5. **All 100 events.** Every event parses; writing an unchanged schedule (or
   one exported to JSON and imported back) reproduces the track file byte for
   byte; adding a vehicle works in all 100 events.

A full-disc comparison of the first test ISO (Grand Slam, built with
`scripts/waves.py`) found 232 changed bytes, all inside the Grand Slam event
block, and the waves read back from the ISO equal the requested file.

## Known limits and open questions

- **Disc path not yet played.** The controlled test changed the block in a
  savestate's RAM. An exported ISO must still be played from the game menu to
  confirm the disc path end to end. The test ISO for that is described below.
- The clock starts with the event; whether it counts from the moment the
  event loads or from "GO" was not measured separately.
- A flag at `0x00665ea0` (set by some front-end routines) makes the game release
  every vehicle with a time of 45 s or less as soon as possible. Normal Crash
  play had it at 0 in every savestate. Its purpose is unknown.
- Not named yet: the source flags, the per-wave density and 0x48/0x10-byte
  tables, the `+0x9C` point list and the upper bits of the event flags at
  `+0xB4`. They are preserved byte for byte.
- The six model groups decide which models are loaded; the wave records name
  model IDs directly. Reordering models inside a group (the earlier Grand Slam
  ISO test) therefore probably does not change which models the waves spawn.
  This is an inference, not an observation.

## Play test: Grand Slam waves test ISO

`outputs/Grand Slam - waves test.iso` (local, not in the repository) was built
from the original ISO with `outputs/waves/grand-slam-test.waves.json`. Only
traffic changed; goals and the Crashbreaker are original.

1. Boot the ISO from scratch in PCSX2 and enter **Grand Slam** from the menu
   (a savestate would bring back the old traffic).
2. On the two-way street after the bend (path P21), the red `COMPCAR14` at the
   back of the queue should start **40 units further back** than in the
   original.
3. About **3 s** after the start, an extra **bus** enters behind that queue.
4. The second wave arrives at about **4 s** instead of 9 s.
5. Between **5 and 7 s**, three extra vehicles (two cars and a van, colour 2)
   join the second-wave lane on P20.
