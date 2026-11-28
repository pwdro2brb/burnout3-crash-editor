"""Batches behind several references, and references outside the physics range.

Synthetic snapshots only (no game asset or emulator): planning, installation,
per-request validation and recipe bookkeeping use the real batch code.
"""
import copy
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import batch, controller as c, profile, spawncode as s
from editor.pine import Patch
from test_batch import CAR, TRUCK, TRAILER, BatchClient, initial_snapshot, vehicle

OTHER_PATH = 34


def two_lane_snapshot(*, far=False):
    snap = initial_snapshot()
    second = vehicle(20, node_index=40)
    second.update(path=OTHER_PATH, position=[500.0, 10.0, 50.0], progress=300.0)
    snap.vehicles[20] = second
    if far:
        for row in snap.vehicles.values():
            row.update(initialized=False, editable=False, far_reference=True, can_reference=True)
    snap.player = {'position': [0.0, 10.0, 0.0], 'forward': [1.0, 0.0, 0.0]}
    return snap


class Helpers:
    def fixture(self, **options):
        client = BatchClient()
        return c.EditorController(client=client), client, two_lane_snapshot(**options)

    def run_with(self, client, snap, action):
        def behind(_memory, _path, progress, _lateral, gap, **_kwargs):
            self.assertEqual(client.writes, [], 'Planning must precede installation')
            return progress - gap

        def lane(_memory, path, progress, _lateral):
            offset = 50.0 if path == OTHER_PATH else 0.0
            return {'point': [progress, 10.0, offset], 'lane': [0., 0., 10.]}

        with patch.object(profile, 'snapshot', return_value=snap), \
             patch.object(batch, '_state_digest', return_value='digest'), \
             patch.object(profile, 'behind_progress', side_effect=behind), \
             patch.object(profile, 'lane', side_effect=lane):
            return action()

    def publish(self, editor, client, snap, *, initialized=True, first_index=60):
        final = copy.copy(snap)
        final.vehicles = dict(snap.vehicles)
        ids = []
        for number, (probe, request) in enumerate(zip(editor.pending.probes, editor.pending.requests_meta)):
            index = first_index + number
            row = vehicle(index, node_index=80 + number)
            row.update(path=request['path'], initialized=initialized, path_valid=True,
                       position=[400.0 + number, 10.0, 0.0])
            final.vehicles[index] = row
            ids.append(index)
            client.store(probe, struct.pack('<3I', 2, row['address'], row['node']))
            client.store(row['address'], b'actor-sentinel')
            client.store(row['address'] + 0xA0, struct.pack('<I', index))
            client.store(row['node'] + 0x34, struct.pack('<f', 0.5))
        client.store(editor.pending.completion_address, struct.pack('<I', editor.pending.completion_token))
        client.store(s.HOOK, s.ORIGINAL)
        base = final.memory

        class Memory:
            # Synthetic counters from the fixture; node words from the client.
            def u32(self, address):
                try:
                    return base.u32(address)
                except AssertionError:
                    return int.from_bytes(client.read_bytes(address, 4), 'little')

            def u8(self, address):
                return base.u8(address)
        final.memory = Memory()
        client.writes.clear()
        client.patch_calls.clear()
        return final, ids

    def finish(self, editor, client, final):
        def alignment(state, index, _lateral, **_kwargs):
            return [Patch(state.vehicles[index]['address'] + 0xA0, 4, index, index + 100)]
        with patch.object(profile, 'snapshot', return_value=final), \
             patch.object(batch, 'collider_valid', return_value=True), \
             patch.object(profile, 'lateral_patches', side_effect=alignment) as near, \
             patch.object(editor, '_journal'):
            return editor.poll(), near



