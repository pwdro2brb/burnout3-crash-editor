"""Replacing an event's traffic models with models of the same group from other events."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.catalog import encode_identifier
from resources import model_swap as ms
from resources import traffic_waves as tw
from resources.native_edit import prepare_changes
from resources.native_traffic import read_groups
from test_traffic_waves import EVENT, GROUPS, WaveExportTests, make_bgd


class ModelSwapTests(unittest.TestCase):
    def setUp(self):
        self.bgd = make_bgd()

    def test_replacement_rewrites_group_and_wave_records_only(self):
        swaps = {"COMPCAR12": "COMPCAR18", "HEVYCAR27": "HEVYCAR24"}
        edited = ms.replace_models(self.bgd, EVENT, swaps)
        self.assertEqual(len(edited), len(self.bgd))
        groups = read_groups(edited, EVENT)
        self.assertEqual(groups[0], ("COMPCAR14", "COMPCAR18"))
        self.assertEqual(groups[5], ("HEVYCAR24",))
        waves = tw.read_waves(edited, EVENT)
        names = [(v.model, v.trailer) for w in waves.waves for l in w.lanes for v in l.vehicles]
        self.assertIn(("COMPCAR18", None), names)
        self.assertIn(("HEVYCAR22", "HEVYCAR24"), names)
        self.assertNotIn("COMPCAR12", {n for pair in names for n in pair})
        changed = [i for i in range(len(edited)) if edited[i] != self.bgd[i]]
        self.assertTrue(all(EVENT <= i < EVENT + 0x1000 for i in changed))
        # Swapping back restores the original file byte for byte.
        back = ms.replace_models(edited, EVENT, {v: k for k, v in swaps.items()})
        self.assertEqual(back, self.bgd)

    def test_rejects_other_groups_duplicates_unknown_and_unloaded_models(self):
        for swaps, message in (({"COMPCAR12": "HEVYCAR19"}, "same group"),
                               ({"COMPCAR12": "COMPCAR14"}, "only once"),
                               ({"COMPCAR12": "HEVYCAR28"}, "same group"),
                               ({"COMPCAR11": "COMPCAR18"}, "not loaded"),
                               ({"COMPCAR12": "COMPCAR18", "COMPCAR14": "COMPCAR18"}, "only once")):
            with self.subTest(swaps=swaps):
                with self.assertRaisesRegex(ValueError, message):
                    ms.replace_models(self.bgd, EVENT, swaps)

    def test_candidates_exclude_models_already_loaded(self):
        groups = read_groups(self.bgd, EVENT)
        options = ms.candidates_for(groups, "COMPCAR12")
        self.assertNotIn("COMPCAR14", options)
        self.assertIn("COMPCAR18", options)
        self.assertEqual(ms.candidates_for(groups, "HEVYCAR22"), ("HEVYCAR23",))
        with self.assertRaises(ValueError):
            ms.candidates_for(groups, "COMPCAR11")

    def test_rename_schedule_matches_the_written_file(self):
        swaps = {"HEVYCAR33": "HEVYCAR31"}
        schedule = tw.read_waves(self.bgd, EVENT)
        renamed = ms.rename_schedule(schedule, swaps)
        written = tw.read_waves(ms.replace_models(self.bgd, EVENT, swaps), EVENT)
        self.assertEqual(renamed.waves, written.waves)
        self.assertEqual(renamed.models, written.models)

    def test_record_offsets_cover_every_wave_vehicle(self):
        offsets = tw.vehicle_record_offsets(self.bgd, EVENT)
        self.assertEqual(len(offsets), 6)
        first = struct.unpack_from("<Q", self.bgd, offsets[0])[0]
        self.assertEqual(first, encode_identifier("COMPCAR14"))


class ModelAdditionTests(unittest.TestCase):
    def setUp(self):
        self.bgd = make_bgd()

    def test_added_models_move_the_groups_to_the_free_tail_only(self):
        edited = ms.add_models(self.bgd, EVENT, ["COMPCAR18", "HEVYCAR21"])
        groups = read_groups(edited, EVENT)
        self.assertEqual(groups[0], ("COMPCAR14", "COMPCAR12", "COMPCAR18"))
        self.assertEqual(groups[2], ("HEVYCAR20", "HEVYCAR21"))
        self.assertEqual(groups[1], GROUPS[1])
        self.assertEqual(tw.read_waves(edited, EVENT).waves, tw.read_waves(self.bgd, EVENT).waves)
        changed = [i - EVENT for i in range(len(edited)) if edited[i] != self.bgd[i]]
        # Only the group headers (0x54..0x9C) and the new arrays in the old zero tail change.
        old_end = max(s + 24 * c for s, c, _cap in (struct.unpack_from("<3I", self.bgd, EVENT + 0x54 + 12 * g)
                                                     for g in range(6)))
        self.assertTrue(all(0x54 <= i < 0x9C or i >= old_end for i in changed))
        self.assertTrue(all(b == 0 for b in self.bgd[EVENT + old_end:EVENT + 0x1000]))

    def test_additions_respect_groups_limits_and_duplicates(self):
        groups = read_groups(self.bgd, EVENT)
        self.assertIsNone(ms.can_add(groups, "COMPCAR18"))
        self.assertIn("already loaded", ms.can_add(groups, "COMPCAR14"))
        self.assertIn("not a traffic model", ms.can_add(groups, "HEVYCAR28"))
        full = (tuple(ms.CANDIDATES[0][:6]),) + groups[1:]  # 6 cars + 4 others = 10, plus 2 trams
        self.assertIn("at most 12", ms.can_add(full, "COMPCAR19", trams=("TSPCCAR1", "TSPCCAR2")))
        with self.assertRaises(ValueError):
            ms.add_models(self.bgd, EVENT, ["COMPCAR14"])
        self.assertEqual(ms.group_of("HEVYCAR29"), 5)

    def test_size_budget_uses_the_model_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("COMPCAR14", "COMPCAR12", "HEVYCAR33", "HEVYCAR20", "HEVYCAR22", "HEVYCAR27", "COMPCAR18"):
                target = ms.model_file(root, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bytes(400_000))
            groups = read_groups(self.bgd, EVENT)
            self.assertEqual(ms.budget(groups, root=root)["bytes"], 6 * 400_000)
            self.assertIn("more than any original event", ms.can_add(groups, "COMPCAR18", root=root))
            self.assertIn("not found", ms.can_add(groups, "COMPCAR19", root=root))


class ModelSwapExportTests(WaveExportTests):
    def test_prepare_changes_applies_swaps_then_order_and_waves(self):
        swaps = {"COMPCAR12": "COMPCAR18"}
        orders = (("COMPCAR18", "COMPCAR14"), *GROUPS[1:])
        waves = ms.rename_schedule(self.edited(), swaps)
        plan = prepare_changes(self.root, self.event, orders, expected_orders=GROUPS, model_swaps=swaps,
                               waves=waves, expected_waves=self.schedule.waves)
        (_rel, (_old, new)), = plan.items()
        self.assertEqual(read_groups(new, EVENT), orders)
        self.assertEqual(tw.read_waves(new, EVENT).waves[1].start, 3.5)

    def test_prepare_changes_adds_a_model_used_by_the_waves(self):
        added = ms.add_models(self.track.read_bytes(), EVENT, ["COMPCAR18"])
        schedule = tw.read_waves(added, EVENT)
        lane = schedule.waves[0].lanes[0]
        from dataclasses import replace
        lane = replace(lane, vehicles=(replace(lane.vehicles[0], model="COMPCAR18"),) + lane.vehicles[1:])
        waves = replace(schedule, waves=(replace(schedule.waves[0], lanes=(lane,) + schedule.waves[0].lanes[1:]),)
                        + schedule.waves[1:])
        orders = (("COMPCAR14", "COMPCAR12", "COMPCAR18"), *GROUPS[1:])
        plan = prepare_changes(self.root, self.event, orders, expected_orders=GROUPS, model_additions=["COMPCAR18"],
                               waves=waves, expected_waves=self.schedule.waves)
        (_rel, (_old, new)), = plan.items()
        self.assertEqual(read_groups(new, EVENT), orders)
        self.assertEqual(tw.read_waves(new, EVENT).waves[0].lanes[0].vehicles[0].model, "COMPCAR18")

    def test_prepare_changes_with_only_a_swap_is_a_change(self):
        plan = prepare_changes(self.root, self.event,
                               (("COMPCAR14", "COMPCAR18"), *GROUPS[1:]), model_swaps={"COMPCAR12": "COMPCAR18"})
        self.assertEqual(len(plan), 1)


if __name__ == "__main__":
    unittest.main()
