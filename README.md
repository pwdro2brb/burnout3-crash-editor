# Burnout 3 Crash Editor

Research tools and an editor for the **Crash Mode** events of *Burnout 3: Takedown*
(PlayStation 2, USA release `SLUS-21050`). The goal is to let anyone build new Crash
events: choose the traffic, where and when every vehicle enters, the medal goals and
the Crashbreaker, and test the result on PCSX2.

> **Status: experimental.** Everything here was reverse engineered and is tested on one
> game version and one emulator version. Keep backups of your saves and never edit your
> only copy of the game.

**No game files are included.** You need your own copy of the game. The repository
contains only original code and documentation: no ISO, ELF, BIOS, game resources,
saves, dumps, decompiled code or analysis exports. This project is not affiliated
with or endorsed by Electronic Arts or Criterion Games.

## What you can do

| Tool | What it does | Needs |
| --- | --- | --- |
| **Events on the disc** (button **Waves & models (disc)…**) | Browse the 100 Crash events and edit them: the **traffic waves** (when and where every vehicle appears, with a timeline and "add several"), **replace a traffic model with one from another event** (a tuk-tuk in Grand Slam, a minibus…), the medal goals and the Crashbreaker wreck count. Then build a new ISO. | The extracted game folder (and the ISO to build a copy). The emulator can be closed. |
| **`scripts/waves.py`**, **`scripts/models.py`** | The same wave editing (shareable `.waves.json` files) and model replacement from the command line. | The extracted game folder. |
| **Current-event editor** | Live edits of the event running in PCSX2: list vehicles, move them across the lane, add batches of cars or trucks **behind one or many vehicles at once** (including far and oncoming traffic that has no physics yet), change their speed, save and repeat scenes. | PCSX2 1.7.2521 with PINE enabled. |

### How Crash traffic works

Crash traffic is scripted, not random. Each event has **waves**: wave 1 places most of
the vehicles on the road as soon as the event starts; later waves load at fixed times
(1 to 21 seconds in the original events). Inside a wave, each lane lists vehicles that
are either **on the road** at a distance along the road when the wave loads, or
**drive in later**, one by one at the lane's entry point at a given time. That is why
many levels start with a big group of cars and get a smaller batch a few seconds later.

Each event loads at most 12 traffic models, listed in six groups (cars, big cars and
vans, buses, type-3 vans, truck cabs, trailers). The model files are global
(`PVEH/COMP`, `PVEH/HEVY`), so a model used by any event can replace one of the same
group in another event; see [model replacement](docs/model-replacement.md).

Read [docs/traffic-waves.md](docs/traffic-waves.md) for the full explanation, the data
format and the evidence behind it.

## Requirements

- **Python 3.10 or later**, standard library only. The graphical editor needs Tcl/Tk,
  which the Windows Python installer includes by default.
- **Burnout 3: Takedown USA** (`SLUS-21050`, CRC `BEBF8793`), extracted to a folder with
  `DATA` and `TRACKS` (any ISO9660 extractor works). Keep the matching ISO to build
  edited copies.
- For live editing: **PCSX2 1.7.2521** with PINE enabled (`EnablePINE=enabled` in the
  `[EmuCore]` section of `inis/PCSX2_vm.ini`). Use a separate test installation.
- Optional, for research only: Ghidra with the Emotion Engine Reloaded extension
  (`r5900:LE:32:default`). The research used Ghidra 12.2, JDK 25 and extension v2.1.39.

Other game regions, versions or emulator builds need their own validation.

## Quick start

### Open the editor

Double-click **Open Editor.cmd**, or run from the project folder:

```powershell
python -B scripts/editor/run_editor.py
```

### Make a new version of a Crash event

1. In the editor, click **Waves & models (disc)…** (top right) and choose your extracted
   game folder (it opens automatically if the folder sits next to this one with its
   default name, `Burnout 3 - Takedown (USA)`).
2. Pick an event, for example **Grand Slam**.
3. In **Traffic waves**, the timeline shows when each wave loads. Select a wave, a lane or
   a vehicle in the list and the panel on the right shows only what can be changed there:
   a wave's start time, a lane's entry point and **Add several** (a queue on the road or a
   stream of cars that drive in later), or one vehicle's model, colour and position/time.
   In **Models and goals**, replace a model with one from another event, or change the
   goals and the Crashbreaker count.
4. Click **Build ISO copy…**, choose the original ISO and a new file name.
5. Boot the new ISO in PCSX2 and enter the event from the game menu. (A savestate would
   bring back the old event data.)

### Same thing from the command line

```powershell
python scripts/waves.py --game-root "C:\Games\Burnout 3 - Takedown (USA)" list
python scripts/waves.py --game-root "C:\Games\Burnout 3 - Takedown (USA)" show "Grand Slam"
python scripts/waves.py --game-root "C:\Games\Burnout 3 - Takedown (USA)" export "Grand Slam" grand-slam.waves.json
python scripts/waves.py --game-root "C:\Games\Burnout 3 - Takedown (USA)" build grand-slam.waves.json --iso "C:\Games\Burnout 3.iso" --out "Grand Slam - edited.iso"
```

Edit the JSON between `export` and `build`. Several files (several events) can be
built into one ISO. The original files and ISO are never modified, and every output is
read back and verified.