class MultiReferenceBatchTests(Helpers, unittest.TestCase):
    def test_one_batch_spans_two_references_on_different_paths(self):
        editor, client, snap = self.fixture()
        result = self.run_with(client, snap, lambda: editor.add_behind_each([9, 20], [{'model_id': None}], 10, 2))
        self.assertTrue(result['pending'])
        self.assertIn('behind 2 reference', result['message'])
        pending = editor.pending
        self.assertEqual([m['path'] for m in pending.requests_meta], [21, 21, OTHER_PATH, OTHER_PATH])
        matched = s.match_batch_scratch(pending.scratch, bytes.fromhex(pending.nonce))
        descriptors = [r['path_descriptor'] for r in matched['requests']]
        self.assertEqual(descriptors, [profile.PATHS + p * profile.PATH_STRIDE for p in (21, 21, 34, 34)])
        self.assertEqual(len(client.patch_calls), 1)
        final, ids = self.publish(editor, client, snap)
        done, near = self.finish(editor, client, final)
        self.assertFalse(done['pending'])
        self.assertEqual(done['new_vehicle_ids'], ids)
        self.assertEqual(near.call_count, 4)
        targets = [op['target'] for op in editor.recipe]
        self.assertEqual(targets[0], {'kind': 'initial', 'id': 9, 'model_id': CAR, 'path': 21})
        self.assertEqual(targets[1], {'kind': 'created', 'key': 1})
        self.assertEqual(targets[2], {'kind': 'initial', 'id': 20, 'model_id': CAR, 'path': OTHER_PATH})
        self.assertEqual(targets[3], {'kind': 'created', 'key': 3})

    def test_more_than_eight_queue_by_chain_and_group_later_chains_together(self):
        editor, client, snap = self.fixture()
        result = self.run_with(client, snap, lambda: editor.add_behind_each([9, 20], [{'model_id': None}], 10, 6))
        self.assertIn('Queue: 4 more', result['message'])
        self.assertEqual(editor.pending.created_keys, list(range(1, 9)))
        self.assertEqual(editor.next_key, 13)
        queued = editor.replay_queue
        self.assertEqual([op['created_key'] for op in queued], [9, 10, 11, 12])
        self.assertEqual(queued[0]['target'], {'kind': 'created', 'key': 8})
        self.assertEqual(queued[1]['target'], {'kind': 'created', 'key': 9})
        final, ids = self.publish(editor, client, snap)
        # Finishing the first group stages the next one from the queue.
        def alignment(state, index, _lateral, **_kwargs):
            return [Patch(state.vehicles[index]['address'] + 0xA0, 4, index, index + 100)]
        with patch.object(profile, 'snapshot', return_value=final), \
             patch.object(batch, 'collider_valid', return_value=True), \
             patch.object(profile, 'lateral_patches', side_effect=alignment), \
             patch.object(batch, '_state_digest', return_value='digest'), \
             patch.object(profile, 'behind_progress', side_effect=lambda _m, _p, progress, _l, gap, **_k: progress - gap), \
             patch.object(profile, 'lane', side_effect=lambda _m, path, progress, _l: {'point': [progress, 10.0, 0.0], 'lane': [0., 0., 10.]}), \
             patch.object(editor, '_journal'):
            follow = editor.poll()
        self.assertTrue(follow['pending'])
        self.assertEqual(editor.pending.created_keys, [9, 10, 11, 12])
        self.assertEqual(editor.replay_queue, [])

    def test_a_reference_selected_twice_or_without_a_path_is_refused_before_writes(self):
        editor, client, snap = self.fixture()
        with self.assertRaises(c.EditorError):
            self.run_with(client, snap, lambda: editor.add_behind_each([9, 9], [{'model_id': None}], 10, 1))
        snap.vehicles[20]['can_reference'] = False
        with self.assertRaisesRegex(c.EditorError, 'reference'):
            self.run_with(client, snap, lambda: editor.add_behind_each([9, 20], [{'model_id': None}], 10, 1))
        self.assertEqual(client.writes, [])
        self.assertIsNone(editor.pending)

    def test_chain_reaching_another_selected_vehicle_on_the_same_lane_is_refused(self):
        editor, client, snap = self.fixture()
        snap.vehicles[20].update(path=21, position=[185.0, 10.0, 0.0], progress=185.0)
        with self.assertRaisesRegex(c.EditorError, 'another selected vehicle'):
            self.run_with(client, snap, lambda: editor.add_behind_each([9, 20], [{'model_id': None}], 10, 2))
        self.assertEqual(client.writes, [])

    def test_normal_mode_limits_per_reference_and_in_total(self):
        editor, client, snap = self.fixture()
        with self.assertRaisesRegex(c.EditorError, 'per reference'):
            editor.add_behind_each([9], [{'model_id': None}], 10, 9)
        with self.assertRaisesRegex(c.EditorError, 'limit is 64'):
            editor.add_behind_each(list(range(9)), [{'model_id': None}], 10, 8)
        self.assertEqual(client.writes, [])

    def test_same_model_on_a_cab_reference_keeps_its_native_trailer(self):
        editor, client, snap = self.fixture()
        snap.vehicles = {9: vehicle(9, TRUCK, child=10), 10: vehicle(10, TRAILER, parent=9)}
        snap.vehicles[9]['secondary_model_id'] = TRAILER
        self.run_with(client, snap, lambda: editor.add_behind_each([9], [{'model_id': None}], 30, 2))
        self.assertEqual([item['secondary_model_id'] for item in editor.pending.items], [TRAILER, TRAILER])


