# Burnout 3 Crash Editor — history and current state

The goal is to create Crash events where the author picks the junction, the traffic
and the goals. **Grand Slam is the reference event.** The player has already tested
moved and added vehicles in a live session, an ISO with edited goals and models, and
now an ISO with edited [traffic waves](traffic-waves.md). Next steps are in the
[roadmap](roadmap.md).

## What can be edited today

| Where you work | What the editor offers | How the edit is repeated |
| --- | --- | --- |
| Paused session in PCSX2 | List of vehicles and loaded models, lateral position, creations behind a reference or at a point projected on a path, batches, experimental visual variants and group nominal speed. | The session can be kept in a local state; a JSON recipe stores actions that depend on compatible references. |
| Scene project | The **Project** tab keeps an original base, saved scenes and commands to test, repeat and recover the base; **Manage slots…** archives a state and verifies the copy before freeing the slot. | The project manifest references local `.p2s` files. The player confirmed the export; restoring that specific exported file has no individual confirmation yet. |
| Game files | **Project → Native events / traffic waves…** works with the emulator closed: 100 events, track paths, model order inside a group, the three medal goals, the Crashbreaker wreck count and the **traffic waves** (when and where every vehicle enters). `scripts/waves.py` does the same from the command line with shareable JSON files. | Exports the changed resources or builds a new ISO. The game reads the edit when the event is entered from the menu. |

Guides: [session editor](editor-quickstart.md), [scene projects](custom-event-projects.md),
[native editing](native-crash-events.md), [traffic waves](traffic-waves.md).

## From the extraction to the first moving car

1. **Executable and resources.** The researched profile is Burnout 3 USA, `SLUS-21050`,
   CRC `BEBF8793`, on PCSX2 1.7.2521. `SLUS_210.50` is an ELF32 MIPS little-endian for
   the Emotion Engine/R5900 with an empty `.symtab`; functions were analysed with
   Ghidra and the Emotion Engine extension. [Early findings](findings.md)
2. **ISO inventory.** The USA ISO9660 extraction has 775 files, including IOP modules
   (`.IRX`) and MPEG-2 video (`.M2V`). `GLOBALUS.BIN` holds 4,006 UTF-16LE strings,
   `STAGEHED.BIN` 377 records, and there are 36 `GAMEDATA.BGD` track files.
   `PRGDATA.BIN`, the localized titles and the track descriptors later identified the
   Crash events by name. [Event directory](native-crash-events.md)
3. **Test copies and first saves.** The first states showed results screens; others had
   buses stopped before the ramp and slow vehicles far from the junction, which led to
   choosing a reproducible approach. Moving a car required coordinating the two physics
   points, the visual position and the lateral position on the path; a 30-frame
   comparison confirmed the move and the collision-bound update.
   [First repositioning](repositioning-milestone.md)
4. **Grand Slam.** On the two-way street after the bend, moving traffic could be
   followed. A capture tied object 9 to node 8 and path 21; the move persisted over 30
   and 120 frames. In a more visible variant the player recognized the first red car and
   confirmed the collision. That car is now identified in the event data as the fourth
   vehicle placed by wave 1 on P21 (`COMPCAR14` at distance 1486.08).
   [Moving reference](moving-traffic-reference.md)
5. **First extra car.** Creating an independent car took the counters from 12 to 13
   objects and 10 to 11 nodes; the new car was aligned about 10.85 units behind the
   reference and the player saw and hit it. The model was `COMPCAR14`; the player later
   also confirmed the `HEVYCAR33` van. [Vehicle creation](vehicle-creation-milestone.md) ·
   [Editor tests](editor-status.md)

## What the traffic tests taught

- **Models and late entries.** 40 traffic models were identified from their base-40 IDs
  and the game's labels (`HEVYCAR20` is a bus, `HEVYCAR33` a van). Vehicles that enter
  during the round can be references once their path and physics are valid; they come
  from the scripted waves. Batches can alternate loaded models. Visual indices 0–7 are
  still experimental. [Catalogue and batches](slots-and-mixed-traffic.md)
- **Pause and batches.** The PCSX2 setting could hide the render window on Esc, so the
  editor got pause/resume buttons and recovery of pending creations. The player
  confirmed the car batch, the state export and, after the physics-wait fix, batches
  and group speed. [Pause and finish](batches-trucks-and-pause.md) ·
  [Pending recovery](traffic-capacity-and-trucks.md)
- **Direction, position and speed.** Eligibility depends on each vehicle's own path and
  physics; a car stopped in a queue can have a valid node, a parked scenery object may
  need another method, and driving against the player does not decide eligibility by
  itself. The editor separates the speed target from the actual progress. In the
  player's tests, vehicles could wait for room when spacing was below 8 units for cars
  or 30 for buses/trucks (editor margins). [Paths and speed](routes-and-speed.md)
- **Large vehicles.** The player confirmed that the truck with a trailer appeared and
  worked. Cab and trailer have their own models and collisions and use two objects and
  one path node. Bus creation and a fourth tanker remain unconfirmed.
  [Trucks, buses and capacity](traffic-capacity-and-trucks.md)
- **Density.** The player saw lost rendering or physics with more than about 50
  vehicles concentrated and a freeze with about 61–65 vehicles involved in the crash.
  The 254-object and 254-node pools also serve other components; usable capacity
  depends on the physics state and the scene. `FQC = 0 on VIF FIFO READ!` is an
  emulator failure whose cause in the simulation is still being investigated.
  [High-density experiments](high-density-experiments.md)

## The first event edited on the ISO

The 100 Crash events use 18 tracks of the catalogue. Reading all 36 track files found
2,572 paths; in Grand Slam the 27 paths and 2,821 point pairs matched the capture in
memory. Key `1G0007EUC3V1` links Grand Slam to track `EU/C3_V1`. Each event has six
model groups. [Event and track structure](native-crash-events.md)

| Grand Slam field | Original event | Test ISO |
| --- | ---: | ---: |
| Gold | $280,000 | $310,000 |
| Silver | $200,000 | $200,000 |
| Bronze | $60,000 | $60,000 |
| Wrecks to unlock the Crashbreaker | 10 | 6 |

The test also swapped `COMPCAR14` and `COMPCAR12` in the first group. A full ISO
comparison found **ten different bytes** in `DATA/STAGEHED.BIN` and
`TRACKS/EU/C3_V1/GAMEDATA.BGD`. After boot the table loaded by the game held the three
expected goals and the counter 6. **The player then confirmed the test worked.** At
that revision 424 distributable tests passed.

## Traffic waves (26/11/2026)

The question "why do most cars appear at once and a smaller batch later?" was answered:
each Crash event schedules its traffic in **waves**. Wave 1 places most vehicles when
the event starts; later waves load at fixed times (1–21 s in the originals) and each
lane can release extra vehicles at set times. The data sit in the event block of the
track's `GAMEDATA.BGD`, were decoded for all 100 events, and can now be edited in the
editor, as JSON, and from the command line. The release rule was confirmed by a
controlled mutation in an isolated PCSX2. A Grand Slam test ISO with moved, added and
re-timed vehicles is ready for a play test. [Traffic waves](traffic-waves.md)
