# Many vehicles and experimental tests

Investigation started on 13/11/2026 and updated on 14/11/2026, for Burnout 3 USA
on PCSX2 1.7.2521.

## What the error says

The user reported failures after adding more than fifty vehicles to the original
traffic: some lose their physics, and a crash with many vehicles involved can
freeze or end in the assert `FQC = 0 on VIF FIFO READ!`. This is what the user
observed in some events; it does not establish a general maximum of fifty added
vehicles.

In this PCSX2 version, `ReadFIFO_VIF1` requires a non-zero FIFO count before
reading. On the transfer path to memory the routine waits for the GS, takes the
data and reduces the remaining amount. The assert means the emulator received a
read with a zero count. It does not measure cars, physics bodies or free space in
the game's pools, and on its own it cannot separate an invalid game state from an
emulation behaviour or an earlier cause.
[Official FiFo.cpp](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/FiFo.cpp#L42).

`FQC` is the amount of data in the FIFO and `FDR` its transfer direction in that
version's register model. Disabling the check would not show that a transfer's
data are correct nor fix the lost physics. This work did not change the emulator
or its asserts.
[Official VIF registers](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/Vif.h#L112).

## There are several finite resources

In later tests the user narrowed the instant failure down to about **61–65
vehicles already involved in the crash**. Outside that state the user could keep
more vehicles on screen, and also saw scenery geometry and nearby vehicles shrink
or disappear when more than fifty cars were concentrated in one place. These are
separate observations of crash physics and rendering, with no instrumented capture
yet of which resource ran out. Cabs, trailers, the player and other bodies are not
assumed to use a single slot per visually counted vehicle.

That range makes the 64-record structure below a stronger hypothesis for the
conversion to crash physics, but it does not replace identifying the allocator and
counting occupancy during the failure.

The traffic pool is only part of the problem. The executable has separate
structures, shared with other scene objects:

| Resource | Limit or observed behaviour | What it does not prove |
| --- | --- | --- |
| Traffic objects and path nodes | 254 entries in each pool; truck parts also use objects | that 254 cars can take part in a crash |
| Collision descriptors | the researched region holds 1,224 records | that all can be processed at once with full physics |
| Spatial-sort endpoints | 2,448 per axis, two per descriptor | that other stages have free resources |
| Candidate collision pairs | the examined routine only adds pairs while its counter is below 256 | a 256-vehicle limit or the exact cause of the VIF assert |

The pair limit is explicit in function `0x001b8f00`: the test at `0x001b9198`
compares the counter with `0x100`, and the following branch skips the insertion
when the list is full. Each record is `0x30` bytes. Admitted pairs are sent to
`0x001b7220` for collision handling.

In a cluster of vehicles the number of possible pairs grows faster than the number
of cars: 24 objects already make 276 pairs. The game filters which boxes really
overlap before recording pairs, so a contact queue can be under pressure without
exhausting the traffic pool. This does not show that the user's round hit that
queue nor which contacts would be dropped.

A set of 64 larger records, initialized at `0x001b9850` with size `0x2430` and
constructor `0x002513f0`, was also found; collision handling uses fields of that
layout for one kind of body. The full link between creation, conversion of traffic
to crash physics, occupancy and release of those records still has to be mapped,
so **64 is not presented as a general vehicle limit nor as the proven cause of the
failures**.

The value `0x001b93bc` in the stack text matches an instruction right after the
pair-handling call in the USA executable. The stack shown does not include the
guest register context needed to attribute it to the game's PC; the match is a
lead, not a diagnosis.

## What experimental mode can unlock

The user also reported that spacing below eight units for cars and thirty for
buses/trucks works in their trials: the vehicles start overlapped and queue until
they can pull away. The 8/30 values are conservative choices of the editor's
normal mode, not proven engine minimums; experimental mode already accepts
smaller positive distances. Congestion matters when reading speeds: the desired
speed and the current progress can differ, down to zero progress.

The editor can relax its own per-request amount, distance and proximity limits to
try denser scenes. That does not enlarge the engine's fixed structures or load
missing models, and the mode must be clearly flagged: **there is a high chance of
a crash, freeze or lost physics**.

A loaded compatible model, a recognized path, finite values, a core pause for
writes and checks of the temporary code are still required, and the editor refuses
to go beyond known memory regions and capacities. An "unlimited" option cannot turn
an address outside the pool into a valid record.

Creating more cars and raising the capacity of a crash are different tasks. Real
capacity growth needs every consumer of each structure identified, storage and
indices adjusted, and conversion, contacts, drawing and effects validated. This
research did not implement that.

## Validation still missing

To isolate the lost physics, the next instrumented trial should keep a reference
of the same event and raise density in steps, comparing scattered traffic,
clustered vehicles without impact, and the crash. Counts of objects, pairs,
converted bodies and collisions need to be observed before the failure. An assert
without that capture does not prove which resource ran out.

This pass read official sources and preserved static exports; two more functions
were exported with Ghidra in read-only mode. No crash was triggered, no input was
sent to the game and no private capture or decompiled code is distributed here.

With [traffic waves](traffic-waves.md) the density of an event can now also be
changed on the disc (more placed or timed vehicles per wave). The same limits
apply: waves share the pools above.
