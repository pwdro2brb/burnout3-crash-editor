# Current-event editor — first use

This external window edits the event that is loaded in PCSX2. It can identify
the vehicles present, move a vehicle across the width of its lane, add batches
behind a reference vehicle and create a vehicle at an X/Z point snapped to the
loaded paths. It draws the researched traffic-lane geometry and can change the
nominal speed target of supported records. Normal mode works in groups of 1 to
8; experimental mode accepts larger requests, limited by the game's capacity.
Trucks with trailers only use native cab/trailer pairs already loaded by the game.

These are **session** edits: they live in RAM and disappear when the event
restarts. To change an event permanently on the disc, use
[native event editing](native-crash-events.md) and [traffic waves](traffic-waves.md).

The researched profile is Burnout 3 USA, `SLUS_210.50`, on PCSX2 1.7.2521.
Other executables and emulator versions need their own validation. Use a test
copy of the emulator and keep a reference state of the event before editing.

## Open and connect

1. Install Python 3.10 or later with Tcl/Tk. The editor installs nothing.
2. In the test PCSX2, enable PINE and load the game and the event to edit. In
   the researched version the setting is in `inis/PCSX2_vm.ini`, section
   `[EmuCore]`: `EnablePINE=enabled`. Close the emulator before editing that
   file, keep a copy and restart it afterwards. Only change the test
   installation. The default port is 28011 and the connection is local only.
3. Open **Open Editor.cmd** in the project folder and click **Connect / new session**.
4. When shown, use **Pause PCSX2** and **Resume** in the editor. They identify
   the installation behind the PINE connection and confirm the pause through
   the emulator. Otherwise use **System → Pause** in the right PCSX2 window.
   **Start** in the game's own pause menu does not replace a core pause.
5. Select a vehicle in **Vehicles present** to see its model and position.
   **Refresh list** re-reads the current session. After loading another state
   or event, click **Connect / new session** before starting a recipe.

When you select a blocked vehicle, the details say whether it is a linked
component, a type that is not enabled yet, or whether the game has not
initialized its physics. Being listed does not mean being ready to edit.

On short windows, use the right panel's scrollbar to reach the speed, model and
trailer controls. The mouse wheel over the map is reserved for zoom; drag with
the right button to pan.

You can also start the editor from a terminal in the project folder:

```powershell
python -B scripts/editor/run_editor.py
```

Use `--port 28112` for a different local port. In the researched wx PCSX2, a
port set in the PINE dialog does not survive a restart.

To keep the game window visible while paused, untick **Hide window when
paused** in the test PCSX2 (`CloseOnEsc=disabled` in `PCSX2_ui.ini` in the
researched install). The editor never changes that setting. See
[pause and preservation](batches-trucks-and-pause.md).

## Why only vehicles near the player can be edited

The game builds the full physics body of a traffic vehicle only when the vehicle
comes within about **250 game units** of the player car (the per-object update
`FUN_00186850` marks vehicles closer than 250 units and clears the mark beyond
275). Until then the vehicle only follows its path and its two physics points are
still zero. In 38 savestates, all 538 vehicles inside that radius had their physics
ready, while 223 of the 251 vehicles outside it did not.

The live editor needs those physics points to move a vehicle or to add vehicles
behind it without breaking the game's physics, so it blocks vehicles that have not
been near the player yet; the details say so. The **Top view** draws that radius as
a dashed circle around the player. To change vehicles that are still far away,
drive closer and pause again, or edit the event itself in **Traffic waves** (button
in the top-right corner), which has no distance limit.

## Create an event project

In the **Project** tab, name the event and use **Create project…** with PCSX2
paused before the crash. The original reference is kept. Edit the vehicles and
finish the batches; **Test scene** saves the version and resumes the game. To
repeat, pause and use **Back to start**, which restores the last saved scene.
**Restore original base** brings back the reference without replacing that
scene. To reopen the work, select `event.b3event.json` in **Open project…**.

The automatic flow needs a free slot and never replaces existing saves. If all
slots are taken, **Manage slots…** offers **Archive and free selected**, after
showing the paths and keeping verified copies in the backup folder. The
**Alternative without a free slot** section lets you save/load a `.p2s` through
the PCSX2 menu and import/check that scene in the editor; the chosen file must
match the verified paused memory. See the [project guide](custom-event-projects.md).
Restoring and repeating projects in game still needs confirmation.

