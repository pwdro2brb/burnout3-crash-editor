# Research findings and limits

This page keeps the results of the first investigations. Later research identified
the event directories, the path geometry inside the BGD files and the
[traffic waves](traffic-waves.md); the Grand Slam edit also allowed checking the
`STAGEHED.BIN` record in the table loaded after boot. See the
[project history](project-history.md) and [native event editing](native-crash-events.md)
for the current state.

This summary contains structural facts and inferred names, without game bytes,
pseudocode, saves or dumps. Static observations and historical save-state
observations must not be treated as tests of a running modification.

## Researched profile

- USA executable `SLUS_210.50`, ELF32 little-endian MIPS/PS2 R5900.
- SHA-256 `e118dba952bf9fde6a04ee284bb1f06fa0bb49c9e04bbe762af1039dcc443c66`.
- Empty symbol table; function names are automatic or inferred. Ghidra with the R5900
  extension produced the analysis and pseudocode.

## Resources

- `GLOBALUS.BIN`: 16-byte header, 4,006 absolute ascending uint32LE offsets to
  UTF-16LE strings.
- 36 `GAMEDATA.BGD` files. Those examined have version marker 9 and the text
  `B3tGameDataGame`. The path section, the event directory and the event blocks
  (model groups and traffic waves) are now decoded; other sections are not.
- The `CRASH*.RWS` samples analysed are sound banks, not traffic layouts.
- The loader reads `TLIST.BIN` as a 4,096-byte block; its header starts with `(4, 36)`.
- `STAGEHED.BIN` holds 377 records at base `0x278`, stride `0x3e0`, confirmed by the
  analysis and by exact ordinals in every record. Each record has six `0x98` slots
  with two 64-bit IDs per slot; the goals and the Crashbreaker count are at
  `+0x3A0…+0x3AC`. No traffic coordinates live there: spawn data are in the track's
  event block.

## Candidate traffic pool

Static analysis proposed the layout below, confirmed structurally by every save state
examined since:

| Structure | Address / stride |
| --- | --- |
| Manager | `0x00527440` |
| Objects | `0x00539c10` / `0x180`, 254 entries |
| Nodes | `0x00551910` / `0x50`, 254 entries |
| Matrices | `0x00556870` / `0x50` |
| Object visual translation | object `+0xa0` |
| Two absolute physics points | object `+0x00` and `+0x30` |
| Translation in the following matrix | matrix `+0x30` |

The manager's first word points to the loaded event block; `+0x363a0` holds the next
wave's start time and `+0x363b1` the wave index (see [traffic waves](traffic-waves.md)).

Indices, free lists, free/allocated partitions, bitmaps, flags, counters and
backlinks matched the captures examined. Object counts include parent/child
components, so they are not the number of independent or visible vehicles. Some
components had a null node. The first two saves examined restored Crash results
screens, not references before GO.

## First milestone, 12/11/2026

An independent car was repositioned in a copy of a save state. Changing only the
lateral fraction moved the following matrix without moving the body. The confirmed
test coordinated X/Z of both physics points and of the visual translation with the
node's lateral parameter. The move persisted over the configured 30-frame step and
the collision box updated itself. See [repositioning-milestone.md](repositioning-milestone.md).

## Moving traffic in Grand Slam

The next reference restored the Grand Slam intro and countdown. In an approach state
an independent vehicle with initialized anchors got a horizontal offset of about 0.51
units and a new lateral fraction. After 30 and 120 configured frames the states
showed real movement, persistent lateral separation and automatic AABB and Y
updates. In a later variant with a larger offset the user reported a visible change
and working collision on the "first red car" — since identified as Grand Slam's wave-1
`COMPCAR14` on path P21. See [moving-traffic-reference.md](moving-traffic-reference.md).

## First additional vehicle

A local trial called the game's own creation routine to add an independent instance
to Grand Slam. Counts went from 12/10 objects/nodes to 13/11 with one more collision
descriptor; free lists, bitmaps, backlinks, the path chain/grid and the collision
records passed. The user reported that the car appeared and the collision worked. See
[vehicle-creation-milestone.md](vehicle-creation-milestone.md).

## Catalogue and external editor

The 40 traffic identifiers were decoded in base 40 and tied to the game's own label
table and resources (`COMPCAR14` is **Car**, `HEVYCAR33`/`HEVYCAR35` **Van**,
`HEVYCAR20` **Bus**). The external editor lists vehicles, shows their positions from
above, applies lateral offsets and prepares batches; a real PINE integration confirmed
reading, repositioning and creation, and the user confirmed batches, trucks with
trailers and state export. Details in [editor-status.md](editor-status.md).

## Traffic waves (26/11/2026)

Crash traffic is scripted per event: waves with start times, lanes and vehicle
records, in the event block of `GAMEDATA.BGD`. Established by static analysis, by
comparing the loaded block with the disc, by savestate snapshots and by a controlled
mutation in an isolated emulator. See [traffic-waves.md](traffic-waves.md).

This repository is an experimental research base. It does not prove that every
location of the game can host Crash events.
