"""Exercise the traffic-wave reader and writer with a generated track file."""
from dataclasses import replace
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.catalog import encode_identifier
from resources import traffic_waves as tw
from resources.crash_events import (
    CrashEvent, CRASHBREAKER_OFFSET, STAGE_KEYS, STAGE_STRIDE, STAGE_TABLE, THRESHOLDS_OFFSET,
    bgd_path, stagehed_path,
)
from resources.native_edit import prepare_changes
from resources.native_traffic import read_groups
import waves as waves_cli


EVENT = 0x2000
SIZE = 0x1000
GROUPS = (("COMPCAR14", "COMPCAR12"), ("HEVYCAR33",), ("HEVYCAR20",), (), ("HEVYCAR22",), ("HEVYCAR27",))


def vehicle(model, *, trailer=None, distance=0.0, time=0.0, kind=1, colour=0):
    return struct.pack("<QQff4B4x", encode_identifier(model), encode_identifier(trailer) if trailer else 0,
                       distance, time, kind, colour, 0, 0)


def make_bgd():
    """A track file with one Crash event: two sources, two waves, three lanes."""
    data = bytearray(0x6000)
    struct.pack_into("<I", data, 0, 9)
    struct.pack_into("<I", data, 0x198, 0x800)
    struct.pack_into("<3I", data, 0x260, 1, 0x800, 0x1000)
    struct.pack_into("<Q", data, 0x800 + 0x398, encode_identifier("1G0007EUC3V1"))
    struct.pack_into("<8I", data, 0x800 + 0x3BC, 0x800, 0x1000, SIZE, EVENT, 0x800, 0x4000, 0x800, 0x4800)
    block = bytearray(SIZE)
    struct.pack_into("<I", block, 0x28, 8)
    struct.pack_into("<2I", block, 0x2C, 0xC0, 0)          # unused table
    struct.pack_into("<2I", block, 0x34, 0xC0, 0)          # unused table
    struct.pack_into("<2I", block, 0x3C, 0xC0, 2)          # traffic sources
    struct.pack_into("<2I", block, 0x44, 0x100, 0)         # point table
    struct.pack_into("<2I", block, 0x4C, 0x100, 2)         # waves
    struct.pack_into("<4I", block, 0xC0, 0xE0, 0xE8, 2, 0)
    struct.pack_into("<4I", block, 0xD0, 0xF0, 0xF4, 1, 0)
    struct.pack_into("<2I", block, 0xE0, 3, 4)
    struct.pack_into("<I", block, 0xF0, 7)
    for wave, (headers, count, start) in enumerate(((0x200, 2, 0.0), (0x220, 1, 9.0))):
        base = 0x100 + wave * 0x58
        for offset in range(0, 0x38, 4):
            struct.pack_into("<I", block, base + offset, 0x1B0)
        struct.pack_into("<2I", block, base + 0x38, headers, count)
        struct.pack_into("<f", block, base + 0x4C, start)
    # Wave 2 also changes one lane speed, like the original events do.
    struct.pack_into("<4I", block, 0x158 + 0x04, 0x1C0, 0x1C4, 0x1C8, 0x1B0)
    struct.pack_into("<I", block, 0x158 + 0x40, 1)
    struct.pack_into("<f", block, 0x1C0, 50.0)
    struct.pack_into("<If4B", block, 0x200, 0x240, 100.0, 3, 2, 0, 0)
    struct.pack_into("<If4B", block, 0x20C, 0x2A0, 50.0, 1, 1, 1, 0)
    struct.pack_into("<If4B", block, 0x220, 0x2C0, 100.0, 2, 1, 0, 1)
    records = (vehicle("COMPCAR14", distance=150.0), vehicle("HEVYCAR33", distance=135.0, kind=2),
               vehicle("HEVYCAR22", trailer="HEVYCAR27", time=0.5, kind=4),
               vehicle("HEVYCAR20", distance=70.0, kind=5),
               vehicle("COMPCAR12", distance=120.0, colour=3), vehicle("COMPCAR14", time=9.5))
    block[0x240:0x300] = b"".join(records)
    cursor = 0x300
    for group in (0, 1, 3, 4, 2, 5):
        names = GROUPS[group]
        struct.pack_into("<3I", block, 0x54 + group * 12, cursor, len(names), len(names))
        for name in names:
            struct.pack_into("<Q4I", block, cursor, encode_identifier(name), 100, 0, 1, 0)
            cursor += 24
    data[EVENT:EVENT + SIZE] = block
    return bytes(data)


