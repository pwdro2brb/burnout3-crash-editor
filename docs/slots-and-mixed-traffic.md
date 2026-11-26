# Slots, standing references and alternating batches

This revision adds slot archiving and creation with alternating models. The new
flows still need confirmation in a running PCSX2; the automated trials use
temporary files and copied memory.

## Free a slot while keeping the save

1. Connect the editor to PCSX2 and pause the emulator. Finish any pending creation
   before managing state files.
2. In the **Project** tab, click **Manage slots…**. The list shows the ten slot
   indices used by the editor, the files found and their size.
3. Select an occupied slot and use **Archive and free selected**. Check the paths
   shown before confirming.
4. Wait for the confirmation. The copy goes to `editor-slot-backups/slotNN-…` inside
   the recognized portable installation; the full path appears in the reply.

Archiving copies and verifies every recognized file of that slot before freeing
its original names. Versions in the main and game-specific folders, when both
exist, are kept apart as `flat/` and `nested/` inside the backup, and `backup.json`
lists the paths and hashes. Other slots and the emulator configuration are kept.

This does not permanently delete the save: the archived `.p2s` can be picked with
**System → Load state → File…** in PCSX2. Keep the backup folder. A damaged or
empty state can be archived to free the slot, but keeping its bytes does not make
it loadable.

Links, redirects and files above the admitted size are blocked. If the emulator is
resumed or the files change during the process, the operation stops and keeps the
copies. If part of the slot was already archived, the message says so; do not
repeat automatically. Freeing files is not atomic with external emulator actions.

## Using standing and oncoming vehicles

Driving against the player is not a reason for the profile to block a vehicle; the
reference uses its own path and orientation. A traffic controller with zero
progress can also be a reference when its path, parameters and physics are valid.

Select the vehicle and read the details when an action is disabled. A car stopped
in traffic can have a valid path; a parked scenery object may have no traffic node
or path. Linked trailers are still edited through the cab, and physical types not
recognized yet stay blocked. Nothing is enabled indiscriminately, and there is no
free movement outside the researched paths.

## Create a batch with alternating models

1. Pause and select an enabled reference.
2. In **Add vehicles behind**, choose **Alternate models** and **Choose
   alternating models…**.
3. Pick at least two models with **Ctrl/Shift** and confirm with **Use selection**.
   The order shown repeats in the batch, e.g. car → van → car → van.
4. Set distance and amount and use **Add vehicles behind**. Resume and pause to
   finish each group, as with the earlier batches.

Only independent models that are loaded and admitted by the current read can be
selected. Trucks with trailers stay in **Single model**, with a compatible native
trailer. Buses may need the large-vehicle spacing. The batch is validated before
the first write; an invalid choice is never silently skipped. Normal mode is still
limited to eight per group; alternating models do not raise the game's safe
collision limit.

## Experimental visual variation

**Original (0)** keeps the native argument used before. **Alternate variants
(0–7)** passes different values to the native creator across the batch. The
effect on colour depends on the model and still needs confirmation: there is no
proven mapping from index to colour, no guarantee of eight different colours, and
the option only affects new vehicles of the batch.

The same 0–7 index is the `colour` field of [traffic waves](traffic-waves.md):
original events use values 0–7 on many vehicles.

Action recipes record the model and variant of each confirmed creation. Projects
keep the scene through their local `.p2s` states. No save, backup or game resource
is included in the repository.
