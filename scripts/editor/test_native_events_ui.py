"""Exercise the native-event Tk controls with hidden windows and generated inputs."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import gui, native_events_ui as ui
from resources.crash_events import CrashEvent, bgd_path
from resources.native_traffic import read_groups


GROUPS = (("COMPCAR14", "COMPCAR12"), ("HEVYCAR33",), (), (), (), ())


class NativeEventGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")
        cls.root.withdraw()
        cls.addClassCleanup(cls.root.destroy)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.game = Path(folder.name)
        self.a = CrashEvent("1G0007EUC3V1", "EU_C3_V1", "Grand Slam", 97, 0, 0, 0,
                            2048, (300, 200, 100), (300, 200, 100), 10, 10)
        self.b = CrashEvent("1G0003USC2V1", "US_C2_V1", "Other", 96, 1, 0, 0,
                            4096, (700, 400, 100), (800, 400, 100), 9, 8)
        for event in (self.a, self.b):
            path = bgd_path(self.game, event.track)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"track")
        self.active = None
        self.catalog = self.replace(ui, "load_crash_events", return_value=(self.b, self.a))
        self.groups = self.replace(ui, "read_groups", return_value=GROUPS)
        self.replace(ui, "read_roads", return_value={
            "path_count": 1, "paths": [{"center": [[0, 0, 0], [20, 0, 12]]}]})
        self.error = self.replace(ui.messagebox, "showerror")
        self.info = self.replace(ui.messagebox, "showinfo")
        self.confirm = self.replace(ui.messagebox, "askyesno", return_value=False)
        with patch.object(Path, "is_file", return_value=False):
            self.window = ui.NativeEventsWindow(self.root, lambda: self.active)
        self.window.withdraw()
        self.addCleanup(self.clean_window)
        self.window.open_game(self.game)
        self.finish_job()

    def replace(self, target, name, **options):
        setting = patch.object(target, name, **options)
        self.addCleanup(setting.stop)
        return setting.start()

    def clean_window(self):
        if self.window.winfo_exists():
            self.window.worker.shutdown()
            self.window.destroy()
        self.root.update()

    def finish_job(self):
        end = time.monotonic() + 5
        while self.window.job is not None and time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)
        self.assertIsNone(self.window.job)
        self.root.update()

    def swap_first_group(self):
        self.window.models.selection_set("0/0", "0/1")
        self.window.swap()

    def test_offline_browsing_locate_and_divergent_thresholds(self):
        window = self.window
        self.assertEqual(window.event, self.a)
        self.groups.assert_called_once()  # Initial selection only decodes its own track.
        self.assertEqual(window.fields[0].get(), "300")
        self.assertEqual(window.crash_count.get(), "10")
        self.assertEqual(len(window.models.get_children()), 3)
        window.locate()
        self.assertIn("paused", window.status.get())
        window.query.set("Grand")
        self.active = {"event_key": self.b.key}
        window.locate()
        self.assertEqual(window.event, self.b)
        self.assertEqual(window.query.get(), "")
        self.assertEqual(str(window.fields[0].cget("state")), "readonly")
        self.assertEqual(window.fields[0].get(), "700")
        self.assertEqual(str(window.crash_count.cget("state")), "readonly")
        self.assertIn("differ", window.limit_note.get())
        self.error.assert_not_called()

    def test_filter_remembers_model_order_and_thresholds(self):
        window = self.window
        window.models.selection_set("0/0", "1/0")
        window.swap()
        self.assertEqual(window.orders, GROUPS)
        self.swap_first_group()
        window.fields[0].delete(0, "end")
        window.fields[0].insert(0, "425")
        window.crash_count.delete(0, "end")
        window.crash_count.insert(0, "12")
        window.query.set("no such event")
        self.assertIsNone(window.event)
        self.assertFalse(window.models.get_children())
        window.query.set("grand")
        self.assertEqual(window.orders[0], ("COMPCAR12", "COMPCAR14"))
        self.assertEqual(window.fields[0].get(), "425")
        self.assertEqual(window.crash_count.get(), "12")
        self.assertFalse(window.close())
        self.assertTrue(window.winfo_exists())
        self.confirm.assert_called_once()

    def test_export_buttons_use_snapshot_and_recognize_exported_edit(self):
        window = self.window
        self.swap_first_group()
        expected = (("COMPCAR12", "COMPCAR14"), *GROUPS[1:])
        changes = {"DATA/STAGEHED.BIN": (b"old", b"new")}
        prepared = self.replace(ui, "prepare_changes", return_value=changes)
        written = self.replace(ui, "export_resources", return_value=self.game / "result")
        self.replace(ui.filedialog, "askdirectory", return_value=str(self.game))
        window.export(False)
        self.finish_job()
        prepared.assert_called_once_with(self.game, self.a, expected, None, expected_orders=GROUPS,
                                         crashbreaker_wrecks=None)
        written.assert_called_once_with(self.game, self.game, self.a, changes)
        self.assertIn("result", window.status.get())
        self.replace(ui.filedialog, "askopenfilename", return_value=str(self.game / "source.iso"))
        self.replace(ui.filedialog, "asksaveasfilename", return_value=str(self.game / "dest.iso"))
        iso = self.replace(ui, "export_iso")
        window.export(True)
        window.focus_event(self.b.key)  # In-flight export belongs to the event clicked.
        self.finish_job()
        iso.assert_called_once()
        self.assertEqual(iso.call_args.args, (self.game / "source.iso", self.game / "dest.iso", changes))
        self.assertTrue(callable(iso.call_args.kwargs["progress"]))
        self.assertIn("Grand Slam", window.status.get())
        self.assertTrue(window.close())
        self.confirm.assert_not_called()

    def test_one_export_can_hold_every_edited_event(self):
        window = self.window
        self.swap_first_group()                      # edit Grand Slam
        window.focus_event(self.b.key)
        self.swap_first_group()                      # edit the other event too
        changes = {"DATA/STAGEHED.BIN": (b"old", b"new")}
        many = self.replace(ui, "prepare_many", return_value=changes)
        single = self.replace(ui, "prepare_changes", return_value=changes)
        written = self.replace(ui, "export_resources", return_value=self.game / "result")
        self.replace(ui.filedialog, "askdirectory", return_value=str(self.game))
        self.confirm.return_value = True
        window.export(False)
        self.finish_job()
        single.assert_not_called()
        edits = many.call_args.args[1]
        self.assertEqual({edit[0].key for edit in edits}, {self.a.key, self.b.key})
        self.assertEqual([e.key for e in written.call_args.args[2]], [self.b.key, self.a.key])
        self.assertIn("Grand Slam", window.status.get())
        self.confirm.return_value = False
        self.assertTrue(window.close())          # both drafts count as exported now

    def test_declining_the_combined_export_keeps_the_open_event_only(self):
        window = self.window
        self.swap_first_group()
        window.focus_event(self.b.key)
        self.swap_first_group()
        changes = {"DATA/STAGEHED.BIN": (b"old", b"new")}
        single = self.replace(ui, "prepare_changes", return_value=changes)
        many = self.replace(ui, "prepare_many", return_value=changes)
        self.replace(ui, "export_resources", return_value=self.game / "result")
        self.replace(ui.filedialog, "askdirectory", return_value=str(self.game))
        self.confirm.return_value = False
        window.export(False)
        self.finish_job()
        many.assert_not_called()
        self.assertEqual(single.call_args.args[1], self.b)

    def test_crashbreaker_alone_can_be_exported_within_observed_range(self):
        folder = self.replace(ui.filedialog, "askdirectory", return_value=str(self.game))
        window = self.window
        window.crash_count.delete(0, "end")
        window.crash_count.insert(0, "16")
        window.export(False)
        self.assertIn("6 to 15", window.status.get())
        folder.assert_not_called()
        window.crash_count.delete(0, "end")
        window.crash_count.insert(0, "6")
        prepared = self.replace(ui, "prepare_changes", return_value={})
        self.replace(ui, "export_resources", return_value=self.game / "result")
        window.export(False)
        self.finish_job()
        prepared.assert_called_once_with(self.game, self.a, GROUPS, None, expected_orders=GROUPS,
                                         crashbreaker_wrecks=6)
        window.close()
        self.confirm.assert_not_called()

    def test_unchanged_invalid_and_failed_exports_retain_current_draft(self):
        dialog = self.replace(ui.filedialog, "askdirectory", return_value=str(self.game))
        window = self.window
        window.export(False)
        self.assertIn("Change a model", window.status.get())
        window.fields[0].insert("end", "x")
        window.export(False)
        self.assertIn("whole numbers", window.status.get())
        dialog.assert_not_called()
        window.fields[0].delete(0, "end")
        window.fields[0].insert(0, "450")
        self.replace(ui, "prepare_changes", side_effect=ValueError("Track changed"))
        window.export(False)
        self.finish_job()
        self.assertEqual(window.status.get(), "Track changed")
        self.assertEqual(window.fields[0].get(), "450")
        self.error.assert_called_once()
        self.assertFalse(window.close())

    def test_opening_a_folder_preserves_draft_if_loading_or_confirmation_fails(self):
        self.swap_first_group()
        self.catalog.side_effect = ValueError("Other region")
        self.window.open_game(self.game)
        self.finish_job()
        self.assertIn("region", self.window.status.get())
        self.confirm.assert_not_called()
        self.catalog.side_effect = None
        self.window.open_game(self.game)
        self.finish_job()
        self.assertEqual(self.window.orders[0], ("COMPCAR12", "COMPCAR14"))
        self.confirm.assert_called_once()
        self.assertIn("were kept", self.window.status.get())

    def test_project_entry_works_disconnected_and_observes_pause_state(self):
        app = gui.EditorApp.__new__(gui.EditorApp)
        app.root = self.root
        app.connected = app.profile_valid = app.core_paused = False
        app.native_identity = {"event_key": self.a.key}
        app.closed = app.busy = app.pending = False
        app._submit = Mock()
        app.controller = Mock()
        with patch.object(ui, "NativeEventsWindow", return_value=self.window) as ctor:
            app.open_native_events()
            current = ctor.call_args.args[1]
        self.assertIsNone(current())
        app.connected = app.profile_valid = True
        self.assertIsNone(current())
        app.core_paused = True
        self.assertEqual(current(), app.native_identity)
        self.swap_first_group()
        app.close()
        app._submit.assert_not_called()
        self.assertTrue(self.window.winfo_exists())


class NativeWaveTabTests(NativeEventGuiTests):
    """The Traffic waves tab edits a draft schedule and exports it with the other fields."""

    def setUp(self):
        from editor import test_traffic_waves as synthetic
        from resources import traffic_waves as tw
        self.tw = tw
        self.bgd = synthetic.make_bgd()
        self.base = tw.read_waves(self.bgd, synthetic.EVENT)
        self.offset = synthetic.EVENT
        real_write = tw.write_waves
        patch.object(ui, "read_waves", return_value=self.base).start()
        patch.object(ui, "write_waves", side_effect=lambda _d, _o, s: real_write(self.bgd, self.offset, s)).start()
        self.addCleanup(patch.stopall)
        super().setUp()

    def pick(self, iid):
        self.window.wave_tree.selection_set(iid)
        self.root.update()
        self.window.wave_selected()

    def test_wave_edits_validate_and_export_with_the_draft(self):
        window = self.window
        self.assertEqual(window.wave_tree.item("w1", "text"), "Wave 2")
        self.pick("w1")
        window.wave_start.delete(0, "end")
        window.wave_start.insert(0, "0")
        window.apply_wave()
        self.assertIn("increase", window.status.get())       # rejected, draft unchanged
        self.assertEqual(window.schedule, self.base)
        window.wave_start.delete(0, "end")
        window.wave_start.insert(0, "4")
        window.apply_wave()
        self.assertEqual(window.schedule.waves[1].start, 4.0)
        self.pick("w0/l0/v0")
        window.duplicate_vehicle()
        lane = window.schedule.waves[0].lanes[0]
        self.assertEqual((lane.initial, len(lane.vehicles)), (3, 4))
        self.assertEqual(lane.vehicles[1].distance, 135.0)
        self.pick("w0/l0/v2")  # a placed van becomes a timed vehicle
        window.vehicle_role.set("released")
        window.vehicle_value.delete(0, "end")
        window.vehicle_value.insert(0, "0.25")
        window.apply_vehicle()
        lane = window.schedule.waves[0].lanes[0]
        self.assertEqual(lane.initial, 2)
        self.assertEqual([(v.model, round(v.time, 2)) for v in lane.vehicles[lane.initial:]],
                         [("HEVYCAR33", 0.25), ("HEVYCAR22", 0.5)])
        window.add_wave()
        self.assertEqual(len(window.schedule.waves), 3)
        self.pick("w2")
        window.add_lane()
        self.assertEqual(len(window.schedule.waves[2].lanes), 1)
        prepared = self.replace(ui, "prepare_changes", return_value={"x": (b"a", b"b")})
        self.replace(ui, "export_resources", return_value=self.game / "result")
        self.replace(ui.filedialog, "askdirectory", return_value=str(self.game))
        window.export(False)
        self.finish_job()
        kwargs = prepared.call_args.kwargs
        self.assertEqual(kwargs["waves"], window.schedule)
        self.assertEqual(kwargs["expected_waves"], self.base.waves)
        self.assertTrue(window.close())
        self.confirm.assert_not_called()

    def test_main_window_buttons_open_the_waves_tab(self):
        self.window.tabs.select(0)
        self.window.show_waves()
        self.assertEqual(self.window.tabs.select(), str(self.window.waves_page))
        self.assertIn("up to 6 on the road", self.window.wave_note.get())
        self.assertEqual(self.window.wave_warning.cget("text"), "")

    def test_waves_json_round_trip_through_the_tab(self):
        window = self.window
        target = self.game / "grand.waves.json"
        self.replace(ui.filedialog, "asksaveasfilename", return_value=str(target))
        window.export_waves_json()
        data = __import__("json").loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["event"], self.a.key)
        data["waves"][1]["start_s"] = 6.5
        target.write_text(__import__("json").dumps(data), encoding="utf-8")
        self.replace(ui.filedialog, "askopenfilename", return_value=str(target))
        window.import_waves_json()
        self.assertEqual(window.schedule.waves[1].start, 6.5)
        data["event"] = self.b.key
        target.write_text(__import__("json").dumps(data), encoding="utf-8")
        window.import_waves_json()
        self.assertIn("belongs to event", window.status.get())

    def test_add_several_fills_a_lane_on_the_road_and_later(self):
        window = self.window
        self.pick("w0/l0")
        window.quick_model.set("COMPCAR12")
        window.quick_count.set("2")
        window.quick_role.set("placed")
        _set = ui._set
        _set(window.quick_spacing, "20")
        window.add_vehicles_to_lane()
        lane = window.schedule.waves[0].lanes[0]
        placed = [round(v.distance, 1) for v in lane.vehicles[:lane.initial]]
        self.assertEqual(placed[-2:], [115.0, 95.0])
        window.quick_role.set("released")
        _set(window.quick_start, "2")
        _set(window.quick_every, "0.5")
        window.add_vehicles_to_lane()
        lane = window.schedule.waves[0].lanes[0]
        times = [round(v.time, 2) for v in lane.vehicles[lane.initial:]]
        self.assertEqual(times, [0.5, 2.0, 2.5])
        self.assertIn("drive in from 2 s", window.status.get())

    def test_inspector_shows_only_the_selected_level(self):
        window = self.window
        self.pick("w1")
        self.assertTrue(window.wave_panel.winfo_ismapped() or window.wave_panel.grid_info())
        self.assertFalse(window.vehicle_panel.grid_info())
        self.pick("w0/l0/v0")
        self.assertTrue(window.vehicle_panel.grid_info())
        self.assertFalse(window.lane_panel.grid_info())
        self.assertIn("On the road", window.inspector_text.get())


class NativeModelEditTests(unittest.TestCase):
    """Replacing and adding models and lane speeds, on a generated track file (no patched readers)."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")
        cls.root.withdraw()
        cls.addClassCleanup(cls.root.destroy)

    def setUp(self):
        from editor import test_traffic_waves as synthetic
        from resources import traffic_waves as tw
        self.tw = tw
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.game = Path(folder.name)
        self.event = CrashEvent("1G0007EUC3V1", "EU_C3_V1", "Grand Slam", 97, 0, 0, 0,
                                synthetic.EVENT, (300, 200, 100), (300, 200, 100), 10, 10)
        path = bgd_path(self.game, self.event.track)
        path.parent.mkdir(parents=True)
        self.bgd = synthetic.make_bgd()
        path.write_bytes(self.bgd)
        self.base = tw.read_waves(self.bgd, synthetic.EVENT)
        for target, name, options in ((ui, "load_crash_events", dict(return_value=(self.event,))),
                                      (ui, "read_roads", dict(return_value={"path_count": 1, "paths": [
                                          {"center": [[0, 0, 0], [20, 0, 12]]}]})),
                                      (ui.messagebox, "showerror", {}), (ui.messagebox, "showinfo", {})):
            setting = patch.object(target, name, **options)
            self.addCleanup(setting.stop)
            setting.start()
        self.answer = True
        setting = patch.object(ui.messagebox, "askyesno", side_effect=lambda *a, **k: self.answer)
        self.addCleanup(setting.stop)
        setting.start()
        with patch.object(Path, "is_file", return_value=False):
            self.window = ui.NativeEventsWindow(self.root, lambda: None)
        self.window.withdraw()
        self.addCleanup(self.clean)
        self.window.open_game(self.game)
        self.wait_job()

    def wait_job(self):
        end = time.monotonic() + 5
        while self.window.job is not None and time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)
        self.root.update()

    def clean(self):
        if self.window.winfo_exists():
            self.window.worker.shutdown()
            self.window.destroy()
        self.root.update()

    def pick(self, iid):
        self.window.wave_tree.selection_set(iid)
        self.root.update()
        self.window.wave_selected()

    def replace_second_car(self, target):
        window = self.window
        window.models.selection_set("0/1")
        window.model_selected()
        window.replacement.set(next(o for o in window.replacement.cget("values") if o.startswith(target)))
        window.replace_model()

    def export_kwargs(self):
        with patch.object(ui, "prepare_changes", return_value={"x": (b"a", b"b")}) as call, \
                patch.object(ui, "export_resources", return_value=self.game / "result"), \
                patch.object(ui.filedialog, "askdirectory", return_value=str(self.game)):
            self.window.export(False)
            self.wait_job()
            return call.call_args.kwargs

    def test_replace_model_updates_groups_waves_and_export(self):
        window = self.window
        self.replace_second_car("COMPCAR18")
        self.assertEqual(window.orders[0], ("COMPCAR14", "COMPCAR18"))
        names = {v.model for w in window.schedule.waves for l in w.lanes for v in l.vehicles}
        self.assertIn("COMPCAR18", names)
        self.assertNotIn("COMPCAR12", names)
        self.assertIn("replaces COMPCAR12", window.models.item("0/1", "values"))
        kwargs = self.export_kwargs()
        self.assertEqual(kwargs["model_swaps"], {"COMPCAR12": "COMPCAR18"})
        self.assertNotIn("waves", kwargs)
        self.replace_second_car("COMPCAR12")  # back to the original removes the change
        self.assertEqual(window.swaps, ())
        self.assertEqual(window.schedule.waves, self.base.waves)

    def test_wave_edit_after_a_replacement_uses_the_new_name(self):
        window = self.window
        self.replace_second_car("COMPCAR18")
        self.pick("w0/l0")
        window.quick_model.set("COMPCAR18")
        window.quick_count.set("1")
        window.add_vehicles_to_lane()
        lane = window.schedule.waves[0].lanes[0]
        self.assertEqual(lane.vehicles[lane.initial - 1].model, "COMPCAR18")

    def test_vehicle_can_use_a_model_the_event_did_not_load(self):
        window = self.window
        self.pick("w0/l0/v0")
        labels = window.vehicle_model.cget("values")
        self.assertTrue(any(l.startswith("COMPCAR18") and l.endswith(ui.NOT_LOADED) for l in labels))
        window.vehicle_model.set(next(l for l in labels if l.startswith("COMPCAR18")))
        window.apply_vehicle()
        self.assertEqual(window.schedule.waves[0].lanes[0].vehicles[0].model, "COMPCAR18")
        self.assertIn("COMPCAR18", window.additions)
        self.assertEqual(window.orders[0], ("COMPCAR14", "COMPCAR12", "COMPCAR18"))
        self.assertIn("added", window.models.item("0/2", "values")[4])
        kwargs = self.export_kwargs()
        self.assertEqual(kwargs["model_additions"], ["COMPCAR18"])
        self.assertEqual(kwargs["waves"].waves[0].lanes[0].vehicles[0].model, "COMPCAR18")
        # The writers accept the same draft: add the model, then write the waves.
        from resources.model_swap import add_models
        offset = self.event.event_offset
        new = self.tw.write_waves(add_models(self.bgd, offset, kwargs["model_additions"]), offset, kwargs["waves"])
        self.assertEqual(read_groups(new, offset)[0], ("COMPCAR14", "COMPCAR12", "COMPCAR18"))
        self.assertEqual(self.tw.read_waves(new, offset).waves[0].lanes[0].vehicles[0].model, "COMPCAR18")

    def test_declining_the_addition_keeps_the_vehicle(self):
        window = self.window
        self.answer = False
        self.pick("w0/l0/v0")
        window.vehicle_model.set(next(l for l in window.vehicle_model.cget("values") if l.startswith("COMPCAR18")))
        window.apply_vehicle()
        self.assertEqual(window.schedule.waves[0].lanes[0].vehicles[0].model, "COMPCAR14")
        self.assertEqual(window.additions, ())

    def test_lane_speed_is_shown_and_edited(self):
        window = self.window
        self.pick("w0/l0")
        self.assertEqual(window.lane_speed.get(), "")  # the generated wave 1 sets no speed
        ui._set(window.lane_speed, "45")
        window.apply_lane_speed()
        lane = window.schedule.waves[0].lanes[0]
        self.assertEqual(self.tw.lane_speed(window.schedule, 0, lane.source, lane.slot), (45.0, 0))
        self.assertIn("72 km/h", window.lane_speed_note.get())
        self.assertIn("speed 45", window.wave_tree.item("w0/l0", "values")[1])
        kwargs = self.export_kwargs()
        self.assertEqual(kwargs["waves"].waves[0].speeds[-1].speed, 45.0)

    def test_lane_options_are_readable_and_can_be_added(self):
        window = self.window
        self.pick("w1")
        options = window.new_lane.cget("values")
        self.assertTrue(options)
        self.assertTrue(all(o.startswith("P") for o in options))
        self.assertTrue(any("used in wave" in o or "not used" in o for o in options))
        window.new_lane.set(options[0])
        window.add_lane()
        self.assertEqual(len(window.schedule.waves[1].lanes), 2)

    def test_3d_map_matches_the_top_view_when_looking_straight_down(self):
        import math
        window = self.window
        window.roads = {"path_count": 1, "paths": [{"center": [[0, 0, 0], [100, 20, 50]]}]}
        window.wave_canvas.configure(width=300, height=200)
        self.root.update()
        window.map_view, window.map_cy = (50.0, 25.0, 120.0), 10.0
        flat, _ = window._map_frame()
        window.map_3d.set(True)
        window.map_yaw, window.map_pitch = 0.0, math.pi / 2
        top, _ = window._map_frame()
        for point in ([0, 0, 0], [100, 20, 50], [30, -5, 80]):
            self.assertAlmostEqual(flat(point)[0], top(point)[0], places=6)
            self.assertAlmostEqual(flat(point)[1], top(point)[1], places=6)
        window.map_pitch = 0.3  # tilted: a higher point is drawn higher on screen
        tilted, _ = window._map_frame()
        self.assertLess(tilted([50, 40, 25])[1], tilted([50, 0, 25])[1])

    def test_level_number_and_shared_start_appear_in_the_heading(self):
        window = self.window
        window.numbers = {self.event.key: 8}
        window.places = {self.event.key: {"shared_with": []}}
        window.event = None
        window.select()
        self.assertIn("Level 8", window.heading.get())

    def test_add_several_shows_a_preview_before_adding(self):
        window = self.window
        self.pick("w0/l0")
        window.quick_model.set("COMPCAR12")
        window.quick_count.set("2")
        ui._set(window.quick_spacing, "10")
        window.preview_changed()
        self.assertIn("125, 115", window.quick_preview.get())
        self.assertIn("behind HEVYCAR33 at 135", window.quick_preview.get())


if __name__ == "__main__":
    unittest.main()
