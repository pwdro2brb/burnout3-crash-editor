"""The fixture constructs synthetic event identities, labels and descriptors."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.catalog import encode_identifier
from resources import crash_events as events


class NativeCrashCatalogTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.stage_file = events.stagehed_path(self.root)
        self.bgd_file = events.bgd_path(self.root, "EU_C1_V1")
        self.stage_file.parent.mkdir()
        self.bgd_file.parent.mkdir(parents=True)
        self.progress_file = self.stage_file.with_name("PRGDATA.BIN")
        self.global_file = self.stage_file.with_name("GLOBALUS.BIN")

        count = events.CRASH_COUNT
        stages = bytearray(events.STAGE_TABLE + count * events.STAGE_STRIDE)
        def track_name(tier):
            return f"EU_C{tier + 1}_V1"
        # Each test track contains a 20-sector native descriptor directory.
        tracks = [bytearray(41 * events.SECTOR) for _ in range(5)]
        for bgd in tracks:
            struct.pack_into("<I", bgd, 0, 9)
            struct.pack_into("<20I", bgd, 0x198, *(i * events.SECTOR for i in range(1, 21)))
            struct.pack_into("<3I", bgd, 0x260, 20, events.SECTOR, 21 * events.SECTOR)
        progress = bytearray(0x1A00 + count * 0x20)
        struct.pack_into("<I", stages, 0, 8)
        struct.pack_into("<I", stages, 0x260, count)
        struct.pack_into("<III", progress, 0, 4, 0x20, 2)
        struct.pack_into("<II", progress, 0x28, 0x30, 5)
        for ordinal in range(count):
            tier, position = divmod(ordinal, 20)
            bgd = tracks[tier]
            stage_index = count - 1 - ordinal
            start = events.STAGE_TABLE + events.STAGE_STRIDE * stage_index
            entry = 0x100 + ordinal * 0x40
            child = 0x1A00 + ordinal * 0x20
            if not position:
                struct.pack_into("<II", progress, 0x40 + tier * 0x18, entry, 20)
            struct.pack_into("<II", progress, entry + 0x34, child, 1)
            track = encode_identifier(track_name(tier))
            key = encode_identifier(f"1GTEST{ordinal}")
            struct.pack_into("<QQII", progress, child, track, key, 96 + ordinal, 6)
            local = events.SECTOR * (position + 1)
            for data, base in ((stages, start), (bgd, local)):
                struct.pack_into("<QQ", data, base + events.STAGE_KEYS, track, key)
                struct.pack_into("<I", data, base + 0x3BC, events.SECTOR)
                struct.pack_into("<3f", data, base + 0x3A0, 1500, 1000, 500)
                struct.pack_into("<I", data, base + events.CRASHBREAKER_OFFSET, 10)
            struct.pack_into("<I", stages, start + 0x3C0, stage_index)
            struct.pack_into("<I", bgd, local + 0x3C8, (21 + position) * events.SECTOR)
        # An original level can have different thresholds in its two files.
        struct.pack_into("<f", tracks[0], events.SECTOR + 0x3A0, 2200)
        struct.pack_into("<I", tracks[0], events.SECTOR + events.CRASHBREAKER_OFFSET, 12)
        self.stage_file.write_bytes(stages)
        for tier, bgd in enumerate(tracks):
            path = events.bgd_path(self.root, track_name(tier))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bgd)
        self.progress_file.write_bytes(progress)

        text_count = events.FIRST_TITLE + count + 1
        strings = bytearray(16 + 4 * text_count)
        struct.pack_into("<II", strings, 8, text_count, 16)
        for index in range(text_count):
            value = "X"
            if events.FIRST_UPPERCASE_TITLE <= index < events.FIRST_TITLE:
                value = f"EVENTO {index - events.FIRST_UPPERCASE_TITLE}"
            if events.FIRST_TITLE <= index < events.FIRST_TITLE + count:
                value = f"Evento {index - events.FIRST_TITLE}"
            struct.pack_into("<I", strings, 16 + 4 * index, len(strings))
            strings.extend((value + "\0").encode("utf-16le"))
        self.global_file.write_bytes(strings)

    def test_join_uses_native_keys_and_preserves_both_source_values(self):
        catalog = events.load_crash_events(self.root)
        first = catalog[0]
        self.assertEqual(len(catalog), 100)
        self.assertEqual((first.key, first.title, first.stage_index),
                         ("1GTEST0", "Evento 0", 99))
        self.assertEqual((first.thresholds, first.bgd_thresholds),
                         ((1500, 1000, 500), (2200, 1000, 500)))
        self.assertEqual(catalog[-1].progression_index, 195)
        self.assertEqual(first.bgd_stage_offset, events.SECTOR)
        self.assertEqual((first.crashbreaker_wrecks, first.bgd_crashbreaker_wrecks), (10, 12))
        self.assertEqual(first.event_offset, 21 * events.SECTOR)

    def test_rejects_duplicate_track_descriptor(self):
        data = self.bgd_file.read_bytes()
        with self.bgd_file.open("r+b") as handle:
            handle.seek(2 * events.SECTOR)
            handle.write(data[events.SECTOR:2 * events.SECTOR])
        with self.assertRaisesRegex(ValueError, "duplicado"):
            events.load_crash_events(self.root)

    def test_duplicate_bytes_outside_the_directory_are_not_descriptors(self):
        data = self.bgd_file.read_bytes()
        with self.bgd_file.open("ab") as handle:
            handle.write(data[events.SECTOR:2 * events.SECTOR])
        self.assertEqual(len(events.load_crash_events(self.root)), 100)

    def test_rejects_corrupt_progression_child_offset(self):
        with self.progress_file.open("r+b") as handle:
            handle.seek(0x134)
            handle.write(struct.pack("<I", 0xFFFFFFFF))
        with self.assertRaisesRegex(ValueError, "offset"):
            events.load_crash_events(self.root)

    def test_rejects_mismatched_title_series(self):
        data = bytearray(self.global_file.read_bytes())
        first = struct.unpack_from("<I", data, 16 + events.FIRST_TITLE * 4)[0]
        data[first:first + 2] = "A".encode("utf-16le")
        self.global_file.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "títulos"):
            events.load_crash_events(self.root)

    def test_rejects_missing_stage_and_external_track_path(self):
        with self.stage_file.open("r+b") as handle:
            handle.seek(events.STAGE_TABLE + events.STAGE_KEYS)
            handle.write(bytes(16))
        with self.assertRaisesRegex(ValueError, "Faltam descritores"):
            events.load_crash_events(self.root)
        with self.assertRaises(ValueError):
            events.bgd_path(self.root, "../C1_V1")
