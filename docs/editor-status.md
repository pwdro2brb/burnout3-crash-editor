# Current-event editor: implementation status and model identification

This page records what the live-session editor implements, what was observed in
real runs, and where its limits are. The how-to is in the
[first-use guide](editor-quickstart.md).

## Slots and mixed batches

The **Project** tab can archive a chosen slot with verified copies, batches can
use an independent sequence of models and alternating visual parameters, and
references standing still (zero progress) are admitted. There is no filter on
the player's direction; the path, native orientation and physics admitted by
the profile are still required. The reason for a blocked action shows in the
details.

Archiving verifies the copies and the identity of the files before freeing the
slot's names; other saves are kept. The manager needs a pause and no pending
creation, re-checks the pause during the operation, and stops if something
changes outside; copies and remaining files are kept. It is not atomic with
external emulator actions.

Mixed batches validate each model, type, trailer and variant and reserve
objects for the whole sequence before the first group. Recipes record the items
one by one and regroup them on replay. Recovering temporary code still needs a
matching journal and canonical payload.

Static analysis and preserved captures show the primary visual argument at
object byte `+0xC9`, with natural indices 0–7. The link to the colour palette is
not closed: these values are not presented as eight proven colours per model.
Trailers have a separate visual argument, preserved by the editor. Details in
[slots-and-mixed-traffic.md](slots-and-mixed-traffic.md).

## Test history

| Revision | Automated tests | Notes |
| --- | --- | --- |
| 13/11/2026 (trucks, guards) | 157 distributable + 40 private | first truck pairs |
| 14/11/2026 (paths, speed) | 241 + 45 private | offline path/speed checks on preserved memory |
| 15/11/2026 (finalization, group speed) | 271 + 47 private | the user later confirmed **"Everything is working!"** |
| 15/11/2026 (event projects v1) | 331 + 49 private | offline only; in-game restore pending |
| 15/11/2026 (slots, mixed batches) | 380 + 50 private | three real-link subcases skipped by Windows permissions |
| 19/11/2026 (native editing, Grand Slam ISO) | 424 distributable | the user confirmed the edited ISO worked |
| 26/11/2026 (traffic waves, English) | 444 distributable | waves module, CLI and tab; full English UI |

"Private" tests use local captures of game memory and are not distributed.

### 15/11/2026: finalization and group speed

The user reported that creating several cars worked, but the editor kept
waiting for physics/PCSX2 and blocked new edits. The flow had an unbounded wait
for actors whose physics did not yet allow confirming the alignment. The
revision limits that step to five seconds after the first paused check with all
records finished, a recognized payload, the original hook and the completion
token of the matching generation. On timeout it cleans only the admitted
temporary code, keeps the native vehicles, cancels the queue and leaves the
batch out of the recipe. Identity and completion are checked again before the
cleanup. **Finish pending request** ends that wait at once; incomplete
execution or unknown code stays blocked.

**Ctrl/Shift** selects several records and **Select speed-eligible** gathers the
enabled ones. One action applies the same nominal target to the whole selection
after validating every record; a blocked target stops the action instead of
being skipped. Only each node's desired control is changed; progress and physics
stay computed by the game. Select the cab rather than the trailer.

An actor seen after the initial reference can be edited if it passes the
profile, even without a confirmed creation in the recipe. A recipe that depends
on it cannot be saved as JSON; a `.p2s` keeps the session, or a new connection
can adopt the current scene as the reference.

### Event projects, first version

The **Project** tab organizes the name, the original base and the versions of
the edited scene. **Test scene** saves before resuming; **Back to start**
restores the last saved scene. Opening a project or restoring the base starts a
new editing session without rebuilding the old JSON recipe.

Automatic loading needs restore evidence, besides the PINE ACK, and a valid
profile read before enabling writes. It uses a free slot without replacing
saves. There is a manual alternative with a `.p2s` saved/loaded from the menu,
followed by a check of memory regions. That check compares the selected traffic
data, paths, player and temporary code; it is not a full comparison of the PS2
state. An ambiguous failure blocks edits without repeating the request. States
stay local and the manifest ties hashes to internal files. See
[custom-event-projects.md](custom-event-projects.md).

## What the catalogue identifies

The car used in the first creation was **COMPCAR14**, labelled **Car** by the
game's label table. The identifier names the game resource; it does not
establish a real manufacturer or model.

The 64-bit IDs encode names of up to 12 characters in **base 40**, alphabet
` -/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_`, padded with spaces on the right.
Encoding and decoding the names reproduced exactly the 40 values of the USA
executable's traffic table, so categories do not depend on guessing.

The local check compared three sources: the 40 IDs in the ELF table, the
parallel label-index table resolved through `GLOBALUS.BIN`, and the existence
of the matching resources. All 40 IDs, indices and resource paths agreed and all
40 names survived the codec round trip.

