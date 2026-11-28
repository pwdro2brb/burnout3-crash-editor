# Event cameras: the preview fly-by and the results tally

Every Crash event uses two scripted cameras:

1. **The preview fly-by**, before the countdown: the camera leaves the player's car,
   flies down the road to the junction and shows the traffic.
2. **The results tally**, after the crash: the camera travels along a route and shows
   the value of each wrecked vehicle. It stops after the last wrecked vehicle on its
   route or at the end of the route, so in several events it stops before showing every
   wreck.

Placing an event in a new location needs both. This page records what is known so far
(Grand Slam, USA `SLUS-21050`, PCSX2 1.7.2521). Research is ongoing.

## Resource 0 of the event

Each event descriptor in the track's `GAMEDATA.BGD` has four resources. Resource 0
(0x800 bytes in Grand Slam) is loaded right before the event block, and the game
relocates its two offsets at `+0x3E0` and `+0x3E4` (`FUN_003a20e0`).

| Offset | Content in Grand Slam | Status |
| --- | --- | --- |
| `+0x000…+0x1DF` | six 0x50-byte transforms (3×4 rotation, position, value `0x25`) | **Start grid.** The player's car sits exactly on transform 0 (-2680.9, -27.5, 754.9) before GO. |
| `+0x1E0…+0x25F` | four 0x20-byte entries: position, a float (13–20), a direction; one pair next to the start, one near the queue of lane P20 | unknown |
| `+0x3E0` → list | 13 entries of 0x20 bytes: position, then a code such as `0x700…0x703`, `0x604…0x607`, `0x204…0x206`, `0x408`, `0x200` (count at `+0x3F8`) | **Preview camera route** (see below); the codes are not decoded |
| `+0x3E4` → list | empty in Grand Slam (count at `+0x3F4`) | unknown |

## The preview fly-by

Observed in an isolated PCSX2 copy, sampling the camera position 20 times per second:

- While the preview plays, the game sets the flag at `0x00665ea0`. The event clock
  starts again from zero and the traffic schedule is fast-forwarded: every timed
  vehicle due before 45 s is released at once and later waves load 0.1 s apart (Grand
  Slam had both waves loaded by 4.1 s instead of 9 s). This is how the preview shows
  the whole traffic of the event.
- The camera (a position vector at `0x01E32A50` in that session) holds behind the car
  for about 4 s, then flies to the junction. It passes 12–14 units above the points of
  the resource-0 list, in order — `0x700`, `0x200`/`0x204`, `0x701`, `0x604`/`0x705`,
  `0x702`/`0x205`, `0x703`, `0x606` — slowing down or pausing near several of them, and
  ends above `0x606` at about 12 s.
- The flag then returns to 0 and the camera waits, static, behind the car on the start
  grid: the screen before the countdown.

So the list at `+0x3E0` is the route the preview camera follows. What the high byte of
each code means (7, 6, 2, 4: pause, look-at, speed?) is still open.

## The results tally

Not observed yet: the unattended test run ended without wrecked vehicles, so no tally
was shown. The working hypothesis is that the tally camera follows a stored route too,
probably the same resource-0 list or the event block's `+0x9C` list of (node, path)
points (725 valid points across the 100 events), and stops after the last wreck it
passes. That would explain why wrecks away from the route are not shown.

To test it, the next step is a few savestates taken during the tally (start, middle,
the moment it stops) in an event where the camera shows every wreck and in one where
it stops early. The camera vector can then be traced the same way and compared with
both lists.
