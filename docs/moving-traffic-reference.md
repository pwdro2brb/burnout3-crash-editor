# Repositioning moving traffic in Grand Slam

On 12/11/2026 a small offset was applied to a moving vehicle of Grand Slam in an
isolated copy of PCSX2 1.7.2521.0. Comparing RAM after configured steps of 30 and
120 frames confirmed that the body kept driving and kept its lateral separation.
The instrumented captures were taken on the approach to the Hotel Grand bend.
Later the user tested a variant with a larger offset and reported a visible change
and working collision.

**Update (26/11/2026):** the target, object 9 on path 21, has since been
identified in the event data: it is the fourth vehicle placed by wave 1 on lane
P21, a `COMPCAR14` (colour 0) at distance 1486.08 — the "first red car". Its
starting position can now be edited on the disc; see [traffic waves](traffic-waves.md).

## Reference and selection

The new slot 1 supplied by the user restored the **Grand Slam** intro and, after
Continue, the countdown and GO. The preserved reference is 14,309,260 bytes,
SHA-256 `68e2c8429aa8ef5dfb31c62d248fe86467eaba7f7cd8ba696865dc40a4be4476`.
The earlier references were also preserved.

The intro has 10 active objects and 9 nodes; the approach used by the test, 12
objects and 10 nodes. The examined invariants passed. Four known code words match
the researched ELF; that does not prove the whole state is unmodified.

The target was independent object 9, linked to node 8 / path 21, with two
initialized physics points and a valid collision descriptor. Objects 5/6 form an
articulated set and were excluded. Some distant objects are active but have zeroed
anchors; they cannot be used by this method yet, and the prototype now refuses
degenerate anchor pairs.

## Change and comparison

The approach reference has SHA-256
`3abef54f23f5029e0eb5e9afbd4de00ffbdce21db5ce03a4111f2635d6a210a9`. The variant
changed seven floats: X/Z of both physics points and of the current translation,
plus the node's lateral fraction, from about 0.4635 to 0.55. The effective
horizontal delta was `(+0.212890625, -0.462646484375)` in X/Z, about 0.51 game
units. Every other byte of the input RAM and the other ZIP members were preserved.

The offset was recomputed for the current point of the path; reusing the vector
estimated at the intro would point in another direction after the bend. The local
projection of width and AABB helped choose the variant but does not replace a real
contact test with the road or another vehicle.

Control and variant were restored separately with the same neutral inputs and the
same number of step commands. Frame numbers are the steps configured in the
emulator; an internal game counter was not validated independently.

| Configured step | Control distance since start | Variant distance since start | Separation between the cars |
| --- | ---: | ---: | ---: |
| 30 frames | 6.716 | 6.713 | 0.513 |
| 120 frames | 26.621 | 26.608 | 0.523 |

Distances are norms between sampled positions in game units, not integrated path
lengths or established metres. Path progress and the candidate speed fields were
equal between control and variant, and the 0.55 lateral fraction stayed in both steps.

The game updated both physics points, the transform, the stored target and the
AABB. Y also changed during the run (the difference between the bodies stayed near
-0.0205 and -0.0197). Orientation and AABB extents differed slightly; the result is
not an exactly rigid translation in a bend.

In both pairs the other 253 object records, the other 253 nodes and their matrices
were byte-identical, as were the 11 descriptors of the other active objects, the
examined manager region and the inferred player block. There are differences in
unclassified RAM; no global absence of side effects was shown.

Restoring the control and repeating 30 frames reproduced exactly the same 32 MiB
of EE RAM. Saves, captures and comparison reports stay local.

## Larger variant and manual test

The first manual attempt used lateral 0.55; the user said the controls responded
but the emulator closed and the change was not noticed. At the user's request a new
copy used lateral 0.85, an effective XZ delta of `(+0.95166015625,
-2.0672607421875)`, about 2.276 units. The cause of the closing was not established.

The user took the wheel and reported: "I saw the change and the collision worked",
pointing at the first red car. That report is separate from the 30/120-frame samples
of the 0.55 variant; there was no instrumented capture of the impact.

A later trial added an independent instance behind this target; see
[vehicle-creation-milestone.md](vehicle-creation-milestone.md).

## Limits

The result confirms a limited physical repositioning of an existing moving
instance, followed by a manual confirmation of the change and the collision. An
instrumented impact and longer runs with more models are still needed before
generalizing. This test neither created an instance nor changed a persistent
resource of the event. The ISO, the executable and the original saves were not written.