class DistantReferenceTests(Helpers, unittest.TestCase):
    def test_distant_reference_batch_finishes_without_physics_and_sets_the_node_lane(self):
        editor, client, snap = self.fixture(far=True)
        result = self.run_with(client, snap, lambda: editor.add_behind_each([9], [{'model_id': None}], 10, 3))
        self.assertIn('far from the player', result['message'])
        final, ids = self.publish(editor, client, snap, initialized=False)
        done, near = self.finish(editor, client, final)
        self.assertFalse(done['pending'])
        self.assertIn('no physics yet', done['message'])
        near.assert_not_called()
        # Only the node lane fraction of each new vehicle was written.
        written = {address for call in client.patch_calls for p in call for address in [p.address]}
        self.assertEqual(written, {final.vehicles[i]['node'] + 0x34 for i in ids})
        self.assertEqual(len(editor.recipe), 3)

    def test_cold_vehicle_inside_the_physics_range_still_waits(self):
        editor, client, snap = self.fixture(far=True)
        self.run_with(client, snap, lambda: editor.add_behind_each([9], [{'model_id': None}], 10, 1))
        final, ids = self.publish(editor, client, snap, initialized=False)
        final.vehicles[ids[0]]['position'] = [100.0, 10.0, 0.0]  # within 250 units of the player
        done, near = self.finish(editor, client, final)
        self.assertTrue(done['pending'])
        self.assertEqual(client.patch_calls, [])

    def test_beyond_physics_needs_a_readable_player_and_position(self):
        row = {'position': [300.0, 0.0, 0.0]}
        self.assertTrue(batch.beyond_physics(type('S', (), {'player': {'position': [0, 0, 0]}})(), row))
        self.assertFalse(batch.beyond_physics(type('S', (), {'player': None})(), row))
        self.assertFalse(batch.beyond_physics(type('S', (), {'player': {'position': [0, 0, 0]}})(),
                                              {'position': [0.0, 0.0, 0.0]}))
        self.assertFalse(batch.beyond_physics(type('S', (), {'player': {'position': [0, 0, 0]}})(),
                                              {'position': [float('nan'), 0.0, 0.0]}))


class FarProfileTests(unittest.TestCase):
    def test_far_independent_row_can_reference_but_not_move(self):
        row = dict(id=1, initialized=False, type=1, independent=True, path_valid=True, node_index=3,
                   editable=False, speed=30.0, travel_speed=13.0, spacing_scalar=1.0, model_id='M',
                   parent_id=None, child_id=None, kind='independent')
        model = dict(kind='independent', verified=True, observed_types={1}, independent_observed_types={1},
                     trailer_model_ids=set(), truck_model_ids=set())
        profile._compound_metadata({1: row}, {'M': model})
        self.assertTrue(row['far_reference'])
        self.assertTrue(row['can_reference'])
        self.assertFalse(row['editable'])
        for change in (dict(path_valid=False), dict(node_index=None), dict(type=6), dict(independent=False),
                       dict(speed=-1.0)):
            with self.subTest(change=change):
                other = dict(row, **change)
                profile._compound_metadata({1: other}, {'M': dict(model, observed_types={1},
                    independent_observed_types={1}, trailer_model_ids=set(), truck_model_ids=set())})
                self.assertFalse(other['can_reference'])

    def test_far_lateral_patch_touches_only_the_node_fraction(self):
        class Memory:
            def u32(self, address):
                return 0x3F000000
        row = dict(initialized=False, node=0x551910, node_index=0, path_valid=True)
        state = profile.Snapshot(Memory(), {}, {4: row}, {}, True)
        patches = profile.far_lateral_patches(state, 4, 25)
        self.assertEqual([(p.address, p.expected, p.value) for p in patches],
                         [(0x551910 + 0x34, 0x3F000000, struct.unpack('<I', struct.pack('<f', .25))[0])])
        row['initialized'] = True
        with self.assertRaises(profile.ProfileError):
            profile.far_lateral_patches(state, 4, 25)


if __name__ == '__main__':
    unittest.main()
