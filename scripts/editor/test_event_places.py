"""Level numbers and shared start places, on generated track files."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resources.crash_events import CrashEvent, bgd_path
from resources import event_places as ep


def event(key, track, order, descriptor):
    goals = (300.0, 200.0, 100.0)
    return CrashEvent(key, track, key, order, 0, 0, descriptor, 0x4000, goals, goals, 8, 8)


def track_file(starts):
    """A track file whose descriptors (0x800, 0x1000, ...) point at their own resource 0."""
    data = bytearray(0x8000)
    for index, start in enumerate(starts):
        descriptor = 0x800 * (index + 1)
        resource0 = 0x4000 + 0x800 * index
        struct.pack_into("<8I", data, descriptor + ep.RESOURCE_PAIRS,
                         0x800, resource0, 0x800, 0x6000, 0x800, 0x6800, 0x800, 0x7000)
        struct.pack_into("<3f", data, resource0 + ep.START_POSITION, *start)
    return bytes(data)


class EventPlacesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.events = [event("1G0001USC2V1", "US_C2_V1", 98, 0x800),
                       event("1G0002USC2V1", "US_C2_V1", 96, 0x1000),
                       event("1G0003USC2V1", "US_C2_V1", 97, 0x1800),
                       event("1G0004EUC3V1", "EU_C3_V1", 99, 0x800)]
        for track, starts in (("US_C2_V1", [(0, 0, 0), (12, 0, 5), (500, 0, 0)]), ("EU_C3_V1", [(1, 0, 1)])):
            path = bgd_path(self.root, track)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(track_file(starts))

    def test_level_numbers_follow_the_progression_order(self):
        numbers = ep.level_numbers(self.events)
        self.assertEqual(numbers, {"1G0002USC2V1": 1, "1G0003USC2V1": 2, "1G0001USC2V1": 3, "1G0004EUC3V1": 4})

    def test_close_starts_on_one_track_share_a_place(self):
        found = ep.places(self.root, self.events)
        self.assertEqual(found["1G0001USC2V1"]["shared_with"], ["1G0002USC2V1"])
        self.assertEqual(found["1G0002USC2V1"]["place"], found["1G0001USC2V1"]["place"])
        self.assertEqual(found["1G0003USC2V1"]["shared_with"], [])
        # Another track never shares a place, even at the same coordinates.
        self.assertEqual(found["1G0004EUC3V1"]["shared_with"], [])
        self.assertEqual(found["1G0001USC2V1"]["start"], (0.0, 0.0, 0.0))
        self.assertEqual(found["1G0001USC2V1"]["resources"][2], (0x800, 0x6800))

    def test_a_start_between_two_groups_joins_them(self):
        found = ep.places(self.root, self.events, radius=600)
        self.assertEqual(set(found["1G0003USC2V1"]["shared_with"]), {"1G0001USC2V1", "1G0002USC2V1"})

    def test_unreadable_tracks_are_left_out(self):
        missing = self.events + [event("1G0005ASC1V1", "AS_C1_V1", 100, 0x800)]
        found = ep.places(self.root, missing)
        self.assertNotIn("1G0005ASC1V1", found)
        with self.assertRaises(ValueError):
            ep.start_position(bytes(0x900), 0x0)


if __name__ == "__main__":
    unittest.main()
