# Using traffic models from other events

Each Crash event loads its own small set of traffic models, and the live editor can
only create vehicles from that set. This page explains where the models come from,
how to use a model that another event uses, and why the garage (player) cars are a
different problem.

## What decides which models an event has

- **The event's model groups.** Every event block lists its traffic models in six
  groups (24-byte records: 8-byte model ID + four fixed fields). In savestates the
  game's runtime model table (traffic manager `+0x34390`, count at `+0x34450`, at most
  **12** entries) is exactly those groups concatenated in order. Grand Slam:
  `COMPCAR14, COMPCAR12, COMPCAR13 | HEVYCAR35, HEVYCAR33 | HEVYCAR20 | – | HEVYCAR22 |
  HEVYCAR27, HEVYCAR30, HEVYCAR29`. Events that use trams add the tram model
  (`TSPCCARn`) to the table separately.
- **The model files are global.** Traffic models live in `PVEH/COMP/CARnn.BTV` and
  `PVEH/HEVY/CARnn.BTV` (`COMPCAR14` is `PVEH/COMP/CAR14.BTV`), not inside each track,
  so any event can name any of them.
- **The waves name models directly.** A wave vehicle record holds the model ID (and
  the trailer ID for a truck). In all 100 events, every occurrence of a model ID in
  the event block is either its group record or a wave record that spawns it.

| Group | Vehicle type in the waves | Models used by the 100 events |
| --- | --- | --- |
| Cars | 1 | COMPCAR11–19 (cars, taxis, tuk-tuk) |
| Big cars, pickups and vans | 2 | HEVYCAR11–16, 31, 33, 34, 35 (cars, pickups, vans, minibus, motorhome) |
| Buses | 5 | HEVYCAR19, 20, 21 |
| Vans and gritters | 3 | HEVYCAR17, 18, 32 |
| Truck cabs | 4 | HEVYCAR22, 23 |
| Trailers | (with a cab) | HEVYCAR24–27, 29, 30 |

The live editor's **Loaded models** tab shows the current event's set; nothing
outside it can be created live, because the game's creator looks the model up in
that loaded table (and loading a model needs its files streamed from the disc when
the event loads).

## Replacing a model

In **Waves & models (disc)… → Models and goals**, select a model and choose one in
**Replace selected with**. The list offers only models of the same group that some
other event uses and that this event does not load yet. The replacement:

- rewrites the 8-byte ID in the group record and in every wave record that used the
  old model (as model or as trailer), so the event keeps the same number of models
  and the waves spawn the new one wherever they spawned the old one;
- changes nothing else: sizes, counts and every other byte stay the same (checked by
  re-reading the file, and by replacing and restoring in all 100 events, which gives
  back the original files byte for byte);
- shows the change in the **Change** column; choosing the original model again
  undoes it.

From the command line:

```powershell
python scripts/models.py --game-root "<extracted game>" show "Grand Slam"
python scripts/models.py --game-root "<extracted game>" build "Grand Slam" --swap COMPCAR12=COMPCAR18 --swap HEVYCAR35=HEVYCAR31 --iso "<original.iso>" --out "Grand Slam - models test.iso"
```

Then start the new ISO and enter the event from the menu. After that, the live editor
sees the new model as loaded and can create it too.

### Status

The file side is verified (above), and the savestates show the game builds its model
table from these groups. **A play test of an ISO with a replacement is still needed**
to confirm that the game streams the new model and that it drives normally. The test
ISO `outputs/Grand Slam - models test.iso` (local, not in the repository) replaces
`COMPCAR12` (car) with `COMPCAR18` (tuk-tuk) and `HEVYCAR35` (van) with `HEVYCAR31`
(minibus): the tuk-tuks should appear in the first queues of Grand Slam.

## Adding a model

**Models and goals → Add a model to the event** (or choosing a *not loaded yet* model
for a wave vehicle) makes the event load one more model of the same group. The model
lists are the last data the game references in the event block, and the game relocates
their start offsets when it loads the block (seen in savestate RAM), so the editor
writes the six lists, with the new entry, into the empty space at the end of the block
and points the group headers there. Nothing else in the block changes; 52 events keep
bytes nobody references right after the old lists, so those are left untouched.

Limits, both taken from the original events:

- at most **12 models** in the game's table, counting the tram of tram events
  (31 events are already full);
- at most **2,728 KB** of model files, the largest set an original event loads
  (Reiko-chet); the model files are 176–254 KB each.

A model can be added in 65 of the 100 events (4 more lack room at the end of the
block). Like a replacement, an added model needs a play test: the test ISO
`outputs/Grand Slam - speed and added model test.iso` adds the tuk-tuk (`COMPCAR18`) to
Grand Slam, turns the three cars in front of the player on P21 into tuk-tuks and sets
that lane's speed to 10 (about 16 km/h), so they should crawl.

Not offered:

- Models never seen in a Crash event (lumber trailer `HEVYCAR28`, trams outside their
  events).

## Garage cars

The player cars are a different kind of asset: `PVEH/<class>/CARn.BGV` (body) with
`.HWD`/`.LWD` (high and low detail wheels/damage), loaded by the player-car code, not
the traffic `.BTV` files listed in the traffic table. The traffic creator only accepts
IDs from the traffic table (`COMPCARnn`, `HEVYCARnn`, `TSPCCARn`), and the traffic
physics uses its own per-model data. Using a garage car as traffic would need a
traffic version of that car (a `.BTV`) or changes to the game's code, so it is out of
reach for now.
