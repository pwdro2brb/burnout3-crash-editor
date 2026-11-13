"""Completed-request cleanup regressions without game files or an emulator.

Only our generated request bytes are placed in sparse fake memory. Traffic
snapshots are synthetic; the real controller poll/ownership/cleanup path runs.
"""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import controller as c, spawncode as s
from editor.pine import PinePatchConflict, PineVerificationError, PineTransportError, Status


OBJECT = 0x539C10+12*0x180
NODE = 0x551910+10*0x50
MODEL_HASH = 0x0102030405060708  # Synthetic identifier, no game asset required.


class SparseClient:
    def __init__(self, payload):
        self.memory = {}
        self.writes = []
        self.fail_cleanup = False
        self.store(s.CAVE, payload['scratch_bytes'])
        self.store(s.HOOK, payload['hook_bytes'])
        self.store(s.DATA, struct.pack('<3I', s.PROBE_STATE_DONE, OBJECT, NODE))
        self.store(OBJECT, b'actor-sentinel')

    def store(self, address, data):
        self.memory.update((address+i, byte) for i, byte in enumerate(data))

    def identity(self):
        return {'version': 'PCSX2 1.7.2521', 'game_id': 'SLUS-21050', 'game_crc': 'BEBF8793'}

    def status(self):
        return Status.PAUSED

    def read_bytes(self, address, size):
        # An unplanned read is a test failure, rather than zero-filled game RAM.
        return bytes(self.memory[address+i] for i in range(size))

    def read_many(self, requests):
        return [int.from_bytes(self.read_bytes(address, width), 'little')
                for address, width in requests]

    def apply_patch(self, patches):
        patches = list(patches)
        actual = self.read_many((p.address, p.width) for p in patches)
        if actual != [p.expected for p in patches]:
            raise PinePatchConflict('Synthetic expected-byte conflict')
        for entry in patches:
            self.write_bytes(entry.address, entry.value.to_bytes(entry.width, 'little'))

    def write_bytes(self, address, data):
        if self.fail_cleanup and address == s.CAVE:
            raise PineVerificationError('Synthetic cleanup failure')
        self.writes.append((address, bytes(data)))
        self.store(address, data)


def completed_request():
    nonce = bytes(range(16))
    payload = s.build_spawn(manager=s.MANAGER, type_code=1, model_hash=MODEL_HASH,
        path_descriptor=s.PATHS+21*s.PATH_STRIDE, progression=20, speed=30,
        spacing=1, nonce=nonce)
    client = SparseClient(payload)
    controller = c.EditorController(client=client)
    pending = c.Pending(scratch=payload['scratch_bytes'], hook=payload['hook_bytes'],
        model_id='SYNTHETIC_CAR', model_hash=MODEL_HASH, type_code=1, path=21,
        lateral=.85, old_ids={9}, target_ref={'kind': 'initial', 'id': 9},
        gap=10, created_key=1, staged_at=0, nonce=nonce.hex())
    controller.pending = pending
    controller.replay_queue = [{'op': 'move_lateral'}]
    return controller, client, pending


