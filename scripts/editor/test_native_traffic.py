"""Exercise event directory isolation and model permutations with generated data."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.catalog import encode_identifier
from resources.native_traffic import read_groups, reorder_groups


EVENT = 0x2000
PEER = 0x2800
GROUPS = (("COMPCAR14", "COMPCAR12"), ("HEVYCAR33",), ("HEVYCAR20",),
          (), ("HEVYCAR22",), ("HEVYCAR27", "HEVYCAR29"))


def make_bgd():
    data = bytearray(0x4000)
    struct.pack_into("<I", data, 0, 9)
    struct.pack_into("<2I", data, 0x198, 0x800, 0x1000)
    struct.pack_into("<3I", data, 0x260, 2, 0x800, 0x1800)
    for stage, key, offset in ((0x800, "1G0007EUC3V1", EVENT), (0x1000, "0E0300EUC3V1", PEER)):
        struct.pack_into("<Q", data, stage + 0x398, encode_identifier(key))
        struct.pack_into("<8I", data, stage + 0x3BC,
                         0x800, 0x1800, 0x800, offset, 0x800, 0x3000, 0x800, 0x3800)
    struct.pack_into("<I", data, EVENT + 0x28, 8)
    cursor = 0x120
    for group in (0, 1, 3, 4, 2, 5):
        names = GROUPS[group]
        struct.pack_into("<3I", data, EVENT + 0x54 + group * 12, cursor, len(names), len(names))
        for name in names:
            struct.pack_into("<Q4I", data, EVENT + cursor, encode_identifier(name), 100, 0, 1, 0)
            cursor += 24
    return bytes(data)


def replace_fields(data, pos, fmt, *values):
    result = bytearray(data)
    struct.pack_into(fmt, result, pos, *values)
    return bytes(result)


class NativeTrafficTests(unittest.TestCase):
    def test_reorder_changes_only_requested_ids_and_round_trips_exactly(self):
        original = make_bgd()
        self.assertEqual(read_groups(original, EVENT), GROUPS)
        orders = (tuple(reversed(GROUPS[0])), *GROUPS[1:])
        edited = reorder_groups(original, EVENT, orders)
        expected = bytearray(original)
        for position, name in zip((EVENT + 0x120, EVENT + 0x138), orders[0]):
            struct.pack_into("<Q", expected, position, encode_identifier(name))
        self.assertEqual(edited, bytes(expected))
        self.assertEqual(read_groups(edited, EVENT), orders)
        self.assertEqual(reorder_groups(edited, EVENT, GROUPS), original)
        self.assertEqual(reorder_groups(original, EVENT, GROUPS), original)

    def test_rejects_non_crash_shared_and_out_of_bounds_resources(self):
        original = make_bgd()
        examples = (
            (original, PEER), (original, 0x1800), (original, EVENT + 1),
            (original[:0x400], EVENT),
            (replace_fields(original, 0x198, "<I", 0x1000), EVENT),
            (replace_fields(original, 0x260, "<I", 51), EVENT),
            (replace_fields(original, 0x1000 + 0x3C8, "<I", EVENT), EVENT),
            (replace_fields(original, 0x1000 + 0x3D0, "<I", EVENT), EVENT),
            (replace_fields(original, 0x800 + 0x3C4, "<I", 0x4000), EVENT),
        )
        for data, offset in examples:
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                read_groups(data, offset)

    def test_unknown_auxiliary_repeated_unknown_and_out_of_section_records(self):
        original = make_bgd()
        changes = (
            (0x28, "<I", 7), (0x54, "<I", 0x800), (0x54, "<I", 0x40),
            (0x54 + 8, "<I", 4), (0x60, "<I", 0x120),
            (0x120 + 8, "<I", 150), (0x120, "<Q", encode_identifier("UNKNOWN")),
            (0x138, "<Q", encode_identifier(GROUPS[0][0])),
        )
        for rel, fmt, new_value in changes:
            with self.subTest(rel=rel), self.assertRaises(ValueError):
                reorder_groups(replace_fields(original, EVENT + rel, fmt, new_value), EVENT, GROUPS)

    def test_rejects_injection_omission_duplicate_and_cross_group_swap(self):
        invalid = (
            GROUPS[:-1], (("COMPCAR12",), *GROUPS[1:]),
            (("COMPCAR12", "COMPCAR12"), *GROUPS[1:]),
            (("COMPCAR12", "COMPCAR16"), *GROUPS[1:]),
            (("COMPCAR12", "HEVYCAR33"), ("COMPCAR14",), *GROUPS[2:]),
            ("COMPCAR14", *GROUPS[1:]),
        )
        for orders in invalid:
            with self.subTest(orders=orders), self.assertRaises(ValueError):
                reorder_groups(make_bgd(), EVENT, orders)


if __name__ == "__main__":
    unittest.main()
