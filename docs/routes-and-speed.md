# Traffic paths and speed

Update of 15/11/2026 for Burnout 3 USA `SLUS-21050` / CRC `BEBF8793` on PCSX2
1.7.2521. This step improves reading and editing of the loaded event; it does not
create a new road mesh or change ISO resources.

## Viewing the paths

1. Connect the editor, pause PCSX2 and use **Refresh list**.
2. Open **Top view** and keep **Show lanes** on.
3. Select a vehicle and use **Path** to frame the lane it drives on; the selected
   path is highlighted.
4. Zoom and pan to look at junctions, bends and stretches beyond the vehicles
   visible at that moment.

The drawing shows both edges and the approximate centre of the loaded traffic
lanes; `P…` labels tell the paths apart. Arrows show **increasing progress along
the path**; they do not by themselves establish a network of connections between
roads or the direction allowed for the player's car.

Paths with a vehicle reference are distinguished from candidate descriptors with no
observed reference. A candidate passes identity and geometry checks, but that does
not prove the event uses that stretch, that it connects to the next one or that
creation there is compatible. The traffic direction is confirmed only when a moving
reference corroborates the path's orientation.

Curves are sampled and the read uses memory and point budgets; a partial read can
leave paths out, and the map notice says so. The drawing is not the asphalt, the
collision geometry, buildings, obstacles or a full scenery map. Crossings in X/Z can
be at different heights. The data match the last paused read.

**Add at point** still uses an approximate projection onto an admitted path, with
the height of its geometry. Marking X/Z neither picks new terrain nor sets Y
freely, and drawing a candidate descriptor does not make it a valid reference.

The same paths exist on the disc: `GAMEDATA.BGD` stores every lane's control
points and a cumulative distance table, which is how [traffic waves](traffic-waves.md)
places vehicles by distance (`resources/native_roads.py` reads both).

## Reading the speed

When you select a vehicle with a recognized traffic node, the interface separates
the **nominal target** from the **nominal follow** value. They can differ:

| Information | Researched meaning | Use in the editor |
| --- | --- | --- |
| Original control, node `+0` | Target used by the traffic controller | Can be changed, with the profile checks |
| Progress, node `+0x2c` | Value the game uses to advance along the path after its traffic control | Read only |
| Separate field, node `+0x24` | Argument kept from the creator; its full meaning is not settled | Preserved, not treated as speed |

The controller applies the factor **0.44704** to the target, consistent with a
nominal mph scale. The interface shows `control × 1.609344` and `progress × 3.6` as
**nominal km/h**. These are conversions of internal fields, not measurements of the
car's physical or rendered speed, nor proof that every game coordinate is in metres.

Queues, obstacles and traffic states can reduce progress, down to zero, while the
target stays positive. This matches the user's observation that overlapping
vehicles can wait for room to get out of a jam. The 8-unit margin (30 for sets and
buses) is a conservative restriction of the editor's normal mode, not a mandatory
engine minimum.

Records without a recognized node show the speed as unavailable instead of turning
zeroed default fields into a fake measurement. Linked trailers say that the control
belongs to the cab. Vehicles already converted to another physics state may no
longer have an editable traffic control.

## Changing the target

1. Pause PCSX2 and select one or more vehicles with an available control. Use
   **Ctrl** to pick several or **Shift** for a range; **Select speed-eligible**
   gathers the enabled records.
2. Fill **Nominal target (km/h)** and click **Apply speed**, or **Apply to the N
   selected** with more than one. All get the same target; if any record is blocked,
   the whole selection is refused.
3. Resume the game to watch the controller respond. Compare target and follow at the
   next paused read, especially in a queue.

For trucks, select the cab, not the trailer. The focused row remains the reference
for moving or adding vehicles; those actions are not multiplied by the speed selection.

A target of **zero** asks the game's normal control to stop; it does not directly
zero the physical speed or the current progress. Raising the target later lets the
controller seek another speed, but does not remove a car blocking the way nor
guarantee immediate acceleration.

In normal mode the original control range is `0..240`, the range the researched
creator admits, about `0..386.24 km/h` in the nominal display; it is not a
universally validated stable range. Experimental mode accepts larger finite targets
representable in float32, with the risk warning kept.

The change writes only **one target float per vehicle**. The editor checks the
pause, the object–node association, the owner, path, node state, type and previous
value of every selected record before sending the writes in a single action. A
transport failure can still interrupt the write; it is not an atomic transaction.
Physics and computed fields stay under the game's control; progress, acceleration,
the `+0x24` field and the trailer are never written directly.

**Save recipe…** keeps the speed action in the JSON recipe with the other
actions; the recipe needs its matching initial reference, and an experimental action
needs experimental mode when loading. A `.p2s` keeps a moment of the session.
Restarting or changing event can rebuild the original traffic values. A vehicle seen
after the initial reference can still be edited when it passes the profile checks,
but **Save recipe…** refuses a recipe that depends on it.

## Basis of the interpretation

The creator writes the control into the node at `0x00164d90`. The initializer
`0x00161590` produces the initial progress with the 0.44704 factor (the constant
was resolved in the loaded ELF region at `0x004e11f4` through its GP value). The
routine `0x00161b50` adjusts progress for behaviour and obstacles, and
`0x00162e80` integrates the progression using that value, the game delta at
`0x0052267c` and the segment length. That sequence supports the distinction between
target, follow value and observed physical movement.

The user confirmed that the paths-and-speed revision worked and later that the
multi-selection and the batch-wait fix worked. That confirmation is manual; passing
the automated tests does not show the real response of every model, a physical km/h
calibration or stability in dense scenes. Many-car crashes and rendering are covered
in [high-density-experiments.md](high-density-experiments.md).
