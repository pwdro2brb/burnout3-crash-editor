"""Read-only native traffic geometry tests using generated track files."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resources.native_roads import read_roads


def make_track(start=2048, controls=3):
    section = bytearray(2048)
    struct.pack_into('<3I', section, 0, 12, 0x100, 1)
    struct.pack_into('<5I', section, 12, 0x20, 0x80, 0x90, 0, controls)
    for i in range(controls):
        struct.pack_into('<2H', section, 0x20 + 4 * i, i * 2, i * 2 + 1)
        for side, x in enumerate((-5, 5)):
            struct.pack_into('<3f', section, 0x100 + 16 * (i * 2 + side), x, 1, i * 60)
    header = bytearray(start)
    header[:8] = bytes.fromhex('0900000078013200')
    struct.pack_into('<2I', header, 0x270, start, start + len(section))
    return header + section


class NativeRoadsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'GAMEDATA.BGD'

    def parse(self, data, **options):
        self.path.write_bytes(data)
        return read_roads(self.path, **options)

    def test_native_ids_and_cubic_spline_boundaries(self):
        data = make_track()
        result = self.parse(data)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(result['control_pair_count'], 3)
        self.assertEqual(result['path_count'], 1)
        road = result['paths'][0]
        self.assertEqual((road['id'], road['count'], road['sample_count']), (0, 3, 3))
        for side, x in [('left', -5), ('center', 0), ('right', 5)]:
            for point, z in zip(road[side], [10, 60, 110]):
                for actual, expected in zip(point, (x, 1, z)):
                    self.assertAlmostEqual(actual, expected)

    def test_digest_tracks_section_contents_across_relocations(self):
        first = self.parse(make_track())
        second = self.parse(make_track(start=4096), max_samples_per_path=2)
        self.assertEqual(first['section_sha256'], second['section_sha256'])
        self.assertNotEqual(first['section_offset'], second['section_offset'])
        self.assertEqual(second['paths'][0]['sample_count'], 2)
        self.assertEqual(first['paths'][0]['left'][::2], second['paths'][0]['left'])
        data = make_track()
        struct.pack_into('<f', data, 2048 + 0x100, -4)
        self.assertNotEqual(self.parse(data)['section_sha256'], first['section_sha256'])

    def test_bad_header_section_range_and_truncated_file(self):
        for field, value in [(0, 0), (0x270, 2049), (0x274, 2048), (0x274, 8192)]:
            with self.subTest(field=field, value=value):
                data = make_track()
                struct.pack_into('<I', data, field, value)
                with self.assertRaises(ValueError):
                    self.parse(data)
        with self.assertRaises(ValueError):
            self.parse(b'')

    def test_reject_bad_descriptor_ranges_or_invalid_vertex_index(self):
        for field, value in [(0, 0), (4, 16), (8, 0), (12, 28), (16, 32),
                             (20, 8192), (24, 1), (28, 0), (32, 0xffff)]:
            with self.subTest(field=field, value=value):
                data = make_track()
                struct.pack_into('<I', data, 2048 + field, value)
                with self.assertRaises(ValueError):
                    self.parse(data)

    def test_reject_nonfinite_coordinates_even_when_preview_skips_them(self):
        data = make_track(controls=10)
        struct.pack_into('<f', data, 2048 + 0x100 + 16 * 9, float('nan'))
        with self.assertRaisesRegex(ValueError, 'não finita'):
            self.parse(data, max_samples_per_path=2)

    def test_sampling_budget_must_be_bounded_integer(self):
        for value in (True, 1, 1.5, 257):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(make_track(), max_samples_per_path=value)


if __name__ == '__main__':
    unittest.main()