To mix vehicles in a batch, choose **Alternate models** in the creation panel
and pick two or more loaded models; the sequence repeats up to the requested
amount. **Alternate variants (0–7)** is an experimental look option; there is
no colour table per model yet. The reference may be standing still as long as
its path and physics are valid. See [slots and mixed batches](slots-and-mixed-traffic.md).

If the game identity is confirmed but the traffic profile is refused, the
editor stays connected with editing disabled. With the game paused, **Finish
pending request** remains available without selecting a vehicle. A successful
cleanup stays reported even if the next read still fails; **Refresh list**
re-enables editing only after a valid read.

A new connection clears the recipe of actions held by the editor. Save the
configuration before starting another session if you want to keep it.

The editor never starts the emulator or drives the car. If the connection
fails, check that the game is loaded and that PINE is enabled in the test
installation. Do not run two emulators on the same PINE port.

## Identify and choose a model

The car used in the first test was **COMPCAR14**, labelled **Car** by the
game's own label table. The catalogue also tells apart Van, Bus, Taxi and
trailers; this does not identify a real manufacturer or car model.

The creation list offers **Same model as selected** and the loaded models the
profile admits: independent types 1/2/3/5 and native type-4 cabs with type-11
trailers. When you pick a cab, **Truck trailer** shows only observed and loaded
combinations. A trailer is never offered on its own. Type-3 vans
`HEVYCAR17/18` and type-5 buses `HEVYCAR19/21` are admitted when they have a
consistent native association and ready physics. `HEVYCAR20` that is only
loaded, without that association, stays blocked. Special types 6 to 10 are not
enabled. A real bus-creation test is still pending.

For independent vehicles the profile requires two initialized, non-degenerate
physics points, consistency with the rendered position and the collider, and a
valid path and occupancy. A distant vehicle with zeroed points stays blocked.

The **Loaded catalogue** tab lists every model found, its category and its
creation status: **Available**, **Available with truck** or **Creation not
validated**, so you can identify a loaded bus even when it cannot be created.

## View the paths

1. Pause PCSX2 and use **Refresh list**. Select a vehicle and open **Top view**.
2. Turn on **Show lanes** to see edges, centre and `P0`, `P1`… labels. The
   selected vehicle's lane is highlighted; **Path** frames it and **Fit** fits
   everything. Use the wheel to zoom and drag with the right button to pan.
3. Arrows show the **path direction**. A dashed arrow does not prove the current
   traffic direction. Candidate paths with no associated vehicle are labelled
   `P?`, drawn lighter, and their current use is not confirmed.
4. Click a vehicle dot to select it. The player appears in red with its
   heading when available. **Mark position** keeps X/Z meaning while zooming
   or panning.

The lanes show the traffic-following geometry found in memory; they are not
the road mesh and do not guarantee a drivable surface. Roads at different
heights can overlap in the X/Z view. A visible candidate path does not enable
creation at a point: that still needs a valid moving reference. If a read
exceeds its budget or skips invalid data, a notice says the view is partial.
The view matches the last paused read; it does not follow the cars live.

## Check and change speed

1. Pause PCSX2, refresh the list and select one or more vehicles. Use **Ctrl**
   to pick several, **Shift** for a range, or **Select speed-eligible**. The
   **Nominal km/h A/S** column shows target and follow values; the details
   show the full names. Records without a recognized node show unavailable.
2. When the profile allows it, fill **Nominal target (km/h)** and click **Apply
   speed** or **Apply to the N selected**. The same target applies to all; one
   blocked record blocks the whole action instead of being skipped. Zero is
   accepted and a positive target can be applied later. In normal mode the
   nominal maximum is 386.24256 km/h, the researched control ceiling; the car
   may not be able to reach it.
3. For a truck with a trailer, select the cab. The editor never writes speed to
   a trailer on its own. Wait for the confirmation and use **Resume** to watch.

The focused row remains the reference for position and creation actions;
selecting several does not move or add several targets with those actions.

The target is the request to the traffic controller; the follow value is
recomputed by the game. A queue, an obstacle or an overlapping vehicle can
reduce progress while the target stays high. The km/h scale is **nominal**,
derived from the researched fields, not a calibrated physical measurement.
The read happens with the emulator paused, not from a live speedometer.