class TrafficWaveTests(unittest.TestCase):
    def setUp(self):
        self.bgd = make_bgd()
        self.schedule = tw.read_waves(self.bgd, EVENT)

    def test_reads_waves_lanes_and_vehicle_roles(self):
        s = self.schedule
        self.assertEqual([w.start for w in s.waves], [0.0, 9.0])
        first, second = s.waves
        self.assertEqual([(l.source, l.slot, l.initial, len(l.vehicles)) for l in first.lanes],
                         [(0, 0, 2, 3), (1, 0, 1, 1)])
        self.assertEqual(s.lane_path(first.lanes[0]), 3)
        self.assertEqual(s.lane_path(second.lanes[0]), 4)
        truck = first.lanes[0].vehicles[2]
        self.assertEqual((truck.model, truck.trailer, truck.time, truck.kind), ("HEVYCAR22", "HEVYCAR27", 0.5, 4))
        self.assertEqual(second.lanes[0].vehicles[0].variant, 3)
        self.assertEqual(tw.loaded_models(s)["trailers"], ["HEVYCAR27"])
        self.assertGreater(s.free_bytes, 3000)
        self.assertIn("Wave 2 (9 s): 1 placed, 1 released later, 1 lanes", tw.describe(s))

    def test_unchanged_schedule_round_trips_byte_for_byte(self):
        self.assertEqual(tw.write_waves(self.bgd, EVENT, self.schedule), self.bgd)

    def test_value_edits_are_written_in_place(self):
        lane = self.schedule.waves[0].lanes[0]
        vehicles = (replace(lane.vehicles[0], distance=160.0, variant=5),) + lane.vehicles[1:2] + (
            replace(lane.vehicles[2], time=1.25),)
        waves = (replace(self.schedule.waves[0], lanes=(replace(lane, entry=90.0, vehicles=vehicles),)
                         + self.schedule.waves[0].lanes[1:]), replace(self.schedule.waves[1], start=4.0))
        edited = tw.write_waves(self.bgd, EVENT, replace(self.schedule, waves=waves))
        changed = [i for i, (a, b) in enumerate(zip(self.bgd, edited)) if a != b]
        allowed = set()
        for offset, size in ((0x204, 4), (0x250, 4), (0x259, 1), (0x294, 4), (0x158 + 0x4C, 4)):
            allowed.update(range(EVENT + offset, EVENT + offset + size))
        self.assertTrue(changed and set(changed) <= allowed)
        again = tw.read_waves(edited, EVENT)
        self.assertEqual(again.waves[1].start, 4.0)
        self.assertEqual(again.waves[0].lanes[0].vehicles[2].time, 1.25)

    def test_adding_vehicles_relays_out_inside_the_block_only(self):
        lane = self.schedule.waves[0].lanes[0]
        extra = tuple(replace(lane.vehicles[2], time=2.0 + i) for i in range(4))
        added = (replace(lane, vehicles=lane.vehicles + extra),) + self.schedule.waves[0].lanes[1:]
        waves = (replace(self.schedule.waves[0], lanes=added),) + self.schedule.waves[1:]
        edited = tw.write_waves(self.bgd, EVENT, replace(self.schedule, waves=waves))
        self.assertEqual(len(edited), len(self.bgd))
        self.assertEqual(edited[:EVENT], self.bgd[:EVENT])
        self.assertEqual(edited[EVENT + SIZE:], self.bgd[EVENT + SIZE:])
        self.assertEqual(edited[EVENT:EVENT + 0x200], self.bgd[EVENT:EVENT + 0x200])
        self.assertEqual(read_groups(edited, EVENT), GROUPS)
        again = tw.read_waves(edited, EVENT)
        self.assertEqual(len(again.waves[0].lanes[0].vehicles), 7)
        self.assertEqual(again.waves[1], self.schedule.waves[1])
        self.assertEqual(tw.write_waves(edited, EVENT, again), edited)

    def test_adding_and_removing_waves(self):
        lane = tw.WaveLane(1, 0, 40.0, 1, (tw.WaveVehicle("HEVYCAR33", distance=60.0, kind=2),
                                             tw.WaveVehicle("COMPCAR12", time=20.0, kind=1, variant=7)))
        grown = replace(self.schedule, waves=self.schedule.waves + (tw.TrafficWave(15.0, (lane,)),))
        edited = tw.write_waves(self.bgd, EVENT, grown)
        again = tw.read_waves(edited, EVENT)
        self.assertEqual([w.start for w in again.waves], [0.0, 9.0, 15.0])
        self.assertEqual(again.waves[2].lanes[0].vehicles[1].variant, 7)
        # The moved wave table keeps the speed change of wave 2.
        sets = struct.unpack_from("<I", edited, EVENT + 0x4C)[0]
        self.assertEqual(struct.unpack_from("<I", edited, EVENT + sets + 0x58 + 0x40)[0], 1)
        shrunk = tw.write_waves(edited, EVENT, replace(again, waves=again.waves[:1]))
        self.assertEqual([w.start for w in tw.read_waves(shrunk, EVENT).waves], [0.0])

    def test_rejects_schedules_the_game_cannot_follow(self):
        s = self.schedule
        w0, w1 = s.waves
        lane = w0.lanes[0]
        bad = {
            "late first wave": (replace(w0, start=1.0), w1),
            "unsorted waves": (w0, replace(w1, start=0.0)),
            "unknown source": (w0, replace(w1, lanes=(replace(w1.lanes[0], source=9),))),
            "missing slot": (w0, replace(w1, lanes=(replace(w1.lanes[0], source=1, slot=1),))),
            "duplicate lane": (replace(w0, lanes=(lane, lane)), w1),
            "too many placed": (replace(w0, lanes=(replace(lane, initial=4),)), w1),
            "model not loaded": (replace(w0, lanes=(replace(lane, vehicles=(replace(lane.vehicles[0], model="COMPCAR11"),)
                                                       + lane.vehicles[1:]),)), w1),
            "wrong type": (replace(w0, lanes=(replace(lane, vehicles=(replace(lane.vehicles[0], kind=2),)
                                                 + lane.vehicles[1:]),)), w1),
            "truck without trailer": (replace(w0, lanes=(replace(lane, vehicles=lane.vehicles[:2] + (
                replace(lane.vehicles[2], trailer=None),)),)), w1),
            "colour": (replace(w0, lanes=(replace(lane, vehicles=(replace(lane.vehicles[0], variant=8),)
                                             + lane.vehicles[1:]),)), w1),
            "decreasing release": (replace(w0, lanes=(replace(lane, vehicles=lane.vehicles + (
                replace(lane.vehicles[2], time=0.1),)),)), w1),
        }
        for name, waves in bad.items():
            with self.subTest(name), self.assertRaises(ValueError):
                tw.write_waves(self.bgd, EVENT, replace(s, waves=waves))

    def test_reports_missing_space_without_partial_output(self):
        lane = self.schedule.waves[0].lanes[0]
        many = tuple(replace(lane.vehicles[2], time=1.0 + i) for i in range(200))
        waves = (replace(self.schedule.waves[0], lanes=(replace(lane, vehicles=lane.vehicles[:2] + many),)
                         + self.schedule.waves[0].lanes[1:]),) + self.schedule.waves[1:]
        with self.assertRaisesRegex(ValueError, "Not enough free space"):
            tw.write_waves(self.bgd, EVENT, replace(self.schedule, waves=waves))

    def test_json_round_trip_and_rejections(self):
        data = tw.waves_to_dict(self.schedule, event_key="1G0007EUC3V1")
        self.assertEqual(data["waves"][0]["lanes"][0]["vehicles"][2],
                         {"model": "HEVYCAR22", "colour": 0, "trailer": "HEVYCAR27", "enters_at_s": 0.5})
        rebuilt = tw.waves_from_dict(data, self.schedule)
        self.assertEqual(tw.write_waves(self.bgd, EVENT, rebuilt), self.bgd)
        data["waves"][0]["lanes"][0]["path"] = 99
        with self.assertRaisesRegex(ValueError, "path"):
            tw.waves_from_dict(data, self.schedule)
        with self.assertRaises(ValueError):
            tw.waves_from_dict({"format": "other"}, self.schedule)

    def test_vehicle_total_skips_timed_vehicles_a_later_wave_replaces(self):
        # Lane (0,0) of wave 1 has a truck at 0.5 s; wave 2 (9 s) replaces lane (0,1), not (0,0).
        self.assertEqual(tw.vehicle_total(self.schedule), 4 + 2)
        lane = self.schedule.waves[0].lanes[0]
        late = replace(lane, vehicles=lane.vehicles + (replace(lane.vehicles[2], time=20.0),))
        replaced = replace(self.schedule.waves[1], lanes=(replace(self.schedule.waves[1].lanes[0], slot=0),))
        schedule = replace(self.schedule, waves=(replace(self.schedule.waves[0], lanes=(late,) + self.schedule.waves[0].lanes[1:]),
                                                 replaced))
        self.assertEqual(tw.vehicle_total(schedule), 4 + 2)  # the 20 s truck never enters

    def test_density_warning_thresholds_never_block(self):
        self.assertEqual(tw.density_warning(50), "")
        self.assertIn("does not work properly", tw.density_warning(51))
        self.assertIn("crashed in tests", tw.density_warning(64))
        self.assertEqual(tw.density_warning(56, original=56), "")
        self.assertIn("above 50", tw.density_warning(57, original=56))

    def test_blocks_overlapping_or_unsupported_tables(self):
        overlap = bytearray(self.bgd)
        struct.pack_into("<I", overlap, EVENT + 0xC0, 0x240)  # a source path list inside vehicle data
        with self.assertRaisesRegex(ValueError, "overlaps"):
            tw.read_waves(bytes(overlap), EVENT)
        unused = bytearray(self.bgd)
        struct.pack_into("<I", unused, EVENT + 0x30, 1)
        with self.assertRaisesRegex(ValueError, "not covered"):
            tw.read_waves(bytes(unused), EVENT)
        version = bytearray(self.bgd)
        struct.pack_into("<I", version, EVENT + 0x28, 7)
        with self.assertRaisesRegex(ValueError, "version"):
            tw.read_waves(bytes(version), EVENT)


