"""Prepare fixed-size edits to the two native USA Crash event resources."""
from __future__ import annotations

from pathlib import Path
import re
import struct
import tempfile

from editor.catalog import encode_identifier
from resources.crash_events import (
    CrashEvent, CRASHBREAKER_OFFSET, STAGE_KEYS, STAGE_STRIDE, THRESHOLDS_OFFSET, bgd_path, stagehed_path,
)
from resources.native_traffic import read_groups, reorder_groups
from resources.traffic_waves import read_waves, write_waves


def _checked_descriptor(data, start, event, values, wrecks):
    pair = struct.pack("<QQ", encode_identifier(event.track), encode_identifier(event.key))
    if (start < 0 or start + STAGE_STRIDE > len(data)
            or data[start + STAGE_KEYS:start + STAGE_KEYS + 16] != pair
            or data[start + THRESHOLDS_OFFSET:start + THRESHOLDS_OFFSET + 12] != struct.pack("<3f", *values)
            or (wrecks is not None and struct.unpack_from("<I", data, start + CRASHBREAKER_OFFSET)[0] != wrecks)):
        raise ValueError("The event files changed. Reopen the extracted folder.")


def prepare_changes(root: Path, event: CrashEvent, orders, thresholds=None, *,
                    expected_orders=None, crashbreaker_wrecks=None, waves=None, expected_waves=None):
    """Return relative path -> (source, replacement). Omitted fields retain each original value.

    ``waves`` is a WaveSchedule from resources.traffic_waves; ``expected_waves``
    guards against a track file that changed since the schedule was read.
    """
    stage_path = stagehed_path(root)
    track_path = bgd_path(root, event.track)
    stage = stage_path.read_bytes()
    track = track_path.read_bytes()
    _checked_descriptor(stage, event.stage_offset, event, event.thresholds, event.crashbreaker_wrecks)
    _checked_descriptor(track, event.bgd_stage_offset, event, event.bgd_thresholds, event.bgd_crashbreaker_wrecks)
    if struct.unpack_from("<I", track, event.bgd_stage_offset + 0x3C8)[0] != event.event_offset:
        raise ValueError("The traffic block moved. Reopen the extracted folder.")
    if expected_orders is not None and read_groups(track, event.event_offset) != expected_orders:
        raise ValueError("The original model order changed. Reopen the extracted folder.")
    if expected_waves is not None and read_waves(track, event.event_offset).waves != expected_waves:
        raise ValueError("The event's traffic waves changed on disk. Reopen the extracted folder.")
    edited_track = reorder_groups(track, event.event_offset, orders)
    if waves is not None:
        edited_track = write_waves(edited_track, event.event_offset, waves)
    fields = []
    if thresholds is not None:
        if event.thresholds != event.bgd_thresholds:
            raise ValueError("The two goal tables differ for this event.")
        if (len(thresholds) != 3 or any(type(n) is not int or not 0 < n <= 0x7fffffff for n in thresholds)
                or not thresholds[0] > thresholds[1] > thresholds[2]):
            raise ValueError("Use three positive whole-number goals in decreasing order.")
        raw = struct.pack("<3f", *thresholds)
        if struct.unpack("<3f", raw) != tuple(thresholds):
            raise ValueError("One of the goals loses precision in the game's number format.")
        fields.append((THRESHOLDS_OFFSET, raw))
    if crashbreaker_wrecks is not None:
        if event.crashbreaker_wrecks is None or event.crashbreaker_wrecks != event.bgd_crashbreaker_wrecks:
            raise ValueError("Both tables must confirm the same Crashbreaker value.")
        if type(crashbreaker_wrecks) is not int or not 6 <= crashbreaker_wrecks <= 15:
            raise ValueError("Use between 6 and 15 wrecks for the Crashbreaker.")
        fields.append((CRASHBREAKER_OFFSET, struct.pack("<I", crashbreaker_wrecks)))
    edited_stage = stage
    for offset, raw in fields:
        stage_pos = event.stage_offset + offset
        track_pos = event.bgd_stage_offset + offset
        edited_stage = edited_stage[:stage_pos] + raw + edited_stage[stage_pos + len(raw):]
        edited_track = edited_track[:track_pos] + raw + edited_track[track_pos + len(raw):]
    changes = {path.relative_to(root).as_posix(): (old, new)
               for path, old, new in ((stage_path, stage, edited_stage), (track_path, track, edited_track))
               if old != new}
    if not changes:
        raise ValueError("Change a model, a goal, the Crashbreaker count or a traffic wave before exporting.")
    return changes


def export_resources(root: Path, parent: Path, event: CrashEvent, changes) -> Path:
    """Create a unique directory, verifying each exported file against the planned bytes."""
    root, parent = root.resolve(), parent.resolve()
    if parent.is_relative_to(root):
        raise ValueError("Choose an output folder outside the game extraction.")
    if not re.fullmatch(r"1G[A-Z0-9]{10}", event.key):
        raise ValueError("Invalid event key for export.")
    allowed = {p.relative_to(root).as_posix() for p in (stagehed_path(root), bgd_path(root, event.track))}
    if not changes or not changes.keys() <= allowed:
        raise ValueError("Unexpected files in the export.")
    for rel, (source, replacement) in changes.items():
        if not isinstance(source, bytes) or not isinstance(replacement, bytes) or len(source) != len(replacement):
            raise ValueError("The original size of " + rel + " must be preserved.")
        if (root / rel).read_bytes() != source:
            raise ValueError("The source resource changed. Reopen the extracted folder.")
    # A fresh directory isolates concurrent exports and never replaces an existing file.
    directory = Path(tempfile.mkdtemp(prefix=event.key + "-", dir=parent))
    created = []
    try:
        for rel, (_, replacement) in changes.items():
            dest = directory / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as output:
                created.append(dest)
                output.write(replacement)
            if dest.read_bytes() != replacement:
                raise OSError("Could not verify the copy of " + rel)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir():
                path.rmdir()
        directory.rmdir()
        raise
    return directory
