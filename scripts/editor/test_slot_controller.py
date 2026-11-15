"""Slot archival remains an explicit paused action with no pending writes."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import controller as c,profile,slot_archive,spawncode
from editor.pine import Status
import test_batch as fixtures


class SlotControllerTests(unittest.TestCase):
    def fixture(self):
        editor,client,snap=fixtures.BatchControllerTests().fixture()
        editor.pause_control=SimpleNamespace(supports=lambda:True,emulator_root=lambda:Path('TEST_EMULATOR'))
        patched=patch.object(profile,'snapshot',return_value=snap)
        patched.start()
        self.addCleanup(patched.stop)
        return editor,client

    def test_listing_is_read_only_and_archival_receives_a_live_pause_guard(self):
        editor,client=self.fixture()
        rows=[dict(slot=4,occupied=True,paths=['slot04.p2s'],total_bytes=3)]
        with patch.object(slot_archive,'list_slots',return_value=rows) as listed:
            result=editor.list_state_slots()
        self.assertEqual(result['slots'],rows)
        listed.assert_called_once_with(Path('TEST_EMULATOR'))
        def archive(root,slot,*,guard):
            self.assertEqual((root,slot),(Path('TEST_EMULATOR'),4))
            guard()
            return dict(slot=slot,archive_directory='TEST_BACKUP',message='Preservado')
        with patch.object(slot_archive,'archive_slot',side_effect=archive) as archived:
            result=editor.archive_state_slot(4)
        archived.assert_called_once()
        self.assertEqual(result['archive_directory'],'TEST_BACKUP')
        self.assertTrue(result['core_paused'])
        self.assertEqual(client.writes,[])

    def test_running_pending_dirty_hook_and_unavailable_control_never_archive(self):
        for condition in ('running','pending','hook','control'):
            with self.subTest(condition=condition):
                editor,client=self.fixture()
                if condition=='running': client.core_status=Status.RUNNING
                elif condition=='pending': editor.pending=object()
                elif condition=='hook': client.store(spawncode.HOOK,b'changed!')
                else: editor.pause_control.supports=lambda:False
                with patch.object(slot_archive,'archive_slot') as archived:
                    with self.assertRaises(c.EditorError): editor.archive_state_slot(4)
                archived.assert_not_called()
                self.assertEqual(client.writes,[])

    def test_guard_refuses_resume_after_confirmation_before_file_mutation(self):
        editor,client=self.fixture()
        def archive(_root,_slot,*,guard):
            client.core_status=Status.RUNNING
            guard()
            raise AssertionError('No file mutation should follow a resumed core')
        with patch.object(slot_archive,'archive_slot',side_effect=archive):
            with self.assertRaises(c.EditorError): editor.archive_state_slot(4)
        self.assertEqual(client.writes,[])


if __name__=='__main__':
    unittest.main()
