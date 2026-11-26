"""Batch-controller behavior with sparse owned bytes and synthetic snapshots.

No game asset, emulator, socket or native API is used. Geometry and collider
inspection are separate profile responsibilities; these tests exercise real
staging, publication, ownership, cleanup and recipe bookkeeping.
"""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import batch, controller as c, profile, spawncode as s
from editor.pine import Patch, PineError, PineVerificationError, Status
from test_controller import SparseClient


CAR, TRUCK, TRAILER, OTHER_TRAILER = 'TEST_CAR', 'TEST_TRUCK', 'TEST_TRAILER', 'OTHER_TRAILER'
HASHES = {CAR: 0x1122334455667788, TRUCK: 0x8877665544332211,
          TRAILER: 0xAABBCCDDEEFF0011, OTHER_TRAILER: 0x0123456789ABCDEF}
PATH = 21


class BatchClient(SparseClient):
    def __init__(self):
        self.memory, self.writes, self.patch_calls = {}, [], []
        self.fail_cleanup = False
        self.core_status = Status.PAUSED
        self.store(s.CAVE, bytes(4096))
        self.store(s.HOOK, s.ORIGINAL)

    def status(self):
        return self.core_status

    def apply_patch(self, patches):
        patches = list(patches)
        self.patch_calls.append(patches)
        super().apply_patch(patches)


class SnapshotMemory:
    def __init__(self):
        self.suppressed = False
        self.collision_count = 10
        self.endpoint_count = 20

    def u32(self, address):
        if address == 0x55EF70+0x1CB70:
            return self.collision_count
        if address == 0x55EF70+0x1CB74:
            return self.endpoint_count
        raise AssertionError(f'Unexpected synthetic RAM read {address:#x}')

    def u8(self, address):
        if address != s.MANAGER + 0x363BE:
            raise AssertionError(f'Unexpected synthetic RAM read {address:#x}')
        return int(self.suppressed)


def vehicle(index, model=CAR, *, parent=None, child=None, node_index=None):
    type_code = 4 if model == TRUCK else 11 if model in (TRAILER, OTHER_TRAILER) else 1
    node_index = 10 + index if node_index is None else node_index
    node = (profile.NODES + node_index * profile.NODE_STRIDE
            if parent is None else 0)
    return dict(id=index, address=profile.VEHICLES + index * profile.VEHICLE_STRIDE,
                model_id=model, model_hash=HASHES[model], model_pointer=0x100000 + index * 0x10000,
                type=type_code, node=node, node_index=None if parent is not None else node_index,
                path=PATH if parent is None else None, progress=200.0, lateral=.5,
                position=[200.0, 10.0, 0.0], speed=30.0, spacing_scalar=1.0,
                initialized=True, independent=parent is None and child is None,
                editable=parent is None, can_reference=parent is None,
                parent_id=parent, child_id=child, native_pair_valid=child is not None or parent is not None)


def initial_snapshot():
    models = {
        CAR: dict(eligible=True, type=1, model_hash=HASHES[CAR]),
        TRUCK: dict(eligible=True, type=4, model_hash=HASHES[TRUCK], trailer_model_ids=[TRAILER]),
        TRAILER: dict(eligible=False, type=11, model_hash=HASHES[TRAILER],
                      eligible_as_trailer=True, truck_model_ids=[TRUCK]),
        OTHER_TRAILER: dict(eligible=False, type=11, model_hash=HASHES[OTHER_TRAILER],
                            eligible_as_trailer=True, truck_model_ids=['OTHER_TRUCK']),
    }
    return SimpleNamespace(memory=SnapshotMemory(), vehicles={9: vehicle(9)}, models=models,
                           inspection={'counts': dict(free_objects=253, free_nodes=253,
                               active_objects=1, capacity_budget_byte_0x363ab=254)})


