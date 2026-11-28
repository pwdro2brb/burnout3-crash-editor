# Editing an event in the game files

Open **Open Editor.cmd** and click **Traffic waves…** or **Project → Native events / traffic waves…**. This window works with PCSX2
closed. Choose **Open game folder…** and pick the extracted Burnout 3 USA folder that
contains `DATA` and `TRACKS`. If the extraction sits next to the editor with its
default name, the window opens the catalogue automatically.

## Preparing an edit

1. Search the event by name, track or key. **Find session event** selects the last
   event identified when the session list was refreshed with PCSX2 paused.
2. In **Models and goals**, hold **Ctrl** and select two models of the same group.
   Click **Swap two models of the same group**. The event keeps every model it
   loaded; this edits the order of the event's model list. The scripted traffic names
   its models directly, so the order probably does not change which vehicles appear
   (see [traffic waves](traffic-waves.md)).
3. Set the gold, silver and bronze dollar goals as whole numbers in decreasing order.
   **Wrecks to unlock the Crashbreaker** sets how many vehicles must crash to unlock
   the explosion; the editor accepts 6 to 15, the range used by the original events.
   The goals are read only in the two events where the game's own tables disagree.
4. **Traffic waves** shows and edits when and where each vehicle enters the event:
   see [traffic-waves.md](traffic-waves.md).
5. **Track paths** shows the centre lines of the lanes from above. One track can host
   several events, and the drawing covers the whole track, including roads far from
   the junction.
6. **Build ISO copy…** asks for the image that matches the extraction and a new name
   for the output. Keep room for a whole second ISO. To work only with the resources,
   use **Export files…** and pick a destination; the editor creates a unique subfolder
   with the edited files. Each export includes the edits of the selected event.

The same operations are available from the command line for traffic waves:
`python scripts/waves.py --help`.

## The Grand Slam test

In the original USA version the gold goal is **$280,000**, silver **$200,000**,
bronze **$60,000**, and the Crashbreaker needs **10 wrecks**. An easy-to-spot test is
to change gold to **$310,000**, the Crashbreaker to **6**, and swap `COMPCAR14` with
`COMPCAR12` in the first group.

Start the new ISO in PCSX2 from boot and enter Grand Slam from the game menu (your
memory-card progress can be used to reach the event). An old savestate brings back
the round data already in RAM. Check the gold goal on the event screen and the
Crashbreaker counter at the start of the round.

That combination was exported and started on PCSX2 1.7.2521. A full comparison of the
images found ten different bytes in the two expected files. After boot, the table
loaded by the game held the Grand Slam key, the goals of $310,000, $200,000 and
$60,000 and the six-wreck counter; the order of the two models was checked in the
track file. The player started the test and confirmed the round worked. Which model
appeared where and the exact moment the Crashbreaker unlocked were not recorded.

## How the data were checked

- The 100 Crash records in `PRGDATA.BIN` identify event and track. The order of the
  100 keys matches the one the USA executable uses to look up titles in
  `GLOBALUS.BIN`. Grand Slam uses key `1G0007EUC3V1` and the file
  `TRACKS/EU/C3_V1/GAMEDATA.BGD`.
- The key links the `DATA/STAGEHED.BIN` record to the descriptor in the track's
  directory. The three goals are at `+0x3A0`, `+0x3A4` and `+0x3A8`; the event screen
  links them to the gold, silver and bronze texts. The field at `+0x3AC` feeds the
  wrecked-vehicle counter shown by the Crashbreaker.
- Each event block holds six model groups. In all 100 events, swapping the order of
  the identifiers, re-reading and undoing the swap recovered the original files byte
  for byte. The export keeps the models' auxiliary fields and the file sizes.
- 2,572 paths were read from 36 track files. In Grand Slam, the 27 paths and 2,821
  point pairs match the capture of the event in memory. The V1 and V2 variants of the
  same track can share geometry; the event identifier tells which one was loaded.
- To export the ISO, the editor fully checks the source files, keeps their sectors and
  verifies the written copy by SHA-256 before making it available. The edit takes the
  place of the existing menu entry.
