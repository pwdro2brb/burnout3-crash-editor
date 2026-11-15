"""Manual retirement cleanup using synthetic batches and sparse owned memory."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import batch, controller as c, profile, spawncode as s
from editor.pine import Status
import test_batch as fixtures


class ManualFinalizationTests(unittest.TestCase):
    def setUp(self):
        # Composition avoids rediscovering every batch test in this module.
        self.fixture = fixtures.BatchControllerTests()

    def cold_retired(self, *, paired=False):
        editor, client, snap = self.fixture.staged(paired=paired)
        final, ids = self.fixture.publish(editor, client, snap, paired=paired)
        cold = ids[-1] + (1 if paired else 0)
        final.vehicles[cold]['initialized'] = False
        return editor, client, final, ids

    def test_manual_release_of_cold_retired_batch_preserves_all_actors(self):
        for paired in (False, True):
            with self.subTest(paired=paired):
                editor, client, final, _ids = self.cold_retired(paired=paired)
                pending = editor.pending
                editor.replay_queue = [{'op':'must_not_run'}]
                actors = {row['id']:client.read_bytes(row['address'], 14)
                          for row in final.vehicles.values()}
                context, _snapshot, _collider, aligned, journal = self.fixture.poll_context(editor, client, final)
                with context, patch.object(batch.time, 'monotonic', return_value=100.):
                    result = editor.finalize_pending()
                self.assertFalse(result['pending'])
                self.assertTrue(result['warning'])
                self.assertIn('mantidos', result['message'])
                self.assertEqual(pending.physics_wait_started, 100.)
                self.fixture.assert_clean_owned_only(editor, client)
                self.assertEqual(editor.actor_keys, {})
                self.assertEqual(editor.replay_ids, {})
                self.assertFalse(editor.unsafe)
                aligned.assert_not_called()
                for row in final.vehicles.values():
                    self.assertEqual(client.read_bytes(row['address'], 14), actors[row['id']])
                self.assertEqual(journal.call_args.kwargs['reason'], 'manual_physics_release')

    def test_manual_release_accepts_owned_retirement_when_snapshot_is_rejected(self):
        editor, client, final, _ids = self.cold_retired()
        context, _snapshot, _collider, aligned, _journal = self.fixture.poll_context(editor, client, final)
        with context, patch.object(editor, '_snapshot', side_effect=profile.ProfileError('Synthetic not-ready profile')):
            result = editor.finalize_pending()
        self.assertFalse(result['pending'])
        self.assertTrue(result['warning'])
        aligned.assert_not_called()
        self.fixture.assert_clean_owned_only(editor, client)

    def test_manual_release_cannot_clear_running_incomplete_or_unretired_code(self):
        for state in ('running', 'probe_incomplete', 'master_unretired', 'hook_active'):
            with self.subTest(state=state):
                editor, client, final, _ids = self.cold_retired()
                pending = editor.pending
                if state == 'running':
                    client.core_status = Status.RUNNING
                elif state == 'probe_incomplete':
                    client.store(pending.probes[-1], struct.pack('<I', 1))
                elif state == 'master_unretired':
                    client.store(pending.completion_address, struct.pack('<I', 0))
                else:
                    client.store(s.HOOK, pending.hook)
                before = client.memory.copy()
                context, snapshot, _collider, aligned, _journal = self.fixture.poll_context(editor, client, final)
                with context:
                    if state in ('running', 'hook_active'):
                        with self.assertRaises(c.EditorError):
                            editor.finalize_pending()
                    else:
                        self.assertTrue(editor.finalize_pending()['pending'])
                self.assertIs(editor.pending, pending)
                self.assertEqual(client.memory, before)
                self.assertEqual(client.writes, [])
                self.assertEqual(client.patch_calls, [])
                snapshot.assert_not_called()
                aligned.assert_not_called()

    def test_changed_payload_is_refused_before_manual_cleanup(self):
        for offset in (s.NONCE_ADDRESS, s.CAVE + 0x10, s.BATCH_RECORD_BASE + 0x18):
            with self.subTest(offset=hex(offset)):
                editor, client, final, _ids = self.cold_retired()
                pending = editor.pending
                client.memory[offset] ^= 1
                before = client.memory.copy()
                context, snapshot, _collider, aligned, _journal = self.fixture.poll_context(editor, client, final)
                with context, self.assertRaises(c.EditorError):
                    editor.finalize_pending()
                self.assertIs(editor.pending, pending)
                self.assertEqual(client.memory, before)
                self.assertEqual(client.writes, [])
                snapshot.assert_not_called()
                aligned.assert_not_called()

    def test_cleanup_readback_failure_keeps_pending_and_blocks_another_edit(self):
        editor, client, final, _ids = self.cold_retired()
        pending = editor.pending
        editor.replay_queue = [{'op':'must_not_run'}]
        original_write = client.write_bytes

        def corrupt_cleanup(address, data):
            original_write(address, data)
            if address == s.CAVE:
                client.memory[s.CAVE] ^= 1

        context, _snapshot, _collider, aligned, _journal = self.fixture.poll_context(editor, client, final)
        with context, patch.object(client, 'write_bytes', side_effect=corrupt_cleanup):
            with self.assertRaises(c.EditorError):
                editor.finalize_pending()
        self.assertTrue(editor.unsafe)
        self.assertIs(editor.pending, pending)
        self.assertEqual(editor.recipe, [])
        self.assertEqual(editor.actor_keys, {})
        aligned.assert_not_called()
        writes = list(client.writes)
        with self.assertRaises(c.EditorError):
            editor.finalize_pending()
        self.assertEqual(client.writes, writes)

    def test_finishing_one_group_never_manually_releases_the_next_group(self):
        editor, client, snap = self.fixture.staged()
        final, ids = self.fixture.publish(editor, client, snap)
        next_editor, _next_client, _next_snap = self.fixture.staged(count=1)
        next_pending = next_editor.pending
        editor.replay_queue = [{'op':'synthetic_next_group'}]

        def stage_next():
            editor.pending = next_pending
            client.write_bytes(s.CAVE, next_pending.scratch)
            client.write_bytes(s.HOOK, next_pending.hook)
            return {'pending':True, 'core_paused':True, 'message':'Synthetic next group staged'}

        context, _snapshot, _collider, _aligned, _journal = self.fixture.poll_context(editor, client, final)
        with context, patch.object(editor, '_continue_recipe', side_effect=stage_next):
            result = editor.finalize_pending()
        self.assertTrue(result['pending'])
        self.assertIs(editor.pending, next_pending)
        self.assertEqual(client.read_bytes(s.CAVE, 4096), next_pending.scratch)
        self.assertEqual(client.read_bytes(s.HOOK, 8), next_pending.hook)
        self.assertEqual(len(editor.recipe), len(ids))
        self.assertEqual([data for address, data in client.writes if address == s.CAVE],
                         [s.clean_batch_scratch(), next_pending.scratch])


if __name__ == '__main__':
    unittest.main()
