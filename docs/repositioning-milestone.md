# First observed repositioning

On 12/11/2026 a reversible move of an existing vehicle was confirmed on the
researched USA profile, using a copy of a PCSX2 1.7.2521.0 save state.

The target was an independent car of the traffic pool. A first variant changed
only the path's lateral fraction: that moved the following matrix but not the
physical body. The visual position is rebuilt from two absolute points of the
object, at `+0x00` and `+0x30`.

The confirmed test moved the X/Z components of both points and of the matrix
translation at `+0xa0`, together with the node's lateral fraction at `+0x34`:
seven input floats, a delta of `(+2.1409912109375, 0, +0.3963623046875)` in world
units.

After the configured 30-frame step, the body, the path matrix, the stored target
and the AABB kept that delta. The box kept its size and the orientation was the
same. The game itself updated the target and the bounds; the variant did not write
them. The other 253 records of the object pool were identical to the control, as
were their matrices. One scalar of a neighbouring node changed; its meaning is not
established.

In the picture, the difference was limited to the distant vehicle near the
junction. Restoring the reference brought back exactly the control viewport.
Captures, save states and RAM reports stay local.

The user confirmed that parked and slow vehicles are a normal part of these
events; standing still does not by itself indicate a broken state.

The result covers a horizontal move, one independent vehicle and a short
simulation window. Impact against the moved car, larger moves, other models,
rotation, articulated vehicles and event persistence still need testing.
Persistence on the disc is now covered by [traffic waves](traffic-waves.md).
