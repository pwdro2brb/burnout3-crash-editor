# Crash event projects — version 1

The **Project** tab organizes a custom event on an existing map: name, original
reference and an edited scene with vehicles, positions and speeds. A project
uses local PCSX2 states to repeat the same scene. The accepted profile is still
Burnout 3 USA, `SLUS-21050 / BEBF8793`, on a portable PCSX2 `1.7.2521` with PINE.

Projects preserve **live sessions**. To change the event itself on the disc
(what the game loads from the menu), use [native events](native-crash-events.md)
and [traffic waves](traffic-waves.md).

The user confirmed that batches and group speed worked in the previous revision.
The project and restore flow of this version was verified offline; restoring and
repeating it in game still needs confirmation.

## Create and test

1. Load the event, connect the editor and use **Pause PCSX2**. Choose a moment
   before the crash so the test can be repeated from it. Finish any pending creation.
2. In the **Project** tab, enter a name of up to 100 characters and click
   **Create project…**. Choose the folder that will receive a new project
   subfolder. The paused scene is copied as the original reference; existing
   files are never replaced.
3. Arrange the vehicles and their speeds with the editor controls and finish the
   batches. **Save scene to project** stores that version and keeps the emulator paused.
4. **Test scene** saves a new version and resumes the game. Drive and test the crash.
5. To repeat, pause again and click **Back to start**. Wait for the restore
   confirmation before editing or resuming.

**Back to start** restores the last **saved edited scene**, including where the
player was when it was saved. It does not use the game's normal restart and does
not go back to the unedited reference by itself. If PCSX2 does not resume after
**Test scene**, the message tells the saved scene apart from the resume failure;
check the pause before going on.

## Reopen and recover the reference

With the matching game loaded and the emulator paused, use **Open project…** and
select `event.b3event.json`. The editor checks the files and restores the last
saved scene. A new editing session starts from it; the previous session's JSON
recipe is not rebuilt.

**Restore original base** loads the reference captured when the project was
created. The saved edited scene is kept: **Back to start** can still bring it back
until a new scene is saved. Restores stay paused when they finish.

## When there is no free slot

Automatic capture and restore use a free temporary slot; the editor refuses to
replace any of the ten existing slots. The **Alternative without a free slot**
area of the Project tab uses the PCSX2 menu instead:

1. To create a reference or keep a scene, keep the moment paused and use **System
   → Save state → File…** in PCSX2 with a new `.p2s` file.
2. Use **Create from .p2s…** for a new project, or **Save scene from .p2s…** to
   update the open project. The file must match the paused scene; the editor checks
   it before copying and keeps the original.
3. To repeat manually, use **System → Load state → File…** and pick the project's
   scene file. Then pause PCSX2 and use **Check loaded scene…**, selecting that
   project's manifest.
4. To recover the reference, load `base.p2s` the same way and use **Check loaded base…**.

The **Check** buttons verify what is already loaded; they never send a load
command. To test a scene saved this way, use **Resume**. **Test scene** uses the
automatic capture and still needs a free slot.

## Files and preservation

A project folder contains:

```text
event-…/
  event.b3event.json
  base.p2s
  scene-<identifier>.p2s
```

Right after creation, the saved scene points to `base.p2s` without duplicating it.
Each later save creates a new `scene-…p2s` file and only then updates the manifest.
The base and older scenes are never overwritten. The interface uses the current
version named in the manifest; there is no browser for older versions yet.

The manifest stores the name, profile, summary and relative references to the
states, with integrity hashes. External files, references that traverse folders,
links and redirects are rejected. If the manifest changes in another session, open
it again before saving. A failed copy or publish keeps existing files; an
unreferenced capture or version may stay on disk for inspection.

Projects are local and can live in `outputs/events/`. `.p2s` states contain game
data and are never committed to the repository. Keep the whole folder to reopen a
project. A project does not need every vehicle of the scene to have a creation in
the JSON recipe; it restores the saved state.

## How a restore is checked

A valid ZIP and compatible code are recognized before the automatic load request.
PCSX2 acknowledging the request is not treated as completion: the editor writes a
random 16-byte marker into its idle data area and requires the restore to remove
it, even if the target scene was already loaded. It then checks pause, identity,
clean temporary code and the scene's memory regions in two reads, and the
controller validates the profile again before enabling edits. The checked data
include traffic, path descriptors and the player transform when its pointer is
valid. This is not a full comparison of the PS2 state. The file's hash is tied to
the project reference before copying or loading, to refuse a swap between the
check and its use.

If a load is ambiguous there is no automatic retry and no attempt to revert
memory: new edits stay blocked until a clean reference is recovered. The check
does not prove physics, collision or render stability in dense scenes.

## Limits of this version

Creating vehicles still depends on loaded models, admitted paths and valid
references. A candidate path drawn on the map does not become available for
creation by itself. The game's normal **Restart** can rebuild the original
traffic; to repeat the saved work, use the project.

A project keeps scenes outside the game. It does not add options to the Crash
menu, load missing models or create map geometry. Using new locations needs
research on paths, collision, camera and the area's rules.
