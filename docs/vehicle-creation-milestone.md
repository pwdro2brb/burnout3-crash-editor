# First additional vehicle in Grand Slam — partial result

On 12/11/2026 a local trial created a new independent instance behind the vehicle
repositioned earlier in Grand Slam. The creation was checked in the game's
structures. After taking the wheel, **the user reported that the car appeared and
the collision worked**. That manual feedback is recorded separately from the
instrumented checks of structures and positions.

The experiment used new save-state copies in the isolated PCSX2. The ISO, the ELF
and the user's original saves were not written. The experimental creation code
was later generalized into the external editor (see [editor-status.md](editor-status.md)).

## Creation through the original routine

A one-shot call to the game's own creation routine received the target's already
loaded model, its path and a smaller progress value, to place the car behind it.
The game allocated the records, linked the path and registered the new collider.
No active vehicle was removed or moved to fake an addition.

After a configured 30-frame step, the call's return pointed to the new object 12
and the new node 10. The previous target stayed as object 9, node 8, on path 21.

| Structure | Before | After |
| --- | ---: | ---: |
| Active objects | 12 | 13 |
| Active nodes | 10 | 11 |
| Collision descriptors | 32 | 33 |
| Endpoints per axis | 64 | 66 |

Objects include articulated components: **13 objects does not mean 13 independent
cars**. The new object has the same type and model as the target, finite and
separate physics points and its own collider. Free lists, bitmaps, counts,
identities, backlinks, the path chain/grid and the collision/endpoint records all
passed the implemented checks. The 30 frames are the emulator's configured step;
no valid evidence covers a 120-frame window for this creation.

## Cleanup and alignment

After checking the creation, a new copy restored the instructions used by the
temporary call and cleaned its helper area, keeping the records created by the
game. The version handed over for the manual test does not keep code installed to
create cars repeatedly.

The repositioner already used in the research aligned only the new car to lateral
0.85. Both cars sit on that lateral; the new object's centre is about **10.85 game
units behind** the target (a distance between saved positions, not metres). The
other 253 object records stayed identical during that alignment step, including the
previous target. The script did not write the cached target, the path matrix or the
new object's AABB; those dependent data must update while running.

## Manual test and limits

In the test copy prepared for the user, slot 1 kept the previous version with the
offset and without the extra car; slot 2 held the new instance. Replaced contents
were preserved. Reloading slot 2 restores the extra instance; the game's internal
Restart can recreate the event data.

The manual test of the extra instance got the reply: "It appeared and the
collision worked." The full impact sequence was not captured nor tied by
instrumentation to object 12. Time samples of movement after the alignment, an
instrumented impact and a longer run are still missing, and general capacity,
other models/locations and persistence after restarting the event were not
established.

Saves, captures, RAM reports and executable exports stay local.