class LaneSpeedTests(unittest.TestCase):
    """Per-wave lane speeds: wave +0x04 floats, +0x08 sources, +0x0C slots, count +0x40."""

    def setUp(self):
        self.bgd = make_bgd()
        self.schedule = tw.read_waves(self.bgd, EVENT)

    def test_reads_the_speed_tables_of_each_wave(self):
        self.assertEqual(self.schedule.waves[0].speeds, ())
        self.assertEqual(self.schedule.waves[1].speeds, (tw.LaneSpeed(0, 0, 50.0),))
        self.assertEqual(tw.lane_speed(self.schedule, 1, 0, 0), (50.0, 1))
        self.assertEqual(tw.lane_speed(self.schedule, 0, 0, 0), (None, None))

    def test_changing_an_existing_speed_writes_only_its_float(self):
        edited = tw.with_lane_speed(self.schedule, 1, 0, 0, 65.0)
        out = tw.write_waves(self.bgd, EVENT, edited)
        changed = [i - EVENT for i in range(len(out)) if out[i] != self.bgd[i]]
        self.assertTrue(changed and all(0x1C0 <= i <= 0x1C3 for i in changed))
        self.assertEqual(tw.read_waves(out, EVENT).waves[1].speeds, (tw.LaneSpeed(0, 0, 65.0),))

    def test_a_new_speed_entry_is_laid_out_inside_the_block(self):
        edited = tw.with_lane_speed(self.schedule, 0, 1, 0, 40.0)
        out = tw.write_waves(self.bgd, EVENT, edited)
        again = tw.read_waves(out, EVENT)
        self.assertEqual(again.waves[0].speeds, (tw.LaneSpeed(1, 0, 40.0),))
        self.assertEqual(again.waves[1].speeds, self.schedule.waves[1].speeds)
        self.assertEqual(tw.lane_speed(again, 1, 1, 0), (40.0, 0))
        self.assertEqual(len(out), len(self.bgd))
        # Unchanged lanes and vehicles survive the new layout.
        self.assertEqual([w.lanes for w in again.waves], [w.lanes for w in self.schedule.waves])

    def test_a_later_wave_repeating_the_inherited_speed_drops_its_entry(self):
        first = tw.with_lane_speed(self.schedule, 0, 0, 0, 50.0)
        self.assertEqual(first.waves[0].speeds, (tw.LaneSpeed(0, 0, 50.0),))
        same = tw.with_lane_speed(first, 1, 0, 0, 50.0)
        self.assertEqual(same.waves[1].speeds, ())

    def test_invalid_speeds_are_rejected(self):
        with self.assertRaises(ValueError):
            tw.with_lane_speed(self.schedule, 1, 0, 0, 500.0)
        with self.assertRaises(ValueError):
            tw.with_lane_speed(self.schedule, 1, 0, 0, float("nan"))
        bad = replace(self.schedule, waves=(self.schedule.waves[0],
                                            replace(self.schedule.waves[1], speeds=(tw.LaneSpeed(9, 0, 30.0),))))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            tw.validate_waves(bad)
        twice = replace(self.schedule, waves=(self.schedule.waves[0], replace(
            self.schedule.waves[1], speeds=(tw.LaneSpeed(0, 0, 30.0), tw.LaneSpeed(0, 0, 40.0)))))
        with self.assertRaisesRegex(ValueError, "twice"):
            tw.validate_waves(twice)

    def test_json_carries_speeds_and_old_files_keep_them(self):
        edited = tw.with_lane_speed(self.schedule, 0, 1, 0, 40.0)
        data = tw.waves_to_dict(edited, event_key="1G0007EUC3V1")
        self.assertEqual(data["waves"][0]["lane_speeds"], [{"source": 1, "slot": 0, "path": 7, "speed": 40.0}])
        self.assertEqual(tw.waves_from_dict(data, self.schedule).waves, edited.waves)
        for wave in data["waves"]:
            del wave["lane_speeds"]
        self.assertEqual(tw.waves_from_dict(data, self.schedule).waves[1].speeds, self.schedule.waves[1].speeds)