```powershell
python scripts/models.py --game-root "C:\Games\Burnout 3 - Takedown (USA)" show "Grand Slam"
python scripts/models.py --game-root "C:\Games\Burnout 3 - Takedown (USA)" build "Grand Slam" --swap COMPCAR12=COMPCAR18 --iso "C:\Games\Burnout 3.iso" --out "Grand Slam - tuk-tuk.iso"
```

### Live editing in PCSX2

See the [first-use guide](docs/editor-quickstart.md). In short: load the event in the
PCSX2 test installation, click **Connect**, pause with **Pause PCSX2**, edit, then
**Resume**. Select several vehicles (or **Last car of each lane**) to add the same set
behind each of them. Far vehicles, such as oncoming traffic at the start, show as
*Far (no physics)*: you can add behind them, and the game gives the new vehicles physics
when you get close. Live edits are lost when the event restarts; save a scene in the
**Project** tab to repeat it.

## Documentation

| Topic | Document |
| --- | --- |
| How Crash traffic is scheduled and how to edit it | [traffic-waves.md](docs/traffic-waves.md) |
| Editing events on the disc (goals, Crashbreaker, models, ISO export) | [native-crash-events.md](docs/native-crash-events.md) |
| Using models from other events (and why not garage cars) | [model-replacement.md](docs/model-replacement.md) |
| Live editor: first use | [editor-quickstart.md](docs/editor-quickstart.md) |
| Live editor: status, catalogue and evidence | [editor-status.md](docs/editor-status.md) |
| Scene projects and slots | [custom-event-projects.md](docs/custom-event-projects.md), [slots-and-mixed-traffic.md](docs/slots-and-mixed-traffic.md) |
| Batches, trucks, pause and saving | [batches-trucks-and-pause.md](docs/batches-trucks-and-pause.md) |
| Paths and speed | [routes-and-speed.md](docs/routes-and-speed.md) |
| Capacity, trucks and late traffic | [traffic-capacity-and-trucks.md](docs/traffic-capacity-and-trucks.md) |
| Dense scenes and the VIF assert | [high-density-experiments.md](docs/high-density-experiments.md) |
| Preview fly-by and results cameras | [event-cameras.md](docs/event-cameras.md) |
| Research history and early findings | [project-history.md](docs/project-history.md), [findings.md](docs/findings.md) |
| Milestones | [repositioning](docs/repositioning-milestone.md), [moving traffic](docs/moving-traffic-reference.md), [vehicle creation](docs/vehicle-creation-milestone.md) |
| What comes next | [roadmap.md](docs/roadmap.md) |

## Repository layout

```text
Open Editor.cmd            Windows launcher for the editor
config.example.json        Template for local paths (copy to config.local.json)
scripts/
  waves.py                 Command-line traffic-wave tool
  models.py                Command-line model replacement tool
  common.py                Shared path/config handling for the research scripts
  editor/                  Tkinter editor, PINE client, live-session profile and tests
  resources/               Readers/writers for the game files (events, paths, waves, ISO)
  runtime/                 Save-state readers and the repositioning prototype
  ghidra/                  Ghidra headless launcher and export scripts
docs/                      Guides and research notes
```

## Local paths for the research scripts

Copy `config.example.json` to `config.local.json` (ignored by Git) and fill in your own
paths, or use arguments or environment variables:

| Variable | Use |
| --- | --- |
| `B3_GAME_ROOT` | Extracted folder that contains `SLUS_210.50`, `DATA` and `TRACKS` |
| `B3_OUTPUT_ROOT` | Separate folder for reports, projects and logs |
| `B3_GHIDRA_DIR` | Root of a local Ghidra installation |
| `B3_JAVA_HOME` | Root of the JDK used by Ghidra |

Priority: explicit argument, then environment variable, then the JSON config. Without an
output path, `outputs/` (ignored by Git) is used. Game and output folders must not
overlap, and the resource scripts refuse to overwrite existing reports.

```powershell
python scripts/resources/index_binary.py --config config.local.json
python scripts/resources/survey_resources.py --config config.local.json
python scripts/resources/parse_stagehed.py --config config.local.json
./scripts/ghidra/Invoke-Ghidra.ps1 -Config config.local.json -Mode Import
```

The Ghidra import creates a separate analysis project and never modifies the ELF;
`-Mode Process` queries an existing project read-only. Exports must stay out of Git.

To inspect a save state you supplied:

```powershell
python scripts/runtime/inspect_savestate.py <state.p2s> --output-root <output folder> --output traffic.json
```

It reads the RAM in memory, never extracts or rewrites the save, and writes reports
that contain local paths and RAM samples: keep them private.

## Running the tests

```powershell
python -B -m unittest discover -s scripts/editor -p "test_*.py"
```

The tests use generated data only (no game files) and should all pass; a few subcases
are skipped when Windows does not allow creating symbolic links.

## Contributing

Contributions are welcome: research notes, support for other regions, editor features
and tests. Read [CONTRIBUTING.md](CONTRIBUTING.md) first. The most important rule:
**never commit game data** (ISO, ELF, BIOS, `.BGD`/`.BIN` resources, save states, dumps
or decompiled code). The `.gitignore` uses an allowlist to help with that.

## License

The code and documentation are released under the [MIT License](LICENSE).
*Burnout* and *Burnout 3: Takedown* are trademarks of their respective owners; this is
an unofficial fan research project.
