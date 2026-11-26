"""Exercise the native export from selection through verified resource copies."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.catalog import encode_identifier
from editor.test_native_traffic import EVENT, GROUPS, make_bgd
from resources.crash_events import (
    CrashEvent, CRASHBREAKER_OFFSET, STAGE_KEYS, STAGE_STRIDE, STAGE_TABLE,
    THRESHOLDS_OFFSET, bgd_path, stagehed_path,
)
from resources.native_edit import export_resources, prepare_changes
from resources.native_traffic import reorder_groups


class NativeEditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "game"
        self.output = Path(tmp.name) / "exports"
        self.output.mkdir()
        goals = (280000.0, 200000.0, 60000.0)
        self.event = CrashEvent("1G0007EUC3V1", "EU_C3_V1", "Example", 96, 0,
                                STAGE_TABLE, 0x800, EVENT, goals, goals, 8, 8)
        self.new_order = (GROUPS[0][::-1], *GROUPS[1:])
        self.new_goals = (300000, 180000, 70000)
        self.stage = stagehed_path(self.root)
        self.track = bgd_path(self.root, self.event.track)
        self.stage_name = self.stage.relative_to(self.root).as_posix()
        self.track_name = self.track.relative_to(self.root).as_posix()
        for path, offset, source in (
                (self.stage, STAGE_TABLE, bytes(STAGE_TABLE + 2 * STAGE_STRIDE)),
                (self.track, self.event.bgd_stage_offset, make_bgd())):
            data = bytearray(source)
            struct.pack_into("<QQ", data, offset + STAGE_KEYS,
                             encode_identifier(self.event.track), encode_identifier(self.event.key))
            struct.pack_into("<3f", data, offset + THRESHOLDS_OFFSET, *goals)
            struct.pack_into("<I", data, offset + CRASHBREAKER_OFFSET, self.event.crashbreaker_wrecks)
            path.parent.mkdir(parents=True)
            path.write_bytes(data)

    def test_both_replacements_match_bytes_and_verified_exports_are_independent(self):
        original_stage, original_track = self.stage.read_bytes(), self.track.read_bytes()
        plan = prepare_changes(self.root, self.event, self.new_order, self.new_goals,
                               expected_orders=GROUPS, crashbreaker_wrecks=6)
        expected_stage, expected_track = bytearray(original_stage), bytearray(original_track)
        for data, offset in ((expected_stage, self.event.stage_offset), (expected_track, self.event.bgd_stage_offset)):
            struct.pack_into("<3f", data, offset + THRESHOLDS_OFFSET, *self.new_goals)
            struct.pack_into("<I", data, offset + CRASHBREAKER_OFFSET, 6)
        for offset, name in zip((EVENT + 0x120, EVENT + 0x138), self.new_order[0]):
            struct.pack_into("<Q", expected_track, offset, encode_identifier(name))
        self.assertEqual(plan, {self.stage_name: (original_stage, expected_stage),
                                self.track_name: (original_track, expected_track)})
        dirs = [export_resources(self.root, self.output, self.event, plan) for _ in range(2)]
        self.assertNotEqual(*dirs)
        for target in dirs:
            for rel, (_, data) in plan.items():
                self.assertEqual((target / rel).read_bytes(), data)
        self.assertEqual(self.stage.read_bytes(), original_stage)
        self.assertEqual(self.track.read_bytes(), original_track)

    def test_traffic_only_preserves_distinct_local_thresholds(self):
        local = (290000.0, 200000.0, 60000.0)
        event = replace(self.event, bgd_thresholds=local)
        original = bytearray(self.track.read_bytes())
        pos = event.bgd_stage_offset + THRESHOLDS_OFFSET
        struct.pack_into("<3f", original, pos, *local)
        self.track.write_bytes(original)
        plan = prepare_changes(self.root, event, self.new_order)
        self.assertEqual(set(plan), {self.track_name})
        self.assertEqual(struct.unpack_from("<3f", plan[self.track_name][1], pos), local)
        with self.assertRaisesRegex(ValueError, "differ"):
            prepare_changes(self.root, event, self.new_order, self.new_goals)
        plan = prepare_changes(self.root, event, GROUPS, crashbreaker_wrecks=15)
        for rel, offset in ((self.stage_name, event.stage_offset), (self.track_name, event.bgd_stage_offset)):
            source, edited = plan[rel]
            expected = bytearray(source)
            struct.pack_into("<I", expected, offset + CRASHBREAKER_OFFSET, 15)
            self.assertEqual(edited, expected)

    def test_crashbreaker_source_mismatch_preserves_edits_to_other_fields(self):
        original = bytearray(self.track.read_bytes())
        pos = self.event.bgd_stage_offset + CRASHBREAKER_OFFSET
        struct.pack_into("<I", original, pos, 9)
        self.track.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "files changed"):
            prepare_changes(self.root, self.event, GROUPS, crashbreaker_wrecks=12)
        event = replace(self.event, bgd_crashbreaker_wrecks=9)
        with self.assertRaisesRegex(ValueError, "same Crashbreaker value"):
            prepare_changes(self.root, event, GROUPS, crashbreaker_wrecks=12)
        plan = prepare_changes(self.root, event, self.new_order, self.new_goals)
        self.assertEqual(struct.unpack_from("<I", plan[self.track_name][1], pos), (9,))
        self.assertEqual(struct.unpack_from("<I", plan[self.stage_name][1],
                                           event.stage_offset + CRASHBREAKER_OFFSET), (8,))

    def test_crashbreaker_rejects_outside_range_or_unknown_baseline(self):
        for count in (5, 16, -1, True, 8.0, "8"):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "6 and 15"):
                prepare_changes(self.root, self.event, self.new_order, crashbreaker_wrecks=count)
        legacy = replace(self.event, crashbreaker_wrecks=None, bgd_crashbreaker_wrecks=None)
        with self.assertRaisesRegex(ValueError, "same Crashbreaker value"):
            prepare_changes(self.root, legacy, GROUPS, crashbreaker_wrecks=12)
        self.assertEqual(set(prepare_changes(self.root, legacy, self.new_order)), {self.track_name})
        with self.assertRaisesRegex(ValueError, "before exporting"):
            prepare_changes(self.root, self.event, GROUPS, crashbreaker_wrecks=8)

    def test_unchanged_invalid_and_lossy_thresholds(self):
        for goals in (None, self.event.thresholds, (4, 4, 1), (4, 2, 0), (16777217, 2, 1), (3.5, 2, 1)):
            with self.subTest(goals=goals), self.assertRaises(ValueError):
                prepare_changes(self.root, self.event, GROUPS, goals)

    def test_reject_changed_group_order_even_on_goals_only_export(self):
        self.track.write_bytes(reorder_groups(self.track.read_bytes(), EVENT, self.new_order))
        with self.assertRaisesRegex(ValueError, "original model order"):
            prepare_changes(self.root, self.event, GROUPS, self.new_goals, expected_orders=GROUPS)

    def test_moved_or_truncated_track_descriptor_and_stale_stage(self):
        track = self.track.read_bytes()
        moved = bytearray(track)
        struct.pack_into("<I", moved, self.event.bgd_stage_offset + 0x3C8, EVENT + 0x800)
        for data in (moved, track[:self.event.bgd_stage_offset + THRESHOLDS_OFFSET + 12]):
            self.track.write_bytes(data)
            with self.assertRaises(ValueError):
                prepare_changes(self.root, self.event, self.new_order)
        self.track.write_bytes(track)
        stage = bytearray(self.stage.read_bytes())
        stage[self.event.stage_offset + STAGE_KEYS] ^= 1
        self.stage.write_bytes(stage)
        with self.assertRaisesRegex(ValueError, "files changed"):
            prepare_changes(self.root, self.event, self.new_order)

    def test_refuses_unsafe_or_obsolete_export_without_creating_files(self):
        plan = prepare_changes(self.root, self.event, self.new_order)
        for folder in (self.root, self.track.parent):
            with self.assertRaises(ValueError):
                export_resources(self.root, folder, self.event, plan)
        for invalid in ({"../foreign": (b"a", b"b")}, {self.track_name: (b"a", b"bc")}):
            with self.assertRaises(ValueError):
                export_resources(self.root, self.output, self.event, invalid)
        self.track.write_bytes(plan[self.track_name][1])
        with self.assertRaisesRegex(ValueError, "source resource changed"):
            export_resources(self.root, self.output, self.event, plan)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_readback_error_leaves_no_partial_copy(self):
        plan = prepare_changes(self.root, self.event, self.new_order, self.new_goals)
        read = Path.read_bytes
        def damaged(path):
            if path.name == self.track.name and path.is_relative_to(self.output):
                return b"test readback error"
            return read(path)
        with patch.object(Path, "read_bytes", damaged), self.assertRaisesRegex(OSError, "verify the copy"):
            export_resources(self.root, self.output, self.event, plan)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