class WaveExportTests(unittest.TestCase):
    """The waves edit travels through the same verified export path as goals and models."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        goals = (280000.0, 200000.0, 60000.0)
        self.event = CrashEvent("1G0007EUC3V1", "EU_C3_V1", "Example", 96, 0,
                                STAGE_TABLE, 0x800, EVENT, goals, goals, 8, 8)
        for path, offset, source in ((stagehed_path(self.root), STAGE_TABLE, bytes(STAGE_TABLE + STAGE_STRIDE)),
                                     (bgd_path(self.root, self.event.track), 0x800, make_bgd())):
            data = bytearray(source)
            struct.pack_into("<QQ", data, offset + STAGE_KEYS, encode_identifier(self.event.track),
                             encode_identifier(self.event.key))
            struct.pack_into("<3f", data, offset + THRESHOLDS_OFFSET, *goals)
            struct.pack_into("<I", data, offset + CRASHBREAKER_OFFSET, 8)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.track = bgd_path(self.root, self.event.track)
        self.schedule = tw.read_waves(self.track.read_bytes(), EVENT)

    def edited(self):
        wave = replace(self.schedule.waves[1], start=3.5)
        return replace(self.schedule, waves=(self.schedule.waves[0], wave))

    def test_prepare_changes_writes_waves_with_model_order(self):
        orders = (GROUPS[0][::-1], *GROUPS[1:])
        plan = prepare_changes(self.root, self.event, orders, waves=self.edited(),
                               expected_waves=self.schedule.waves)
        (rel, (old, new)), = plan.items()
        self.assertEqual(rel, "TRACKS/EU/C3_V1/GAMEDATA.BGD")
        self.assertEqual(old, self.track.read_bytes())
        self.assertEqual(tw.read_waves(new, EVENT).waves[1].start, 3.5)
        self.assertEqual(read_groups(new, EVENT), orders)
        self.track.write_bytes(new)  # the file changed after the schedule was read
        with self.assertRaisesRegex(ValueError, "waves changed on disk"):
            prepare_changes(self.root, self.event, orders, waves=self.edited(),
                            expected_waves=self.schedule.waves)

    def test_cli_plan_applies_documents_and_rejects_duplicates(self):
        document = tw.waves_to_dict(self.edited(), event_key=self.event.key)
        plan = waves_cli.plan_build(self.root, [self.event], [("a.json", document)])
        (_, (old, new)), = plan.items()
        self.assertEqual(old, self.track.read_bytes())
        self.assertEqual(tw.read_waves(new, EVENT).waves[1].start, 3.5)
        unchanged = tw.waves_to_dict(self.schedule, event_key=self.event.key)
        self.assertEqual(waves_cli.plan_build(self.root, [self.event], [("b.json", unchanged)]), {})
        with self.assertRaises(SystemExit):
            waves_cli.plan_build(self.root, [self.event], [("a.json", document), ("b.json", document)])
        with self.assertRaises(SystemExit):
            waves_cli.plan_build(self.root, [self.event], [("c.json", dict(document, event="1G9999EUC3V1"))])


if __name__ == "__main__":
    unittest.main()
