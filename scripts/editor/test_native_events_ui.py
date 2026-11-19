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


GROUPS = (("COMPCAR14", "COMPCAR12"), ("HEVYCAR33",), (), (), (), ())


class NativeEventGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk indisponível: {exc}")
        cls.root.withdraw()
        cls.addClassCleanup(cls.root.destroy)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.game = Path(folder.name)
        self.a = CrashEvent("1G0007EUC3V1", "EU_C3_V1", "Grand Slam", 97, 0, 0, 0,
                            2048, (300, 200, 100), (300, 200, 100), 10, 10)
        self.b = CrashEvent("1G0003USC2V1", "US_C2_V1", "Outro", 96, 1, 0, 0,
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
        self.assertIn("pausado", window.status.get())
        window.query.set("Grand")
        self.active = {"event_key": self.b.key}
        window.locate()
        self.assertEqual(window.event, self.b)
        self.assertEqual(window.query.get(), "")
        self.assertEqual(str(window.fields[0].cget("state")), "readonly")
        self.assertEqual(window.fields[0].get(), "700")
        self.assertEqual(str(window.crash_count.cget("state")), "readonly")
        self.assertIn("divergem", window.limit_note.get())
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
        window.query.set("nenhum evento")
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
        iso.assert_called_once_with(self.game / "source.iso", self.game / "dest.iso", changes)
        self.assertIn("Grand Slam", window.status.get())
        self.assertTrue(window.close())
        self.confirm.assert_not_called()

    def test_crashbreaker_alone_can_be_exported_within_observed_range(self):
        folder = self.replace(ui.filedialog, "askdirectory", return_value=str(self.game))
        window = self.window
        window.crash_count.delete(0, "end")
        window.crash_count.insert(0, "16")
        window.export(False)
        self.assertIn("6 a 15", window.status.get())
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
        self.assertIn("Altere", window.status.get())
        window.fields[0].insert("end", "x")
        window.export(False)
        self.assertIn("inteiros", window.status.get())
        dialog.assert_not_called()
        window.fields[0].delete(0, "end")
        window.fields[0].insert(0, "450")
        self.replace(ui, "prepare_changes", side_effect=ValueError("Pista mudou"))
        window.export(False)
        self.finish_job()
        self.assertEqual(window.status.get(), "Pista mudou")
        self.assertEqual(window.fields[0].get(), "450")
        self.error.assert_called_once()
        self.assertFalse(window.close())

    def test_opening_a_folder_preserves_draft_if_loading_or_confirmation_fails(self):
        self.swap_first_group()
        self.catalog.side_effect = ValueError("Outra região")
        self.window.open_game(self.game)
        self.finish_job()
        self.assertIn("região", self.window.status.get())
        self.confirm.assert_not_called()
        self.catalog.side_effect = None
        self.window.open_game(self.game)
        self.finish_job()
        self.assertEqual(self.window.orders[0], ("COMPCAR12", "COMPCAR14"))
        self.confirm.assert_called_once()
        self.assertIn("mantidas", self.window.status.get())

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
