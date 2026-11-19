"""Standalone ISO export tests. Fixtures are small generated sector images."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resources import native_iso as iso


def dual(value, size):
    return value.to_bytes(size, 'little') + value.to_bytes(size, 'big')


def record(name, extent, size, directory=False):
    out = bytearray(33 + len(name) + (not len(name) % 2))
    out[0] = len(out)
    out[2:10] = dual(extent, 4)
    out[10:18] = dual(size, 4)
    out[25] = 2 if directory else 0
    out[28:32] = dual(1, 2)
    out[32] = len(name)
    out[33:33 + len(name)] = name
    return out


def make_image():
    blocks = 32
    sector = iso.SECTOR
    data = bytearray(blocks * sector)
    root_entry = record(b'\0', 20, sector, True)
    root = (root_entry + record(b'\1', 20, sector, True) + record(b'TRACKS', 21, sector, True)
            + record(b'OTHER.BIN;1', 23, 9))
    tracks = (record(b'\0', 21, sector, True) + record(b'\1', 20, sector, True)
              + record(b'CRASH.RWS;1', 22, 62))
    primary = bytearray(sector)
    primary[:7] = b'\x01CD001\x01'
    primary[40:72] = b'SLUS_21050'.ljust(32, b' ')
    primary[80:88] = dual(blocks, 4)
    primary[120:128] = dual(1, 2) * 2
    primary[128:132] = dual(sector, 2)
    primary[132:140] = dual(10, 4)
    struct.pack_into('<I', primary, 140, 18)
    struct.pack_into('>I', primary, 148, 19)
    primary[156:156 + len(root_entry)] = root_entry
    for block, content in [(16, primary), (17, b'\xffCD001\x01'),
                           (20, root), (21, tracks), (22, bytes(range(62))), (23, b'untouched'),
                           (31, b'preserved trailing payload')]:
        data[block * sector:block * sector + len(content)] = content
    return data


class NativeIsoTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / 'original.iso'
        self.dest = self.root / 'edited.iso'
        self.image = make_image()
        self.source.write_bytes(self.image)
        self.changes = {'TRACKS/CRASH.RWS': (bytes(range(62)), bytes(range(62))[::-1])}

    def test_equal_size_export_preserves_all_other_bytes_and_verifies_hash(self):
        edits = dict(self.changes)
        edits['/other.bin;1'] = b'untouched', b'modifique'
        expected = self.image.copy()
        expected[22 * iso.SECTOR:22 * iso.SECTOR + 62] = self.changes['TRACKS/CRASH.RWS'][1]
        expected[23 * iso.SECTOR:23 * iso.SECTOR + 9] = b'modifique'
        with patch.object(iso, 'CHUNK', 17):
            result = iso.export_iso(self.source, self.dest, edits)
        self.assertEqual(self.source.read_bytes(), self.image)
        self.assertEqual(self.dest.read_bytes(), expected)
        self.assertEqual(result['sha256'], hashlib.sha256(expected).hexdigest())
        self.assertEqual(result['size'], len(expected))
        self.assertEqual(result['changed_files'], ['TRACKS/CRASH.RWS', 'OTHER.BIN'])
        self.assertEqual(set(self.root.iterdir()), {self.source, self.dest})

    def test_compare_whole_original_even_when_modified_byte_is_elsewhere(self):
        bad = bytearray(range(62))
        bad[-1] = 0
        edits = {'TRACKS/CRASH.RWS': (bytes(bad), b'X' + bytes(bad[1:]))}
        with patch.object(iso, 'CHUNK', 13), self.assertRaisesRegex(ValueError, 'difere'):
            iso.export_iso(self.source, self.dest, edits)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_match_length_and_normalized_unique_complete_names(self):
        old, new = self.changes['TRACKS/CRASH.RWS']
        for edits in [{}, {'CRASH.RWS': (old, new)}, {'TRACKS/CRASH.RWS': (old, new[:-1])},
                      {**self.changes, '/tracks/crash.rws;1': (old, new)}]:
            with self.subTest(edits=edits.keys()), self.assertRaises(ValueError):
                iso.export_iso(self.source, self.dest, edits)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_reject_corrupt_endianness_extent_and_overlapping_file(self):
        header = 16 * iso.SECTOR
        file_row = 21 * iso.SECTOR + 68
        for offset, value in [(header + 80, b'\x7f'), (header + 40, b'X'), (file_row + 2, dual(40, 4)),
                              (file_row + 2, dual(23, 4)), (file_row + 25, b'\x80'),
                              (file_row + 2, dual(18, 4))]:
            with self.subTest(offset=offset, value=value):
                data = self.image.copy()
                data[offset:offset + len(value)] = value
                self.source.write_bytes(data)
                with self.assertRaises(ValueError):
                    iso.export_iso(self.source, self.dest, self.changes)
                self.assertFalse(self.dest.exists())

    def test_preserves_existing_destination_and_original(self):
        self.dest.write_bytes(b'other contents')
        for target in [self.dest, self.source]:
            with self.assertRaises(FileExistsError):
                iso.export_iso(self.source, target, self.changes)
        self.assertEqual(self.source.read_bytes(), self.image)
        self.assertEqual(self.dest.read_bytes(), b'other contents')

    def test_competing_export_wins_without_overwrite(self):
        copy = iso._copy_overlay

        def competing_writer(*args):
            digest = copy(*args)
            self.dest.write_bytes(b'other export')
            return digest

        with patch.object(iso, '_copy_overlay', competing_writer), self.assertRaises(FileExistsError):
            iso.export_iso(self.source, self.dest, self.changes)
        self.assertEqual(self.dest.read_bytes(), b'other export')
        self.assertEqual(set(self.root.iterdir()), {self.source, self.dest})

    def test_no_partial_destination_on_write_or_readback_failure(self):
        for kwargs in [dict(side_effect=OSError('disk full')), dict(return_value='wrong hash')]:
            with self.subTest(kwargs=kwargs), patch.object(iso, '_copy_overlay', **kwargs):
                with self.assertRaises((OSError, ValueError)):
                    iso.export_iso(self.source, self.dest, self.changes)
            self.assertEqual(list(self.root.iterdir()), [self.source])


if __name__ == '__main__':
    unittest.main()