class CompletedRequestTests(unittest.TestCase):
    def test_profile_rejection_records_code_without_writing_or_hiding_error(self):
        controller, client, pending = completed_request()
        rejection = c.profile.ProfileError('Unknown hook')
        with patch.object(c.profile, 'snapshot', side_effect=rejection), \
             patch.object(controller, '_journal') as journal:
            with self.assertRaises(c.profile.ProfileError) as caught:
                controller._snapshot(pending=True)
        self.assertIs(caught.exception, rejection)
        self.assertEqual(client.writes, [])
        details = journal.call_args.kwargs
        self.assertEqual(journal.call_args.args, ('profile_rejected',))
        self.assertEqual(details['epilogue_hex'], pending.hook.hex())
        self.assertEqual(details['core_status'], int(Status.PAUSED))

    def test_diagnostic_disconnect_does_not_replace_original_rejection(self):
        controller, client, _pending = completed_request()
        rejection = c.profile.ProfileError('Unknown hook')
        with patch.object(c.profile, 'snapshot', side_effect=rejection), \
             patch.object(client, 'read_bytes', side_effect=PineTransportError('Disconnected', may_have_executed=False)), \
             patch.object(controller, '_journal') as journal:
            with self.assertRaises(c.profile.ProfileError) as caught:
                controller._snapshot(pending=True)
        self.assertIs(caught.exception, rejection)
        self.assertEqual(client.writes, [])
        self.assertEqual(journal.call_args.kwargs['diagnostic_error'], 'PineTransportError')

    def assert_clean_without_actor_write(self, controller, client):
        self.assertEqual(client.read_bytes(OBJECT, len(b'actor-sentinel')), b'actor-sentinel')
        self.assertEqual(client.read_bytes(s.HOOK, 8), s.ORIGINAL)
        self.assertEqual(client.read_bytes(s.CAVE, s.END-s.CAVE), bytes(s.END-s.CAVE))
        self.assertTrue(client.writes)
        for address, data in client.writes:
            self.assertTrue((s.HOOK <= address and address+len(data) <= s.HOOK+8)
                            or (s.CAVE <= address and address+len(data) <= s.END))
        self.assertIsNone(controller.pending)
        self.assertEqual(controller.replay_queue, [])
        self.assertEqual(controller.recipe, [])
        self.assertEqual(controller.actor_keys, {})
        self.assertEqual(controller.replay_ids, {})

    def test_disappeared_actor_cleans_only_owned_request_and_warns(self):
        controller, client, pending = completed_request()
        with patch.object(c.profile, 'snapshot', return_value=SimpleNamespace(vehicles={})) as snapshot, \
             patch.object(c.profile, 'lateral_patches', side_effect=AssertionError('Must not align an expired actor')), \
             patch.object(controller, '_journal') as journal:
            result = controller.poll()
        snapshot.assert_called_once_with(client, require_paused=True, allow_editor_hook=True)
        self.assertEqual((result['pending'], result['core_paused'], result['warning']), (False, True, True))
        self.assertIn('Alinhamento não confirmado', result['message'])
        self.assert_clean_without_actor_write(controller, client)
        journal.assert_called_once_with('spawn_not_finalized', nonce=pending.nonce,
            reason='object_no_longer_active', object_pointer=OBJECT, node_pointer=NODE)

    def test_reused_model_is_never_aligned_or_recorded_as_success(self):
        controller, client, pending = completed_request()
        row = {'node': NODE, 'model_hash': MODEL_HASH+1, 'path': 21, 'type': 1,
               'independent': True, 'initialized': True}
        with patch.object(c.profile, 'snapshot', return_value=SimpleNamespace(vehicles={12: row})), \
             patch.object(c.profile, 'lateral_patches', side_effect=AssertionError('Must not align a reused actor')), \
             patch.object(controller, '_journal') as journal:
            result = controller.poll()
        self.assertTrue(result['warning'])
        self.assert_clean_without_actor_write(controller, client)
        journal.assert_called_once_with('spawn_not_finalized', nonce=pending.nonce,
            reason='model_changed', object_pointer=OBJECT, node_pointer=NODE)

    def test_changed_nonce_code_or_hook_prevents_all_cleanup_writes(self):
        for address in (s.NONCE_ADDRESS, s.CAVE+100, s.HOOK):
            with self.subTest(address=hex(address)):
                controller, client, pending = completed_request()
                client.memory[address] ^= 1
                before = client.memory.copy()
                with patch.object(c.profile, 'snapshot') as snapshot, \
                     patch.object(c.profile, 'lateral_patches') as align:
                    with self.assertRaises(c.EditorError):
                        controller.poll()
                snapshot.assert_not_called()
                align.assert_not_called()
                self.assertEqual(client.writes, [])
                self.assertEqual(client.memory, before)
                self.assertIs(controller.pending, pending)

    def test_cleanup_failure_retains_pending_and_blocks_further_edits(self):
        controller, client, pending = completed_request()
        client.fail_cleanup = True
        with patch.object(c.profile, 'snapshot', return_value=SimpleNamespace(vehicles={})), \
             patch.object(c.profile, 'lateral_patches') as align, \
             patch.object(controller, '_journal') as journal:
            with self.assertRaisesRegex(c.EditorError, 'Recarregue um estado limpo'):
                controller.poll()
        align.assert_not_called()
        self.assertTrue(controller.unsafe)
        self.assertIs(controller.pending, pending)
        self.assertTrue(controller.replay_queue)
        self.assertEqual(controller.recipe, [])
        self.assertEqual(controller.actor_keys, {})
        self.assertEqual(client.read_bytes(OBJECT, len(b'actor-sentinel')), b'actor-sentinel')
        journal.assert_called_once_with('cleanup_unconfirmed', nonce=pending.nonce,
            reason='object_no_longer_active', object_pointer=OBJECT, node_pointer=NODE)
        before = list(client.writes)
        with self.assertRaises(c.EditorError):
            controller.poll()
        self.assertEqual(client.writes, before)


if __name__ == '__main__':
    unittest.main()