class BatchControllerTests(unittest.TestCase):
    def test_observed_van_and_bus_types_reach_the_native_builder(self):
        for type_code,gap in ((3,10),(5,30)):
            with self.subTest(type_code=type_code):
                editor,client,snap = self.fixture()
                snap.models[CAR]['type'] = type_code
                result,_planned = self.stage(editor,client,snap,count=1,
                    action=lambda: editor.add_many_behind(9,CAR,gap,1))
                self.assertTrue(result['pending'])
                pending = editor.pending
                matched = s.match_batch_scratch(pending.scratch,bytes.fromhex(pending.nonce))
                self.assertEqual(matched['requests'][0]['type_code'],type_code)
                self.assertEqual(matched['requests'][0]['secondary_model_hash'],0)

    def test_bus_model_or_reference_requires_spacing_before_any_write(self):
        for selected_bus in (False,True):
            with self.subTest(selected_bus=selected_bus):
                editor,client,snap = self.fixture()
                if selected_bus: snap.vehicles[9]['type'] = 5
                else: snap.models[CAR]['type'] = 5
                with self.assertRaisesRegex(c.EditorError,'30 to 50'):
                    self.stage(editor,client,snap,count=1)
                self.assertEqual(client.writes,[])

    def test_a_previous_generation_publication_cannot_retire_the_current_batch(self):
        editor,client,snap = self.staged(count=1)
        final,_ids = self.publish(editor,client,snap)
        for old_token in (2,s.completion_token(bytes([44])*16)):
            client.store(editor.pending.completion_address,struct.pack('<I',old_token))
            context,snapshot,_collider,aligned,_journal = self.poll_context(editor,client,final)
            with context:
                result = editor.poll()
            self.assertTrue(result['pending'])
            self.assertEqual(client.writes,[])
            snapshot.assert_not_called()
            aligned.assert_not_called()

    def test_staging_never_reuses_a_known_generation_token(self):
        editor,client,snap = self.fixture()
        old_nonce,new_nonce = bytes([31])*16,bytes([32])*16
        editor.completion_tokens.add(s.completion_token(old_nonce))
        with patch.object(batch.secrets,'token_bytes',side_effect=[old_nonce,new_nonce]) as nonce:
            self.stage(editor,client,snap,count=1)
        self.assertEqual(nonce.call_count,2)
        self.assertEqual(editor.pending.nonce,new_nonce.hex())

    def test_collision_capacity_is_checked_before_installing_any_request(self):
        for field,value in [('collision_count',1224),('endpoint_count',2448)]:
            with self.subTest(field=field):
                editor,client,snap = self.fixture()
                setattr(snap.memory,field,value)
                with self.assertRaisesRegex(c.EditorError,'collision'):
                    self.stage(editor,client,snap,count=2)
                self.assertEqual(client.writes,[])

    def test_all_truck_spacing_constraints_preflight_before_first_recipe_write(self):
        for target_truck,created_reference in [(False,False),(True,False),(False,True)]:
            with self.subTest(target_truck=target_truck,created_reference=created_reference):
                editor,client,snap = self.fixture()
                if target_truck:
                    snap.vehicles = {9:vehicle(9,TRUCK,child=10),10:vehicle(10,TRAILER,parent=9)}
                ref = {'kind':'initial','id':9,'model_id':TRUCK if target_truck else CAR,'path':PATH}
                first = {'op':'move_lateral','target':ref,'lateral_percent':60}
                bad = {'op':'add_behind','target':ref,'model_id':TRUCK if not target_truck else CAR,
                       'gap':8,'created_key':2}
                if not target_truck:
                    bad['secondary_model_id'] = TRAILER
                if created_reference:
                    first = {'op':'add_behind','target':ref,'model_id':TRUCK,
                             'secondary_model_id':TRAILER,'gap':30,'created_key':1}
                    bad = {'op':'add_behind','target':{'kind':'created','key':1},
                           'model_id':CAR,'gap':8,'created_key':2}
                data = {'format':'burnout3-current-event-recipe','version':1,
                        'profile':'SLUS-21050/BEBF8793','baseline':c._fingerprint(snap),
                        'operations':[first,bad]}
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary)/'bad-spacing.json'
                    path.write_text(json.dumps(data),encoding='utf8')
                    with patch.object(profile,'snapshot',return_value=snap), \
                         patch.object(editor,'move',side_effect=AssertionError('No earlier operation may execute')):
                        with self.assertRaisesRegex(c.EditorError,'30 to 50'):
                            editor.load_preset(str(path))
                self.assertEqual(client.writes,[])

    def fixture(self):
        client = BatchClient()
        editor = c.EditorController(client=client)
        return editor, client, initial_snapshot()

    def stage(self, editor, client, snap, *, count=3, paired=False, behind=None, action=None):
        def default_behind(_memory, _path, progress, _lateral, gap, **_kwargs):
            self.assertEqual(client.writes, [], 'All positions must be planned before installation')
            if progress < gap:
                raise profile.ProfileError('Synthetic path begins before the final position')
            return progress - gap

        def lane(_memory, _path, progress, _lateral):
            self.assertEqual(client.writes, [], 'Geometry planning must precede installation')
            return {'point': [progress, 10.0, 0.0],'lane':[0.,0.,10.]}

        with patch.object(profile, 'snapshot', return_value=snap), \
             patch.object(batch, '_state_digest', return_value='synthetic-recovery-digest'), \
             patch.object(profile, 'behind_progress', side_effect=behind or default_behind) as planned, \
             patch.object(profile, 'lane', side_effect=lane):
            result = (action() if action is not None else
                      editor.add_many_behind(9, TRUCK if paired else CAR,
                                             30 if paired else 10, count, TRAILER if paired else None))
        return result, planned

    def staged(self, *, count=3, paired=False):
        editor, client, snap = self.fixture()
        result, _ = self.stage(editor, client, snap, count=count, paired=paired)
        self.assertTrue(result['pending'])
        return editor, client, snap

    def publish(self, editor, client, snap, *, paired=False, first_index=12):
        finished = copy.copy(snap)
        finished.vehicles = dict(snap.vehicles)
        primaries = []
        for number, probe in enumerate(editor.pending.probes):
            index = first_index + number * (2 if paired else 1)
            primary = vehicle(index, TRUCK if paired else CAR,
                              child=index + 1 if paired else None, node_index=10 + number)
            primary['progress'] = 200.0 - (number + 1) * editor.pending.gap
            primary['position'] = [primary['progress'], 10.0, 0.0]
            finished.vehicles[index] = primary
            if paired:
                finished.vehicles[index + 1] = vehicle(index + 1, TRAILER, parent=index)
            primaries.append(index)
            client.store(probe, struct.pack('<3I', 2, primary['address'], primary['node']))
        client.store(editor.pending.completion_address,struct.pack('<I',editor.pending.completion_token))
        client.store(s.HOOK,s.ORIGINAL)
        for row in finished.vehicles.values():
            client.store(row['address'], b'actor-sentinel')
            client.store(row['address'] + 0xA0, struct.pack('<I', row['id']))
        client.writes.clear()
        client.patch_calls.clear()
        return finished, primaries

    def poll_context(self, editor, client, snap, *, collider=None, align=None):
        stack = ExitStack()
        snapshot = stack.enter_context(patch.object(profile, 'snapshot', return_value=snap))
        checked = stack.enter_context(patch.object(batch, 'collider_valid', side_effect=collider or (lambda _m, _r: True)))

        def alignment(state, index, _lateral):
            row = state.vehicles[index]
            ids = [index] + ([row['child_id']] if row['child_id'] is not None else [])
            return [Patch(state.vehicles[i]['address'] + 0xA0, 4, i, i + 100) for i in ids]

        aligned = stack.enter_context(patch.object(profile, 'lateral_patches', side_effect=align or alignment))
        journal = stack.enter_context(patch.object(editor, '_journal'))
        return stack, snapshot, checked, aligned, journal

    def assert_clean_owned_only(self, editor, client, *, expected_recipe=0):
        self.assertIsNone(editor.pending)
        self.assertEqual(client.read_bytes(s.HOOK, 8), s.ORIGINAL)
        self.assertEqual(client.read_bytes(s.CAVE, 4096), s.clean_batch_scratch())
        self.assertEqual(len(editor.recipe), expected_recipe)
        self.assertEqual(editor.replay_queue, [])
        for address, data in client.writes:
            self.assertTrue((s.HOOK <= address and address + len(data) <= s.HOOK + 8)
                            or (s.CAVE <= address and address + len(data) <= s.END))

    def test_many_requests_install_one_scratch_and_one_hook(self):
        for count in (1, 3, 8):
            with self.subTest(count=count):
                editor, client, snap = self.fixture()
                _result, planned = self.stage(editor, client, snap, count=count)
                self.assertEqual(planned.call_count, count)
                self.assertEqual(len(editor.pending.probes), count)
                self.assertEqual(len(client.patch_calls), 1)
                self.assertEqual([p.address for p in client.patch_calls[0]], [s.HOOK, s.HOOK + 4])
                self.assertEqual([address for address, _ in client.writes], [s.CAVE, s.HOOK, s.HOOK + 4])
                self.assertEqual(editor.recipe, [])
                self.assertEqual(editor.actor_keys, {})

    def test_late_path_failure_leaves_every_byte_untouched(self):
        editor, client, snap = self.fixture()
        calls = []
        def behind(_memory, _path, progress, _lateral, gap, **_kwargs):
            self.assertEqual(client.writes, [])
            calls.append(progress)
            if len(calls) == 3:
                raise profile.ProfileError('Synthetic end of usable path')
            return progress - gap
        before = client.memory.copy()
        with self.assertRaises(profile.ProfileError):
            self.stage(editor, client, snap, behind=behind)
        self.assertEqual(len(calls), 3)
        self.assertEqual(client.writes, [])
        self.assertEqual(client.memory, before)
        self.assertIsNone(editor.pending)
        self.assertIsNone(editor.baseline)

    def test_all_pool_budgets_and_suppression_are_checked_before_writes(self):
        cases = [dict(free_objects=3), dict(free_nodes=2),
                 dict(active_objects=251), dict(suppressed=True)]
        for changes in cases:
            with self.subTest(changes=changes):
                editor, client, snap = self.fixture()
                if 'suppressed' in changes:
                    snap.memory.suppressed = True
                else:
                    snap.inspection['counts'].update(changes)
                with self.assertRaises(c.EditorError):
                    self.stage(editor, client, snap)
                self.assertEqual(client.writes, [])
                self.assertIsNone(editor.pending)
        editor, client, snap = self.fixture()
        snap.inspection['counts']['free_objects'] = 6  # Three pairs still need the allocator reserve.
        with self.assertRaises(c.EditorError):
            self.stage(editor, client, snap, paired=True)
        self.assertEqual(client.writes, [])

    def test_wrong_cargo_or_isolated_trailer_is_rejected_before_installation(self):
        for model, cargo in ((TRUCK, None), (TRUCK, OTHER_TRAILER),
                             (CAR, TRAILER), (TRAILER, None)):
            with self.subTest(model=model, cargo=cargo):
                editor, client, snap = self.fixture()
                with patch.object(profile, 'snapshot', return_value=snap), \
                     patch.object(profile, 'behind_progress') as geometry:
                    with self.assertRaises(c.EditorError):
                        editor.add_many_behind(9, model, 30, 2, cargo)
                geometry.assert_not_called()
                self.assertEqual(client.writes, [])

    def test_last_peer_conflict_is_found_before_any_installation(self):
        editor, client, snap = self.fixture()
        peer = vehicle(8)
        peer['position'] = [170.0, 10.0, 0.0]
        snap.vehicles[8] = peer
        with self.assertRaisesRegex(c.EditorError, 'existing vehicle'):
            self.stage(editor, client, snap)
        self.assertEqual(client.writes, [])
        self.assertIsNone(editor.pending)

    def test_all_done_states_are_required_even_when_paused(self):
        for last_state in (0, 1):
            with self.subTest(last_state=last_state):
                editor, client, snap = self.staged()
                final, _ids = self.publish(editor, client, snap)
                pending = editor.pending
                client.store(pending.probes[-1], struct.pack('<3I', last_state, 0, 0))
                before = client.memory.copy()
                context, snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context:
                    result = editor.poll()
                self.assertTrue(result['pending'])
                self.assertIs(editor.pending, pending)
                self.assertEqual(client.writes, [])
                self.assertEqual(client.memory, before)
                snapshot.assert_not_called()
                aligned.assert_not_called()
                self.assertEqual(editor.recipe, [])

    def test_running_complete_batch_waits_for_pause_without_cleaning(self):
        editor, client, snap = self.staged()
        final, _ids = self.publish(editor, client, snap)
        client.core_status = Status.RUNNING
        context, snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
        with context:
            result = editor.poll()
        self.assertEqual((result['pending'], result['core_paused']), (True, False))
        self.assertIn('3/3', result['message'])
        self.assertEqual(client.writes, [])
        snapshot.assert_not_called()
        aligned.assert_not_called()

    def test_vehicle_probes_done_do_not_allow_cleaning_before_code_retires(self):
        for hook_state in ('installed','delay_restored','original'):
            with self.subTest(hook_state=hook_state):
                editor,client,snap = self.staged()
                final,_ids = self.publish(editor,client,snap)
                pending = editor.pending
                client.store(pending.completion_address,struct.pack('<I',0))
                hook = {'installed':pending.hook,
                        'delay_restored':pending.hook[:4]+s.ORIGINAL[4:],
                        'original':s.ORIGINAL}[hook_state]
                client.store(s.HOOK,hook)
                before = client.memory.copy()
                context,snapshot,_collider,aligned,_journal = self.poll_context(editor,client,final)
                with context:
                    result = editor.poll()
                self.assertTrue(result['pending'])
                snapshot.assert_not_called()
                aligned.assert_not_called()
                self.assertEqual(client.memory,before)
                self.assertEqual(client.writes,[])

    def test_completion_without_retired_entry_is_rejected_before_actor_writes(self):
        editor,client,snap = self.staged()
        final,_ids = self.publish(editor,client,snap)
        client.store(s.HOOK,editor.pending.hook)
        context,snapshot,_collider,aligned,_journal = self.poll_context(editor,client,final)
        with context,self.assertRaisesRegex(c.EditorError,'without restoring'):
            editor.poll()
        snapshot.assert_not_called()
        aligned.assert_not_called()
        self.assertEqual(client.writes,[])

    def test_new_request_accepts_only_zero_or_exact_permanent_landing(self):
        for changed in (False,True):
            with self.subTest(changed=changed):
                editor,client,snap = self.fixture()
                client.store(s.CAVE,s.clean_batch_scratch())
                if changed:
                    client.memory[s.LANDING] ^= 1
                    with self.assertRaises(c.EditorError):
                        self.stage(editor,client,snap)
                    self.assertEqual(client.writes,[])
                else:
                    result,_planned = self.stage(editor,client,snap,count=1,
                        action=lambda: editor.add_behind(9,CAR,10))
                    self.assertTrue(result['pending'])
                    self.assertIsInstance(editor.pending,batch.BatchPending)

    def test_return_to_unfinished_request_before_alignment_blocks_actor_writes(self):
        for changed in ('completion','hook'):
            with self.subTest(changed=changed):
                editor,client,snap = self.staged(count=1)
                final,_ids = self.publish(editor,client,snap)
                pending = editor.pending
                def changed_after_snapshot(_snap,_index,_position):
                    if changed == 'completion':
                        client.store(pending.completion_address,struct.pack('<I',0))
                    else:
                        client.store(s.HOOK,pending.hook[:4]+s.ORIGINAL[4:])
                    return [Patch(final.vehicles[12]['address']+0xA0,4,12,112)]
                context,_snapshot,_collider,_aligned,_journal = self.poll_context(
                    editor,client,final,align=changed_after_snapshot)
                with context,self.assertRaisesRegex(c.EditorError,'has not finished yet'):
                    editor.poll()
                self.assertEqual(client.writes,[])
                self.assertEqual(editor.recipe,[])

    def test_success_assigns_primary_keys_and_chains_recipe_for_cars_and_pairs(self):
        for paired in (False, True):
            with self.subTest(paired=paired):
                editor, client, snap = self.staged(paired=paired)
                final, ids = self.publish(editor, client, snap, paired=paired)
                context, snapshot, checked, aligned, journal = self.poll_context(editor, client, final)
                with context:
                    result = editor.poll()
                self.assertEqual(result['new_vehicle_ids'], ids)
                self.assertEqual(result['new_vehicle_id'], ids[-1])
                self.assertEqual((result['pending'], result['core_paused']), (False, True))
                self.assertIsNone(editor.pending)
                self.assertEqual(editor.actor_keys, dict(zip(ids, (1, 2, 3))))
                self.assertEqual(editor.replay_ids, dict(zip((1, 2, 3), ids)))
                self.assertEqual(editor.next_key, 4)
                self.assertEqual([call.args[1] for call in aligned.call_args_list], ids)
                self.assertEqual(checked.call_count, 6 if paired else 3)
                snapshot.assert_called_once_with(client, require_paused=True, allow_editor_hook=True)
                self.assertEqual(client.read_bytes(s.HOOK, 8), s.ORIGINAL)
                self.assertEqual(client.read_bytes(s.CAVE, 4096), s.clean_batch_scratch())
                for number, operation in enumerate(editor.recipe):
                    target = ({'kind': 'initial', 'id': 9, 'model_id': CAR, 'path': PATH}
                              if number == 0 else {'kind': 'created', 'key': number})
                    self.assertEqual(operation['target'], target)
                    self.assertEqual(operation['created_key'], number + 1)
                    self.assertEqual(operation['model_id'], TRUCK if paired else CAR)
                    self.assertEqual(operation.get('secondary_model_id'), TRAILER if paired else None)
                self.assertEqual(journal.call_args.args, ('batch_finished',))
                before = list(client.writes)
                self.assertFalse(editor.poll()['pending'])
                self.assertEqual(client.writes, before)

    def test_replay_groups_a_creation_chain_and_preserves_supplied_keys(self):
        editor, client, snap = self.fixture()
        initial = {'kind': 'initial', 'id': 9, 'model_id': CAR, 'path': PATH}
        editor.replay_queue = [
            {'op': 'add_behind', 'target': initial, 'model_id': CAR, 'gap': 10, 'created_key': 10},
            {'op': 'add_behind', 'target': {'kind': 'created', 'key': 10},
             'model_id': CAR, 'gap': 10, 'created_key': 11},
            {'op': 'add_behind', 'target': {'kind': 'created', 'key': 11},
             'model_id': CAR, 'gap': 10, 'created_key': 12},
        ]
        expected_operations = copy.deepcopy(editor.replay_queue)
        result, planned = self.stage(editor, client, snap, action=editor._continue_recipe)
        self.assertTrue(result['pending'])
        self.assertEqual(planned.call_count, 3)
        self.assertEqual(editor.pending.created_keys, [10, 11, 12])
        self.assertEqual(editor.replay_queue, [])
        self.assertEqual(len(client.patch_calls), 1)
        final, ids = self.publish(editor, client, snap)
        context, _snapshot, _collider, _aligned, _journal = self.poll_context(editor, client, final)
        with context:
            editor.poll()
        self.assertEqual(editor.recipe, expected_operations)
        self.assertEqual(editor.actor_keys, dict(zip(ids, (10, 11, 12))))
        self.assertEqual(editor.replay_ids, dict(zip((10, 11, 12), ids)))
        self.assertEqual(editor.next_key, 13)
        self.assertEqual(editor._resolve({'kind': 'created', 'key': 12}, final,
                                         for_creation=True), ids[-1])

    def test_null_allocation_cleans_owned_code_without_alignment_recipe_or_retry(self):
        editor, client, snap = self.staged()
        final, _ids = self.publish(editor, client, snap)
        pending = editor.pending
        editor.replay_queue = [{'op': 'move_lateral'}]
        client.store(pending.probes[1], struct.pack('<3I', 2, 0, 0))
        context, _snapshot, _collider, aligned, journal = self.poll_context(editor, client, final)
        with context:
            result = editor.poll()
        self.assertTrue(result['warning'])
        self.assert_clean_owned_only(editor, client)
        aligned.assert_not_called()
        self.assertEqual(editor.actor_keys, {})
        self.assertEqual(editor.replay_ids, {})
        self.assertEqual(journal.call_args.args, ('batch_not_finalized',))
        for row in final.vehicles.values():
            self.assertEqual(client.read_bytes(row['address'], 14), b'actor-sentinel')
        before = list(client.writes)
        editor.poll()
        self.assertEqual(client.writes, before)

    def test_changed_car_identity_or_duplicate_publication_never_aligns(self):
        cases = ('missing', 'model_hash', 'node', 'path', 'type', 'independent', 'duplicate', 'old')
        for changed in cases:
            with self.subTest(changed=changed):
                editor, client, snap = self.staged()
                final, ids = self.publish(editor, client, snap)
                row = final.vehicles[ids[1]]
                if changed == 'missing':
                    del final.vehicles[ids[1]]
                elif changed == 'duplicate':
                    first = final.vehicles[ids[0]]
                    client.store(editor.pending.probes[1], struct.pack('<3I', 2, first['address'], first['node']))
                elif changed == 'old':
                    old = final.vehicles[9]
                    client.store(editor.pending.probes[1], struct.pack('<3I', 2, old['address'], old['node']))
                elif changed == 'independent':
                    row[changed] = False
                else:
                    row[changed] += 1
                context, _snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context:
                    result = editor.poll()
                self.assertTrue(result['warning'])
                aligned.assert_not_called()
                self.assert_clean_owned_only(editor, client)

    def test_wrong_secondary_identity_or_link_never_aligns_either_body(self):
        for changed in ('missing', 'model_hash', 'parent_id', 'type', 'node', 'native_pair_valid'):
            with self.subTest(changed=changed):
                editor, client, snap = self.staged(paired=True)
                final, ids = self.publish(editor, client, snap, paired=True)
                primary = final.vehicles[ids[1]]
                child = final.vehicles[primary['child_id']]
                if changed == 'missing':
                    del final.vehicles[child['id']]
                elif changed == 'native_pair_valid':
                    primary[changed] = False
                else:
                    child[changed] += 1
                context, _snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context:
                    result = editor.poll()
                self.assertTrue(result['warning'])
                aligned.assert_not_called()
                self.assert_clean_owned_only(editor, client)

    def test_nonready_physics_waits_and_bad_collider_cleans_without_alignment(self):
        for paired in (False, True):
            with self.subTest(paired=paired):
                editor, client, snap = self.staged(paired=paired)
                final, ids = self.publish(editor, client, snap, paired=paired)
                index = ids[-1] + (1 if paired else 0)
                final.vehicles[index]['initialized'] = False
                context, _snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context:
                    waiting = editor.poll()
                self.assertTrue(waiting['pending'])
                aligned.assert_not_called()
                self.assertEqual(client.writes, [])
                final.vehicles[index]['initialized'] = True
                context, _snapshot, _collider, aligned, _journal = self.poll_context(
                    editor, client, final, collider=lambda _memory, row: row['id'] != index)
                with context:
                    rejected = editor.poll()
                self.assertTrue(rejected['warning'])
                aligned.assert_not_called()
                self.assert_clean_owned_only(editor, client)

    def test_physics_becoming_ready_during_the_wait_finalizes_the_whole_lot(self):
        for paired in (False, True):
            with self.subTest(paired=paired):
                editor, client, snap = self.staged(paired=paired)
                final, ids = self.publish(editor, client, snap, paired=paired)
                index = ids[-1] + (1 if paired else 0)
                final.vehicles[index]['initialized'] = False
                pending = editor.pending
                # The physics timer starts after retirement, independently of
                # how long the user took to run the staged native requests.
                pending.staged_at = -100000.
                context, _snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context, patch.object(batch.time, 'monotonic', return_value=100.):
                    self.assertTrue(editor.poll()['pending'])
                    self.assertEqual(pending.physics_wait_started, 100.)
                    aligned.assert_not_called()
                    self.assertEqual(client.writes, [])
                final.vehicles[index]['initialized'] = True
                context, _snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context, patch.object(batch.time, 'monotonic', return_value=104.):
                    result = editor.poll()
                self.assertFalse(result['pending'])
                self.assertEqual(result['new_vehicle_ids'], ids)
                self.assertEqual(aligned.call_count, len(ids))
                self.assertEqual(len(editor.recipe), len(ids))
                self.assertEqual(set(editor.actor_keys), set(ids))
                self.assertIsNone(editor.pending)

    def test_permanently_cold_primary_or_cargo_releases_only_retired_code(self):
        for paired in (False, True):
            with self.subTest(paired=paired):
                editor, client, snap = self.staged(paired=paired)
                final, ids = self.publish(editor, client, snap, paired=paired)
                cold = [ids[-1] + (1 if paired else 0), ids[0]]
                for index in cold:
                    final.vehicles[index]['initialized'] = False
                before = {row['id']: client.read_bytes(row['address'] + 0xA0, 4)
                          for row in final.vehicles.values()}
                editor.replay_queue = [{'op':'must_not_run'}]
                context, _snapshot, _collider, aligned, journal = self.poll_context(editor, client, final)
                with context, patch.object(batch.time, 'monotonic') as clock:
                    clock.return_value = 100.
                    self.assertTrue(editor.poll()['pending'])
                    clock.return_value = 100. + batch.PHYSICS_WAIT_SECONDS - .01
                    self.assertTrue(editor.poll()['pending'])
                    self.assertEqual(client.writes, [])
                    clock.return_value = 100. + batch.PHYSICS_WAIT_SECONDS
                    result = editor.poll()
                self.assertFalse(result['pending'])
                self.assertTrue(result['warning'])
                self.assertIn('were kept', result['message'])
                aligned.assert_not_called()
                self.assertEqual(client.patch_calls, [])
                self.assert_clean_owned_only(editor, client)
                self.assertFalse(editor.unsafe)
                self.assertEqual(editor.actor_keys, {})
                self.assertEqual(editor.replay_ids, {})
                for row in final.vehicles.values():
                    self.assertEqual(client.read_bytes(row['address'] + 0xA0, 4), before[row['id']])
                finished = [call for call in journal.call_args_list if call.args == ('batch_not_finalized',)]
                self.assertEqual(len(finished), 1)
                self.assertEqual(finished[0].kwargs['reason'], 'physics_not_ready')
                self.assertEqual(set(finished[0].kwargs['vehicle_ids']), set(cold))
                self.assertEqual(finished[0].kwargs['physics_wait_polls'], 3)

    def test_profile_or_alignment_rejection_after_retirement_cannot_wait_forever(self):
        for rejection in ('snapshot', 'primary_collider', 'cargo_collider', 'alignment'):
            with self.subTest(rejection=rejection):
                paired = rejection == 'cargo_collider'
                editor, client, snap = self.staged(paired=paired)
                final, ids = self.publish(editor, client, snap, paired=paired)
                context, snapshot, collider, aligned, journal = self.poll_context(editor, client, final)
                if rejection == 'snapshot':
                    snapshot.side_effect = profile.ProfileError('Synthetic active pool changed')
                elif 'collider' in rejection:
                    collider.side_effect = profile.ProfileError('Synthetic collider is not ready')
                else:
                    def incomplete_alignment(state, index, _lateral):
                        if index == ids[0]:
                            return [Patch(state.vehicles[index]['address'] + 0xA0, 4, index, index + 100)]
                        raise profile.ProfileError('Synthetic physics is not editable')
                    aligned.side_effect = incomplete_alignment
                with context, patch.object(batch.time, 'monotonic') as clock:
                    clock.return_value = 100.
                    self.assertTrue(editor.poll()['pending'])
                    self.assertEqual(client.writes, [])
                    clock.return_value = 100. + batch.PHYSICS_WAIT_SECONDS
                    result = editor.poll()
                self.assertFalse(result['pending'])
                self.assertTrue(result['warning'])
                self.assertEqual(client.patch_calls, [])
                self.assert_clean_owned_only(editor, client)
                finished = [call for call in journal.call_args_list if call.args == ('batch_not_finalized',)]
                self.assertEqual(finished[0].kwargs['reason'],
                                 'alignment_not_ready' if rejection == 'alignment' else 'profile_not_ready')

    def test_expired_physics_wait_does_not_bypass_ownership_or_read_errors(self):
        for failure in ('tampered_code', 'read_failed', 'snapshot_transport_failed'):
            with self.subTest(failure=failure):
                editor, client, snap = self.staged()
                final, ids = self.publish(editor, client, snap)
                final.vehicles[ids[-1]]['initialized'] = False
                pending = editor.pending
                context, _snapshot, _collider, _aligned, _journal = self.poll_context(editor, client, final)
                with context, patch.object(batch.time, 'monotonic', return_value=100.):
                    self.assertTrue(editor.poll()['pending'])
                context, snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                if failure == 'tampered_code':
                    client.memory[s.NONCE_ADDRESS] ^= 1
                elif failure == 'snapshot_transport_failed':
                    snapshot.side_effect = PineError('Synthetic snapshot transport failure')
                with context, patch.object(batch.time, 'monotonic', return_value=200.), ExitStack() as errors:
                    if failure == 'read_failed':
                        errors.enter_context(patch.object(client, 'read_bytes',
                            side_effect=PineError('Synthetic read failure')))
                    with self.assertRaises((c.EditorError, PineError)):
                        editor.poll()
                self.assertIs(editor.pending, pending)
                self.assertEqual(client.writes, [])
                aligned.assert_not_called()
                self.assertEqual(editor.recipe, [])

    def test_expired_physics_wait_never_cleans_an_active_or_unretired_request(self):
        for state in ('running', 'probe_incomplete', 'master_unretired', 'hook_active'):
            with self.subTest(state=state):
                editor, client, snap = self.staged()
                final, ids = self.publish(editor, client, snap)
                final.vehicles[ids[-1]]['initialized'] = False
                pending = editor.pending
                context, _snapshot, _collider, _aligned, _journal = self.poll_context(editor, client, final)
                with context, patch.object(batch.time, 'monotonic', return_value=100.):
                    self.assertTrue(editor.poll()['pending'])
                if state == 'running':
                    client.core_status = Status.RUNNING
                elif state == 'probe_incomplete':
                    client.store(pending.probes[-1], struct.pack('<I', 1))
                elif state == 'master_unretired':
                    client.store(pending.completion_address, struct.pack('<I', 0))
                else:
                    client.store(s.HOOK, pending.hook)
                context, snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context, patch.object(batch.time, 'monotonic', return_value=200.):
                    if state == 'hook_active':
                        with self.assertRaises(c.EditorError):
                            editor.poll()
                    else:
                        self.assertTrue(editor.poll()['pending'])
                self.assertIs(editor.pending, pending)
                self.assertEqual(client.writes, [])
                self.assertEqual(client.patch_calls, [])
                self.assertEqual(editor.recipe, [])
                snapshot.assert_not_called()
                aligned.assert_not_called()

    def test_tampered_hook_code_record_arguments_or_nonce_blocks_all_writes(self):
        addresses = [s.HOOK, s.NONCE_ADDRESS, s.DATA + 0x0C, s.LANDING]
        for number in range(3):
            addresses += [s.CAVE + number * s.BATCH_CODE_STRIDE + 0x10,
                          s.BATCH_RECORD_BASE + number * s.BATCH_RECORD_STRIDE + 0x18,
                          s.BATCH_RECORD_BASE + number * s.BATCH_RECORD_STRIDE + 0x68]
        for address in addresses:
            with self.subTest(address=hex(address)):
                editor, client, snap = self.staged()
                final, _ids = self.publish(editor, client, snap)
                pending = editor.pending
                client.memory[address] ^= 1
                before = client.memory.copy()
                context, snapshot, _collider, aligned, _journal = self.poll_context(editor, client, final)
                with context, self.assertRaises(c.EditorError):
                    editor.poll()
                snapshot.assert_not_called()
                aligned.assert_not_called()
                self.assertEqual(client.writes, [])
                self.assertEqual(client.memory, before)
                self.assertIs(editor.pending, pending)

    def test_unconfirmed_stage_is_not_retried(self):
        editor, client, snap = self.fixture()
        with patch.object(client, 'apply_patch', side_effect=PineVerificationError('Synthetic install failure')):
            with self.assertRaises(c.EditorError):
                self.stage(editor, client, snap)
        self.assertTrue(editor.unsafe)
        self.assertIsNotNone(editor.pending)
        before = list(client.writes)
        with self.assertRaises(c.EditorError):
            editor.poll()
        self.assertEqual(client.writes, before)
        self.assertEqual(editor.recipe, [])

    def test_unconfirmed_cleanup_keeps_pending_and_cannot_commit_or_retry(self):
        editor, client, snap = self.staged()
        final, _ids = self.publish(editor, client, snap)
        pending = editor.pending
        client.fail_cleanup = True
        context, _snapshot, _collider, _aligned, _journal = self.poll_context(editor, client, final)
        with context, self.assertRaises(c.EditorError):
            editor.poll()
        self.assertTrue(editor.unsafe)
        self.assertIs(editor.pending, pending)
        self.assertEqual(editor.recipe, [])
        self.assertEqual(editor.actor_keys, {})
        self.assertEqual(editor.replay_ids, {})
        before = list(client.writes)
        with self.assertRaises(c.EditorError):
            editor.poll()
        self.assertEqual(client.writes, before)


if __name__ == '__main__':
    unittest.main()
