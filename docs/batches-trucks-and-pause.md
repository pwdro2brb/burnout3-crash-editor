# Batches, trucks, pause and preservation

Status of 13/11/2026 for Burnout 3 USA `SLUS-21050` / CRC `BEBF8793` on PCSX2
1.7.2521. The tool stays external and uses the models and paths the event has
already loaded. These are live-session edits; for permanent changes on the disc
see [traffic waves](traffic-waves.md).

## Observed results and limits

The user explicitly confirmed that **both** tests worked: the car batch and the
truck with a trailer. The local log includes `batch_finished` for eight
`COMPCAR14` and for a `HEVYCAR22` + `HEVYCAR27` set. These are specific trials,
without an instrumented capture of the impact or proof of long-term stability in
every event.

There were also three later `batch_not_finalized` records: the instance or
identity no longer matched the request when finishing. Presence in the scene,
reported collision and the technical finish are separate checks. The editor
must never align another object to silently replace an expired reference.

## Technical revision of the finish

With the protected exit, the batch's last stub restores the original hook before
leaving. Global completion is published only to a **fixed twelve-byte landing**,
and the cleanup preserves exactly that landing. If the EE is paused inside that
exit, resuming still finds the return jump and its delay slot; the editor never
erases code that may still be running.

The finish needs the request probes and the global completion marker. In format
v2 that marker holds the current generation's token, tied to the nonce and
checked against the known history, so a completion from another batch does not
satisfy the current request. Format v1 with a landing is recognized only to
recover an old request that already ended. The other temporary bytes are reset
to the canonical baseline with that small exit preserved. The checks of this
sequence include pausing after publication, cleanup and resume in a test
interpreter.

After reopening the editor with the protected exit, the user confirmed: **"Batch
and export worked."** That round confirmed the new flow and the real export
manually. **The exported file has not been restored in a test yet.**

The later local log includes eight `HEVYCAR33` vans finished on path 53 and two
`HEVYCAR22` + `HEVYCAR27` pairs on each of paths 34 and 53. A later profile
refusal (traffic structures failed the check) left a creation pending; it does
not establish a freeze or a general failure.

At that point 157 distributable and 40 private tests passed. The lateral move of
sets is a candidate and needs its own test after moving. **A fourth tanker, its
collisions and explosions remain unvalidated.**

## Pausing and resuming without relying on Esc

After connecting, **Pause PCSX2** and **Resume** appear when the editor
identifies the process behind its own PINE connection and the compatible menu of
the Windows PCSX2. The result is confirmed through the PINE state. This does not
add a pause command to PINE; the button uses the emulator's native menu. A
request without confirmation is never repeated automatically.

The main frame can be hidden while the GS window is open; the target stays tied
to the connection's process. If the button is not available, use **System →
Pause** in the right emulator and check **Game paused** in the editor. The
game's own **Start** pause is not enough.

In the researched installation **Hide window when paused** was unticked
(`CloseOnEsc=disabled` in `PCSX2_ui.ini`), which keeps the game window visible
while paused. The setting was changed through the PCSX2 interface and is never
changed by the editor. Only change it in the installation used for tests.

## One cycle for the whole batch

1. Pause PCSX2 and refresh the list.
2. Select the reference, the model and an amount from **1 to 8**.
3. Enter the distance between creations: **8 to 50** units for independent types
   1/2/3, **30 to 50** for type-5 buses, trucks or references of those types.
   These are game units, not established metres.
4. Prepare the batch and click **Resume** once.
5. When asked, click **Pause PCSX2** to finish all creations. Wait for the
   confirmation before driving.

There is no manual resume/pause per vehicle. While a creation is pending the
yellow banner stays and new edits are blocked. On the **Continue** intro screen
the event must start for the game to run the traffic update.

Eight is the limit of this editor operation, not the engine's capacity. Space
behind the reference, objects, nodes and collision records are shared
resources; a batch can be refused even with free objects if there is no
compatible stretch or combination.

## Cab and trailer