JSON recipes also record speed-target changes for the same initial state, and
experimental actions still require experimental mode when loading. See
[paths and speed](routes-and-speed.md) for the evidence and limits.

## Move a vehicle

1. Click **Pause PCSX2** (or pause from the emulator menu) and refresh the list.
2. Select a vehicle that is available for editing.
3. Adjust **Position across the lane width** and click **Apply position**.
4. Use **Resume** to continue and watch.

The 0%–100% control spans the path width; it is not necessarily a traffic lane
or a collision edge. The position along the path is kept. Start with small
changes; some distant objects have no updated physics points yet and cannot be
edited this way.

For an enabled truck, select the cab: the candidate edit moves cab and trailer
together, keeping the link. Movement and collision after that combined move
still need their own validation. Oncoming traffic can also be a reference when
its physics and path are initialized; the direction relative to the player is
not what blocks it.

## Add a batch or a truck with a trailer

These ranges are for normal mode, with the experimental toggle off.

1. With the emulator paused, select the reference vehicle.
2. Choose the model, **Amount** from 1 to 8 and **Distance behind**. For
   independent types 1/2/3 the default is 10 and the range is 8 to 50 game units.
3. For a cab, also choose a compatible trailer; the amount then counts complete
   sets. The target's native trailer is preselected only when its link was
   validated. For type-5 buses, trucks, or references of those types the minimum
   distance is 30; the interface raises smaller values to 30.
4. Click **Add vehicles behind** or **Add sets behind**. Use **Resume** once to
   run the batch. Do not click the creation button again.
5. When asked, click **Pause PCSX2**. The editor follows the operation and
   finishes the whole batch in that pause. Pause soon after the notice, before
   the new vehicle leaves the stretch or the event recreates its traffic. On the
   **Continue** intro screen you must start the event for the traffic routine to run.
6. Wait for the confirmation, then **Resume** to play and test presence,
   movement and collision. Distances are game units with no established metre
   equivalence.

Also check **Game paused** in the editor and `<PAUSED>` in the game window
title. With two installations open, pausing the other PCSX2 window does not
pause the session the editor is connected to.

The yellow **CREATION PENDING** bar stays until the finish. The "vehicle
created" message still needs the second pause before driving. If the vehicle
already changed or left the scene, the editor may end with **Warning: …
Temporary code removed. Alignment not confirmed.** It then only cleans its own
temporary routine, releases the interface and leaves that creation out of the
JSON recipe. It never moves another vehicle to fix an old reference.

If all creations returned but physics still does not allow confirming the
alignment, the wait is limited to five seconds from the first paused check of
that step. The editor then removes only the recognized temporary code, keeps
the vehicles the game created and cancels the rest of the queue; the batch is
left out of the recipe. **Finish pending request** ends that wait immediately
once the routine has returned control to the game. Active, unknown or unproven
code stays blocked.

While a creation is in progress, do not load another state, change event or
close the editor. If an operation fails, follow the message. If a clean state is
requested, reload the previous reference, pause the emulator and click
**Connect / new session**. The previous creation is never repeated automatically;
repeating an action without knowing its result may add another instance.

## Experimental mode and larger requests

1. Keep a control state before testing. Turn on **Experimental mode: larger
   amounts and distances** and read the persistent warning about freezes and
   lost physics.
2. Enter a positive, finite distance. The 50-unit ceiling and the 8/30 minimums
   stop being editor limits in this mode; the end of the path is still respected.
   Small distances can overlap vehicles.
3. The amount accepts up to 253, but the request must fit the free objects,
   nodes and collision records. That is not 253 guaranteed cars; a cab/trailer
   set uses two objects.
4. Larger requests run as a queue in groups of up to eight. Do **Resume →
   Pause PCSX2** and wait for the confirmation of each group. The footer shows
   the next group and the remaining queue. Do not click creation again.
5. **Cancel queue** drops the remaining operations. It does not remove vehicles
   already created nor undo the group already prepared; finish that group as
   the message says before editing again.

The warning stays visible while the mode is on. The editor shows counts of
active objects, ready physics, free objects/nodes and queue, and can warn when
objects of a reference lose initialized physics. These numbers do not
establish a safe crash capacity. The VIF assert reported after dense scenes is
not fixed by this mode; see [high-density experiments](high-density-experiments.md).
That report does not prove a universal fifty-car limit.

## Create at a marked point

