# Roadmap for the Crash event editor

The **first playable milestone** is to enter Grand Slam from the menu, find the first
red car somewhere else on the same street and be able to crash into it. With the
[traffic waves](traffic-waves.md) decoded, the data that place that car are known and
editable; a test ISO is waiting for the play test. [History and evidence](project-history.md)

## Eight steps

The GitHub issues hold the completion criteria and results as the research advances.

| Step | Deliverable | Status (26/11/2026) | How to recognize the result |
| ---: | --- | --- | --- |
| 1 | Identify the origin of the red car in Grand Slam. | **Found.** Wave 1, lane P21, 4th placed vehicle: `COMPCAR14` at distance 1486.08. | The path, direction and condition that bring the car onto the road are explained. [Issue #1](https://github.com/pwdro2brb/burnout3-crash-editor/issues/1) |
| 2 | Move a vehicle persistently on the ISO. | **Implemented**, play test pending (`Grand Slam - waves test.iso` moves it 40 units back). | An isolated edit changes where the car appears relative to a street landmark; re-entering from the menu brings it back to the chosen point, it follows the lane and takes part in the crash. [Issue #2](https://github.com/pwdro2brb/burnout3-crash-editor/issues/2) |
| 3 | Edit the position on the event map. | **Partly.** The Traffic waves tab draws lanes, placed vehicles and entries; distances are typed, not dragged yet. | The author picks the target, tells lane, direction and overlapping roads apart, chooses the destination and repeats the edit without typing coordinates. [Issue #3](https://github.com/pwdro2brb/burnout3-crash-editor/issues/3) |
| 4 | Add and remove traffic in the native definition. | **Implemented** (vehicles, lanes and waves, within the free space of the event block); play test pending. | One variant gains a car and another loses the chosen vehicle; it also works for traffic that enters after the start. [Issue #4](https://github.com/pwdro2brb/burnout3-crash-editor/issues/4) |
| 5 | Tune behaviour and special vehicles. | **Started.** Trucks with trailers, buses and trams are scheduled like any vehicle; per-wave lane speeds are located but not editable yet. | Speed and spacing on a free road and in a queue; oncoming traffic, stopped vehicles, buses and cab-with-trailer keep their link while turning and crashing. [Issue #5](https://github.com/pwdro2brb/burnout3-crash-editor/issues/5) |
| 6 | Create a Crash at another junction of an existing track. | Next research target. | Inside an existing menu entry, the player starts, reaches the new junction, causes the crash and reaches the results screen; the round can be repeated. [Issue #6](https://github.com/pwdro2brb/burnout3-crash-editor/issues/6) |
| 7 | Reopen and share a native edit project. | **Partly.** Waves travel as `.waves.json`; `scripts/waves.py build` applies several files, including two events on the same track. Goals and model order are not in the file yet. | Two people with identical extractions apply the same project and get the same files; two events sharing a track keep both edits. [Issue #7](https://github.com/pwdro2brb/burnout3-crash-editor/issues/7) |
| 8 | Investigate an own menu entry and progress. | Not started. | If extending the catalogue is viable, an extra event appears next to the original 100, opens by name and keeps its medal after restarting the game. [Issue #8](https://github.com/pwdro2brb/burnout3-crash-editor/issues/8) |

## Testing the first persistent move

1. Boot `Grand Slam - waves test.iso` from scratch and enter Grand Slam from the menu
   (a savestate would bring back the old traffic).
2. On the two-way street after the bend (path P21), the red `COMPCAR14` at the back of
   the queue should start 40 units further back; about 3 s in, an extra bus joins that
   queue; the second wave comes at about 4 s instead of 9 s, and three more vehicles join
   its lane between 5 and 7 s.
3. Crash into the moved car and re-enter from the menu to confirm the edit persists.

## Toward a new junction (step 6)

To move the crash itself, the following event data still need to be decoded, all in
the same event block or its descriptor:

- **Resource 0 of the event descriptor** (loaded right before the event block). Its
  first transform is the player's start position (confirmed), and its point list at
  `+0x3E0` is the route of the preview fly-by camera (traced in PCSX2). The meaning of
  the point codes and of the entries at `+0x1E0` is open. See [event cameras](event-cameras.md);
- **the `+0x9C` list** of 4-byte points (0 to 24 per event). Every one of the 725
  points of the 100 events decodes as a valid (16-bit node, 16-bit path) position on
  a traffic path of its track, often the same node on neighbouring lanes, and 412 of
  them sit on lanes used by the waves. Grand Slam has (node 193, P20) and (node 322,
  P21). Their purpose (stop lines, crash zone or the results camera) is open;
- **the results camera.** After the crash the camera travels along a fixed route,
  showing each wrecked vehicle's value, and stops after the last wreck on the route
  or at the end of the route. Not observed yet; the next step is savestates taken
  during the tally (start, middle, stop) in an event where it shows every wreck and in
  one where it stops early ([event cameras](event-cameras.md));
- the traffic sources (`+0x3C`) that bind lanes to paths, and the per-wave lane speeds;
- the crash-zone and scoring rules (unknown location).

## Vehicle limits

- **The game.** The crash-physics manager holds a fixed table of 64 records of 9,264
  bytes (`0x2430`), embedded in a larger structure with other tables after it
  (initializer `0x001b9850`). It matches the user's observation that the game crashes
  at around 64 crashed vehicles. Raising it would mean patching the executable to
  move that table to free memory and fix every access to it: possible in principle,
  large and risky, not started.
- **The editors** do not cap the number of vehicles. They warn instead: above 50
  vehicles the game does not work properly (lost physics or rendering), and around
  64 crashed vehicles is where it crashed in tests. The Traffic waves tab and
  `scripts/waves.py` count the vehicles an event can put on the road and warn only
  when an edit goes beyond 50 and beyond the original event (four original events
  already schedule 51 to 56 over the whole event). The live editor warns from the
  number of vehicles present.
- **The event block.** What does limit wave edits is the free space inside the
  event block (fixed by the sector layout of the track file). Growing a block means
  moving the following resources of the BGD and, in RAM, the resources loaded after
  it; not done yet.

## Dependencies that can change the plan

- **Room in the event block.** Wave edits stay inside the block, whose size is fixed by
  the sector layout of the track file. Growing a block would mean moving the following
  resources of the BGD and rebuilding the directory. About half of the events have room
  for 38 or more extra vehicles; eleven have room for fewer than ten.
- **Density and physics.** Record separately the vehicles present, the concentration at
  the junction and the vehicles converted for the crash. The failures seen with about
  61–65 involved guide the trials; the exhausted resource is still unknown.
  [High-density experiments](high-density-experiments.md)
- **Disc load path.** The release rule was confirmed on a savestate's RAM; the play test
  of the exported ISO closes the loop through the disc.
- **Progress.** The editor reads five groups of twenty events. An extra menu entry
  depends on understanding the name lookup in the executable, the progression indices
  and the memory-card save.