The creator uses **primary type 4 + secondary type 11**, with separate model IDs.
The interface only offers native pairs observed with both resources loaded. When
you pick a cab, **Truck trailer** appears; trailers are not in the main creation
list. If the target is already a validated set, its native trailer can be
preselected; otherwise the choice is explicit.

**Sets = 3** asks for three cabs with their three trailers, not three loose
objects. Each pair uses two objects and their physics records, but one path node.
Several tankers in the original design do not establish a general limit of three;
the research did not find such a limit in the routines examined. Damage and
explosion effects need separate trials.

The composite reposition prepares **eleven protected floats**: X/Z of the cab's
points and translation, X/Z of the trailer's rear point and translation, plus the
node's lateral fraction. It keeps the link, the Y coordinates and the trailer's
null first point (type 11). It is offered only when the admitted layout is
recognized; implementing it does not prove physical stability after the move.

## Type-3 vans and type-5 buses

The profile admits consistent native associations of `HEVYCAR17/18` to type 3 and
of `HEVYCAR19/21` to type 5, with the same guards as other independent vehicles
(two initialized, non-degenerate physics points, coherent render and collider,
valid path and admitted lists/occupancy) and a valid following movement.

`HEVYCAR20` that is only loaded stays blocked without an active, consistent type-5
association; the **Bus** label in the catalogue does not authorize an instance
without that evidence. Special types 6 to 10 remain outside the editor. **A real
bus-creation test is still pending.** Type-3 vans keep the 8–50 range; a bus chosen
or used as a reference needs 30–50. A type-5 bus request in v2 format was prepared
in this phase; preparation does not demonstrate a finished creation.

## Finishing a restored request

Saving and then reloading a state from before the cleanup can bring an old
temporary routine back into memory; that was the diagnosis of the pending request
investigated in this phase. The real recovery changed only the 4 KiB temporary
area; the object, node and matrix regions stayed byte-identical and no vehicle was
repositioned.

With the game paused, **Finish pending request** compares the request with the
local log and its canonical build. It only cleans v1/v2 landing-based requests that
already returned control to the game, with the original hook, completed probes and
a matching completion marker. Unknown code, a missing log or incomplete execution
stay blocked. The cleanup keeps the existing vehicles; the old request's alignment
and recipe are not recovered. The recovery needs an explicit click: the automatic
poll never repeats a creation nor cleans a restored request.

## Oncoming traffic

The controller does not block by direction relative to the player. The reference
needs a valid path, an admitted link and initialized physics, with coherent
orientation, following speed and progression. In the reads that started this
investigation, oncoming cars still had zeroed physics points and zero following
speed, which explains those blocks without classifying all oncoming traffic as
incompatible.

## JSON recipe and `.p2s` state

| File | What it keeps | How to reuse it |
| --- | --- | --- |
| JSON from **Save configuration…** | Recipe of actions and initial reference | Reload exactly the initial state, connect and open the recipe |
| `.p2s` from **Save state…** | Capture of the edited emulator session | Load the matching game and restore the file in PCSX2 |

Exporting a state needs a confirmed pause and nothing pending. The suggested
destination is `outputs/events/` with a unique date-time name; afterwards the
footer shows **File:** and the returned path. The implementation refuses to
replace existing files, looks for a free slot of the portable installation and
verifies the file before copying it. The user confirmed a real export; restoring
that file still needs manual validation.

If all ten slots are taken the button refuses before replacing any state. Use
**System → Save state → File…** in PCSX2 with a **new** `.p2s` destination. A control
copy saved that way was validated as a ZIP with 32 MiB of EE memory.

To restore in PCSX2 wx 1.7.2521: with the matching game open, use **System → Load
state → File…**, select the `.p2s` and click **Open**. Pause and connect the editor
as a new session before editing. The file menu item and the `.p2s` dialog are in
[PCSX2 wx 1.7.2521's code](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/gui/MainMenuClicks.cpp#L792).

None of these formats writes the layout to ISO resources. **Restart**, changing
event or loading another state can recreate the traffic.

The [first-use guide](editor-quickstart.md) covers the basic sequence, and
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md) records the
capacity, pairs and tanker research.