| Model | Game category | Label index | Association seen in the examined state |
| --- | --- | --- | --- |
| `COMPCAR14` | Car | 1897 | independent objects of type 1, including the created one |
| `HEVYCAR33` | Van | 1925 | independent object of type 2 |
| `HEVYCAR35` | Van | 1927 | independent object of type 2 |
| `HEVYCAR17/18` | Van | 1909/1910 | consistent native type-3 association |
| `HEVYCAR19/21` | Bus | 1911/1913 | consistent native type-5 association |
| `HEVYCAR20` | Bus | 1912 | loaded, no active independent instance; creation blocked |

To reproduce the static association: the 40-ID table starts at `0x004cdc00` and
the index table at `0x004cdd40`. `COMPCAR14` is ordinal 3 (from zero) and its ID
is `0x5b55839b95f21600`. The metadata are in `scripts/editor/catalog.py`; dumps
and local reports are not part of the repository.

Knowing the category does not prove that creating the model works. The first
profile only offered loaded models with an observed association to independent
types 1 or 2. Later versions also admit type-4 cabs with type-11 trailers, only in
native, loaded combinations (an eligible trailer shows as **Available with
truck**, never on its own), and independent types 3 and 5 when the capture holds
a consistent native association (`HEVYCAR17/18` vans, `HEVYCAR19/21` buses).
`HEVYCAR20` that is only loaded stays ineligible; eligibility is never inferred
from the category name. Special types 6 to 10 stay blocked; a real bus-creation
test is pending. Types 1/2/3/5 need two initialized, non-degenerate physics
points, an admitted path and coherence with render and collider.

## Real integration observed

In the isolated PCSX2 copy the interface connected, read the vehicles and
applied the lateral control to object 9. The catalogue and the top view were
checked in the real window, including the player reference.

A controller test created the van **HEVYCAR33** (object 13 / node 11) behind car
12 of that reference. The final check confirmed type 2, model, path 21,
initialized physics points and 85% lateral. The original hook and the 4,096
temporary bytes were left clean. The game also created natural traffic during
the interval, so the whole pool change is not attributed to the editor.

In the first interface test the object returned by the creation was no longer
in the active list at finalization; the editor refused to align or clean a
request it could not confirm any more. Pause soon after the creation notice;
letting the simulation run can invalidate the reference before the finish.

In another interface round at the start of Grand Slam, the user confirmed the
van's presence and collision. The local log shows `HEVYCAR33` prepared behind
object 9 at 10 units, then the request cancelled after a state reload restored
the original hook. Reported presence/collision and a logged finish are different
pieces of evidence.

### Finishing after the manual test

The user again confirmed that the vehicle was added and worked, while the
interface still asked to resume or pause. The window showed **Car created** with
**Game running**: the request had returned from the allocator and was waiting
for the core pause. When the right copy was paused, validation no longer
recognized the original instance. The controller now ends that case with a
warning: after validating the pause, the identity and every immutable byte of
its own request, it restores only the hook and the temporary area, cancels the
queue, and neither aligns vehicles nor records the creation in the recipe.

A local recovery validated the last `HEVYCAR35` request against its recorded
nonce and the canonical bytes of the routine and removed only the temporary
code; hashes of the whole object/node/matrix region were identical before and
after.

## Available implementation

- External Tkinter interface, opened by `Open Editor.cmd`.
- Local PINE connection validated for PCSX2 1.7.2521 and Burnout 3 USA
  `SLUS-21050` / CRC `BEBF8793`.
- Identification of the vehicles present and of the loaded models.
- The connection is kept with an invalid profile once the game identity is
  confirmed, keeping **Finish pending request** available and editing blocked.
- Top view of X/Z positions and of the researched traffic-path geometry (edges,
  centre, direction arrows, highlighted lane). **Show lanes**, **Path**,
  **Fit**, wheel and right-drag navigate. Candidates with no associated vehicle
  are marked `P?`.
- Nominal km/h target and follow values; only the target is edited, on one
  vehicle or a selection. Zero can be applied and changed later; cab and
  trailer never get separate speed writes.
- Scrollable right panel for short windows.
- Lateral repositioning of independent vehicles with initialized physics, and a
  candidate edit of the cab/trailer set protected by the native link.
- Normal mode: batches of 1 to 8 using the game's own routine in one resume/pause
  cycle; distance 8–50 units for independents and 30–50 for trucks, composite
  references and type-5 buses.
- Explicit experimental mode with a persistent warning, positive distances
  without the 50 ceiling and larger requests limited by real resources, queued in
  groups of up to eight; **Cancel queue** drops only what was not prepared yet.
- Counts of active and initialized objects, free objects/nodes and queue.
- **Pause PCSX2** and **Resume** buttons when the Windows installation behind the
  PINE connection and its compatible menu are identified.
