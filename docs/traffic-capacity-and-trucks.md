# Late traffic, restrictions and trucks

Research updated on 13/11/2026 for the researched USA executable.

> **Late traffic is scripted.** Vehicles that appear after the start of a Crash
> event come from the event's [traffic waves](traffic-waves.md): timed vehicles of
> each lane and later waves that load at fixed times. That is why the live editor
> can find valid references that "appear later".

## Current results and restrictions

The user reported creating several vehicles in different levels, including behind
traffic that appeared later and behind other added vehicles. During the
single-creation stage the examined local log confirmed 20 `spawn_finished`
operations over six models, with references on paths 2, 3, 6 and 21 and logical
references to created actors. These are specific trials; they do not validate every
event and situation.

The editor uses resources that are already loaded. The first version admitted
creation with a consistent independent association to types 1 or 2. The visual
category does not necessarily match the type byte: models called Car, Van or
Motorhome have admitted associations. Creating a model that is not loaded requires
investigating its loading and dependencies; changing the ID is not enough. The next
version also admits batches of 1 to 8 and native loaded pairs of type-4 cab with a
type-11 trailer; see [batches-trucks-and-pause.md](batches-trucks-and-pause.md).

This stage's profile also admits independent types 3/5 with a consistent native
association: `HEVYCAR17/18` vans (type 3) and `HEVYCAR19/21` buses (type 5). It
requires two non-degenerate physics points, coherent render and collider, a valid
path and occupancy. `HEVYCAR20` that is only loaded stays blocked without an active
type-5 association. Special types 6 to 10 are not enabled. A real bus-creation test
is still pending; the distance admitted for a bus chosen or used as a reference is
30 to 50 units. A type-5 bus batch in v2 format was prepared and was waiting for the
user to resume traffic; that does not prove presence, movement, collision or finish.
157 distributable and 40 private tests passed in that validation round.

After reopening the revision with the protected finish, the user confirmed batch and
real export. The local log also includes eight `HEVYCAR33` finished on path 53 and
two `HEVYCAR22` + `HEVYCAR27` pairs finished on each of paths 34 and 53. A later read
logged a structural profile refusal with a pending request; that does not prove a
freeze or a general failure and does not remove the physics, link and path
restrictions. Restoring the exported `.p2s` and a fourth tanker remain untested.

With all ten slots taken in the current session, the PINE export through the editor
is refused without replacing saves. **System → Save state → File…** with a new
destination produced a control copy validated as a ZIP with 32 MiB of EE memory.

There is no test of direction relative to the player in the controller. It requires
initialized physics points, a valid path and agreement between orientation,
following speed and path progression. In a paused read of the current event, four
cars oriented against the player had uninitialized physics points and zero following
speed. That explains the refusal of those four cases without establishing that all
oncoming traffic is incompatible. The interface now shows the reason for a block
when an object is selected.

## Capacity and the protection error

The pools are shared. The researched nominal object capacity is 254 records,
including truck components; that is not 254 safe vehicles and does not replace the
node and collision capacities. Creation also depends on loaded resources and usable
room behind the reference; chaining creations near the start of a path can use up
that stretch.

The error **There is an unrecognized code change in the traffic update** is another
protection: the bytes of the routine's return differ from those accepted by the
profile. It does not show pool exhaustion or the end of the track. The historical
cause of the user's screenshot was not captured; in the later read the return was
already original and the temporary area zeroed, so the game did not need changing.

The controller now logs `profile_rejected`, including the pause state, the return
bytes and the small request ID, in the local log, so an old request can be told
apart from another change if the error comes back. A recognized request from another
session gets specific guidance; unknown code stays blocked and is never "restored"
by guessing. These diagnostics stay outside the repository.

A pending request investigated later came from reloading a state saved before the
cleanup. **Finish pending request** now checks the local log and the canonical v1/v2
landing payload, requiring completion and the return of control before cleaning. A
real recovery changed only the 4 KiB temporary area; objects, nodes and matrices
stayed byte-identical and no vehicle was repositioned. The old recipe and its
alignment were not recovered. The per-generation v2 token prevents accepting another
request's completion. With the game identity confirmed and the profile invalid, the
connection is kept for that explicit recovery; listing and mutations stay blocked
until a valid read.

## Cab and trailer are one set

The examined traffic callers request a primary of type 4 and a secondary of type 11,
with separate model IDs. The creator stores the child in `primary+0x110` and the
parent in `child+0x10c`. The primary has a path node; the secondary follows the set
without using a second node. Both have their own physics descriptors.

A preserved save holds ten `HEVYCAR22` cabs and ten trailers: three `HEVYCAR29`
tankers, four `HEVYCAR27` flatbeds and three `HEVYCAR30` covered trailers (the file
kept its hash during the read). That proves more than three type-11 components,
including four flatbeds of the same model.

For a similar set, the expected extra use is:

| Structure | Expected extra use |
| --- | ---: |
| Objects and their occupancy records | 2 |
| Path node, chain and grid | 1 |
| Collision descriptors | 2 |
| Endpoints per axis | 4 |

The interface represents the set as one unit with a separate cab and trailer choice,
keeping both physical objects. It only offers native pairs observed and loaded; a
trailer is never created on its own. The user confirmed a truck with a trailer
worked, and the local log includes the finish of a `HEVYCAR22` + `HEVYCAR27` pair.
That does not validate every pair, the candidate composite move or a fourth tanker.

In the [traffic waves](traffic-waves.md) the same set is one vehicle record of type 4
with a trailer ID, for example `HEVYCAR22` + `HEVYCAR27` in Grand Slam.

## Is there a limit of three tankers?

No such limit was found in `0x164a50` (creation), `0x1864f0` (initialization),
`0x1b85f0` (collision registration) or the examined callers. The `%3` seen in the
creator picks an attribute among three manager bytes; it does not count tankers.
The capacity conditions are shared.

That does not prove four tankers and their explosions are stable: later damage,
explosion and effects routines were not covered by this search. Three in an event's
original design does not establish the engine's maximum.

The decisive test is adding a fourth cab + tanker to an isolated copy that has three,
using a native combination already observed: first check both objects, links,
node/grid and colliders; then movement and, with the user driving, collision and
explosions. Existence, movement and impact are separate checks. No fourth tanker was
created in this investigation; with traffic waves it can now also be scheduled on the
disc in events that load a tanker trailer.

The static conclusions reuse the local exports of `0x164a50`, `0x1864f0`,
`0x1b85f0`, `0x2662e0`, `0x267ec0`, `0x267800` and `0x266ae0`. Exports and saves
stay private.
