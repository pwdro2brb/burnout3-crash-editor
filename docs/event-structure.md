# How a Crash event is put together (and what a new level needs)

This page collects what is known about the data that makes one Crash level, as a
base for creating new levels: at a place the game already uses, and at a place no
event uses. Research profile: Burnout 3 USA `SLUS-21050`. Evidence is kept in the
local ledger `.investigations/event-places/` (not published).

## Level numbers

The level number players use (Crash 1 to 100) is the event's position in the game's
progression order (`PRGDATA.BIN`). The editor's event list now shows it (**No.**),
and the header of an event reads, for example, *Level 8 · Grand Slam*.

## The four resources of an event

Every event has a descriptor (0x800 bytes, in `STAGEHED.BIN` and again in the track's
`GAMEDATA.BGD`) with the medal goals (`+0x3A0`), the Crashbreaker count (`+0x3AC`) and
four resources (size, offset pairs at `+0x3BC`). The event loader (`FUN_0014f050`, a
state machine) reads them in this order:

| Resource | Size (Grand Slam) | What it is | Shared? |
| --- | --- | --- | --- |
| 0 | 0x800 | **Start grid and preview camera.** Six transforms (the player's car starts on transform 0), four unknown 0x20-byte entries at `+0x1E0`, and the preview camera route at `+0x3E0` ([event cameras](event-cameras.md)). Relocated by `FUN_003a20e0`. | one per event |
| 1 | 0x2800 | **The event block**: traffic waves, lane speeds and model lists ([traffic waves](traffic-waves.md)). Loaded right after resource 0 and relocated by `FUN_00269fa0`. | one per event |
| 2 | 0x25800 | **The traffic paths.** After `FUN_00269f10` relocates it, the loader points every path descriptor (`0x52288C + i×0x4C`) at its 0x14-byte entries (count at `+8`). | **the whole track file** |
| 3 | 0x2F800 | Further track data handed to `FUN_00271920` and to globals at `0x64D344…0x64D368` (one of them a 758-entry table of float pairs read by distance). Not decoded yet. | **the whole track file** |

In all 100 events, resources 2 and 3 are the same for every event of a track file:
the ten events of `US_C2_V1`, for example, all point at the same two. So the traffic
network covers the whole crash area of the track, and **any lane of the track can be
used by any of its events**. What makes one level different from another is the
descriptor, resource 0 and resource 1.

## Levels that share a place

Levels that happen "at the same place" start at the same spot. Grouping the 100 starts
gives **68 places**; starts on the same track are either within 36 units of each other
or at least 59 units apart. These levels share their start:

| Track | Levels |
| --- | --- |
| US_C2_V1 | 2 Cross Traffic, 44 Hold Tight, 62 Bus Blockade |
| US_C1_V2 | 3 Marina Mayhem, 43 Bay-side Blitz, 65 T-boned |
| US_C2_V1 | 5 Demolition, 25 Wrecks City, 82 Grid Locked |
| EU_C2_V1 | 9 Roadblock, 30 Don't Look Down |
| EU_C4_V1 | 10 Grapes of Wrath, 93 Gate Crasher |
| EU_C1_V1 | 11 Pump Up the Tram, 51 Winter Wipe-out, 73 Run for the Bus |
| EU_C3_V1 | 12 Get Bent, 49 Cliff Hanger |
| EU_C4_V2 | 14 Jack Knife City, 53 Haul A$$ |
| AS_C3_V2 | 16 Paradise Peril, 37 Tropical Storm, 99 Lost Luggage |
| AS_C3_V1 | 18 Ruined Holiday, 77 Steel Tsunami, 97 Tourist Trap |
| US_C3_V1 | 21 Showdown, 42 3 Ways to Fly, 64 Fear Factor |
| US_C1_V1 | 22 Leap of Faith, 63 Falling Down |
| EU_C3_V1 | 27 Riviera Rampage, 52 High Roller |
| EU_C1_V1 | 28 Riverside Wreck, 87 On Rampage |
| EU_C4_V2 | 29 Grape Fear, 48 Country Chaos |
| EU_C3_V1 | 31 Spin the Wheel, 71 Go for Broke |
| EU_C1_V1 | 33 Snow Joke, 68 Crash Landing |
| AS_C2_V1 | 36 Exit the Dragon, 96 The Crate Escape |
| US_C2_V1 | 41 Hate to be Late, 46 Traffic Jammed |
| US_C3_V2 | 45 Bridge Too Far, 81 Pick up the Pieces |
| EU_C2_V1 | 54 Lanes Lunacy, 94 Highway to Hell |
| AS_C1_V1 | 55 Road to Ruin, 80 Eastern Block |
| AS_C3_V1 | 58 Airstrike, 98 Pure Scores |
| US_C1_V2 | 66 Sunshine Smash, 86 Tram-Pulled |
| EU_C3_V1 | 89 Jumping Jam, 92 Ship Wrecked |

The event list shows the same information in the **Same start as** column.

## What a new level needs

The game has 100 event slots; a new level takes the place of an existing one (the
slot keeps its name in the menus). With what is known now:

- **New level at a place the game uses.** Pick an event on that track and change its
  traffic with the Traffic waves tab: every lane of the track is available, including
  the lanes other events use. To also *start* where another event starts, the start
  grid (resource 0) has to be copied from that event — the next editor feature to build.
- **New level at a place no event uses.** Same track, new start grid (position and
  heading of the car), a new preview camera route, and traffic on the lanes there. This
  works only where the track's traffic paths (resource 2) exist; the editor already
  shows them all on the map.
- **Still unknown** (open questions in the ledger): what resource 3 holds; what the
  four entries at resource 0 `+0x1E0` are (two next to the start, two near a far
  traffic queue); whether moving the start grid gives a playable level (needs a test
  ISO and a play test); and how the results tally camera picks its route.

## The crash cameras

What was observed in an isolated PCSX2 (Grand Slam, no controller input) with the
camera block at `0x1E32A00` (in that session):

| Field | Meaning (observed) |
| --- | --- |
| `+0x50` | camera position |
| `+0x60` | a point 10 units below the camera |
| `+0x70`, `+0x78` | horizontal heading (x, z) |
| `+0x4C` | 10.0 most of the time, 13.8 once (a zoom value?) |

- Before GO the camera holds a still view behind the start grid.
- While driving it follows the car 12.1 units away.
- About two seconds before the car hit the queue, the camera **cut to a fixed spot
  beside the road** (about 22 units from the crash point and 11.6 units higher), then
  went back to following the car, and stayed 15.2 units from it once it stopped.
- None of these camera positions is stored as world coordinates anywhere in the track
  file, so the crash camera is placed by the game at run time from the situation, not
  from data in the event. A new level should therefore get its crash camera for free.
- Without input the game restarts the event about 14 seconds after the crash, so the
  results tally was not reached in these runs. Savestates taken during the tally (start,
  middle, the moment it stops) are still needed for that camera.

## Traffic model shapes

The traffic model files (`.BTV`) store their vertices in PS2 VIF `UNPACK V4-32` blocks
(command byte `0x6C`): about 4,200–4,800 points per model. Plotted from above and from
the side, the points already show recognisable shapes (the bus windows, the tuk-tuk),
but several parts (wheels, doors) are stored in their own local coordinates. Decoding
how the parts are placed would let the editor draw a real preview of every model.