- JSON recipes to reapply the actions on exactly the same initial state.
- **Save state…** export to `.p2s` (confirmed by the user; restoring the exported
  file is still untested).

With all ten Burnout 3 slots taken, the PINE export is refused to protect the
existing files. **System → Save state → File…** to a new destination produced a
control copy validated as a ZIP with 32 MiB of EE memory. The INI reader accepts
NUL padding only at the end of the examined UTF-8 INI without BOM.

The emulator must be paused to list and edit. Controller actions go through a
single interface worker, and a pending creation blocks new edits. Ambiguous write
failures are never repeated automatically. Pause checks and read-backs do not make
an operation a transaction: resuming the emulator during a write can interrupt it.

## Batches and cab/trailer sets

The user explicitly confirmed that the car batch and the truck with a trailer
appeared and worked. The local log includes `batch_finished` for eight `COMPCAR14`
and for a `HEVYCAR22` + `HEVYCAR27` pair, and three later `batch_not_finalized`
records after an instance or identity change; those were not aligned as if the old
reference were still valid.

The composite move is a candidate implementation: it prepares eleven protected
values to move cab/trailer without breaking the link. Creating the set does not
prove movement and collision after that move. A fourth tanker and its explosion
effects remain unvalidated. See [batches-trucks-and-pause.md](batches-trucks-and-pause.md).

A later revision restores the hook in the last stub and publishes completion only
to a fixed twelve-byte landing that the cleanup preserves, protecting the EE resume
if the pause happens while it is still leaving that code. After reopening the
editor with that builder the user confirmed **"Batch and export worked"**.

Later log reads show eight `HEVYCAR33` vans finished on path 53 and two
`HEVYCAR22` + `HEVYCAR27` pairs on each of paths 34 and 53. A later read refused
the profile because the traffic structures failed the check, leaving a pending
request; that refusal does not establish a freeze or a general failure.

## Explicit recovery of restored requests

An old pending request was traced to reloading a state saved before the cleanup:
the temporary routine came back with that state. **Finish pending request**
recognizes only canonical v1/v2 landing-based payloads with a matching local log
and proof that the batch returned control to the game. A real recovery changed only
the 4 KiB temporary area; the object, node and matrix regions stayed byte-identical.
The v2 format ties the completion to a per-generation token so a publication from
another batch cannot complete the current one.

A type-5 bus batch in v2 format was prepared; its finish was not confirmed, so bus
movement, presence and collision in a run remain unconfirmed.

## Experimental density and creation at a point

The user reported lost physics and a freeze / VIF assert in scenes with more than
fifty added cars and many involved in the same crash. `FQC = 0 on VIF FIFO READ!`
is an emulator FIFO read with a zero count; it is not a car counter and does not
prove a general limit of fifty. See [high-density-experiments.md](high-density-experiments.md).

Experimental mode lifts the editor's own limits; it does not enlarge the game's
fixed structures. Each request accepts at most 253 (the known pool) and must fit
the real object, node and collision reserves; a cab/trailer set uses two objects.
Requests above eight run as successive groups of up to eight.

**Add at point** creates one vehicle or set per action. X/Z come from the target
in the top view or the manual fields; the point is snapped to the best loaded path
with valid references. Normal mode limits the lateral offset to the admitted width
and refuses far requests; experimental mode allows a wider lateral offset, still
without terrain search or Y. It is not exact placement on any surface, loading new
scenery, or teleporting an existing body.

## Paths and nominal speed

The drawn network includes lanes with an observed reference and candidates found
through recognized descriptors and geometry; reads are budgeted and incomplete data
is skipped with a partial-view notice. Edges and centre represent traffic
following, not the visual mesh or the road collision. Arrows always show geometric
progression; a traffic direction is only corroborated when the moving reference
and its orientation pass the checks. The desired-control field and the follow
progress are separate; the km/h conversion is nominal. See
[routes-and-speed.md](routes-and-speed.md).

An offline check on a preserved reference produced a preview of 27 admitted paths
with P21 highlighted, leaving the supplied memory bytes untouched.

## Limits

The live editor uses the models and paths already loaded by the game. Changes stay
in the current session; they do not write ISO resources. **Restart**, changing
event or loading another state can recreate the traffic. A JSON preset stores a
recipe; it does not replace a save state.

Persistent edits are now possible through the disc: model order, goals and the
Crashbreaker count ([native events](native-crash-events.md)) and the traffic
waves themselves ([traffic waves](traffic-waves.md)).

Automated tests cover the protocol, profile, creation routine, interface flow and
simulated window/export control. They do not prove impact behaviour, long-term
stability or every model and level.

Later user tests, the diagnosis of blocked vehicles and the cab/trailer research
are in [traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md).