1. Pause PCSX2, refresh the list and select a reference with a valid path and
   physics. Choose the loaded model and, for a truck, a compatible trailer.
2. Open **Top view**, click **Mark position** and then the map; the target
   appears with X/Z. You can also type X and Z.
3. Click **Add at point**. This prepares one vehicle or set with the model
   chosen in the side panel; the batch amount does not multiply it.
4. Do **Resume → Pause PCSX2**, wait for the finish, then resume to watch
   presence, movement and collision.

The X/Z point is projected onto the best path among those with ready
references in the session. In normal mode the position is snapped to the
admitted lane width and far points are refused. Experimental mode allows a
lateral position outside that width, with a higher risk of invalid physics; it
still needs a recognized path. There is no Y height choice or terrain search,
so the result can differ from the click. This never teleports an existing
vehicle. When an off-lane object still has admitted physics and layout,
experimental mode may enable **Apply position** to try to bring it back into
the 0%–100% width; it still cannot be a reference for new creations.

## Finish an old pending request

1. Pause PCSX2 and check **Game paused**.
2. Click **Finish pending request**, even if the list is blocked or empty.
3. Read the result in the footer. If the request is recognized and has already
   returned control to the game, the editor cleans only the admitted temporary area.
4. Click **Refresh list**. If the profile stays invalid, restore a clean
   reference in PCSX2 before editing.

A state saved before the cleanup can bring back the old temporary routine. To
recover an old request not followed by the current session, the editor needs
the matching local log and the canonical payload of a recognized format with
proof of completion. Unknown or unproven code stays blocked. The action does
not align vehicles or recover that request's recipe, and the automatic poll
never repeats the creation command or performs this cleanup on its own.

## Keep the configuration

**Save configuration…** writes a local JSON with the data the editor used.
**Open configuration…** applies it to the current event. It requires **exactly
the same initial state** (before the edits) that was used to prepare the
recipe: reload that reference, pause, start a new session and open the JSON.
Recipes that create vehicles need the same resume/pause steps as above.

If the recipe contains experimental actions, turn the toggle on and read the
warning before opening it; a JSON cannot enable the risk by itself. The recipe
still needs the same loaded models, valid references and initial state.

Vehicles that appeared after the initial reference, without a confirmed
creation in the recipe, can be edited when the profile admits them. If an
action uses such a reference, the editor refuses to save the JSON rather than
promise a replay it cannot rebuild. Use a `.p2s` to keep the session, or
**Connect / new session** to adopt the current scene as a new reference.

**Save state…** exports a `.p2s` of the edited session, with the emulator paused
and nothing pending. Choose a new name. The button only appears when the
portable installation can be identified. It uses a free slot, verifies the
written file and refuses to replace existing states or destinations. The dialog
suggests `outputs/events/` with a date-time name; the footer shows **File:** with
the exported path. The user confirmed a real export; restoring that exported
file has not been tested yet. When all ten slots are taken the button refuses
to export. Then save from PCSX2 with **System → Save state → File…** to a
**new** `.p2s` (for example inside `outputs/events/`). A control copy saved
that way passed the ZIP and EE-memory checks.

To reopen it:

1. Keep the matching game open in PCSX2.
2. In the main PCSX2 window choose **System → Load state → File…**.
3. Select the `.p2s` and click **Open**. This restores the saved moment.
4. Pause the emulator and connect the editor as a new session before editing.

The editor never loads that file automatically. If it brings back an old
pending request, follow **Finish an old pending request** above.

The JSON contains no game resources and does not replace a save state. Session
edits apply to the current RAM only: **Restart**, changing event or loading
another state can recreate the traffic and drop them. The `.p2s` keeps a session
to restore; it does not write a new event to the ISO.

The protocol and the required pause were checked against the
[official PCSX2 v1.7.2521 PINE code](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/PINE.cpp).
Success messages in the interface do not replace watching the game.

After the earlier batch and export confirmation, the user also reported that the
paths-and-speed revision worked, and later that the physics-wait fix and the
multi-selection speed change worked. Restoring the exported `.p2s` still needs
confirmation. Profile blocks can still stop an operation; these reports do not
prove stability in every scenario.

Batches, trucks, pause and files: [batches-trucks-and-pause.md](batches-trucks-and-pause.md).
Restrictions, the protection error and the truck investigation:
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md).
