"""Heterogeneous native batches, visual arguments and recipe ordering."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import batch,controller as c,profile,spawncode as s
import test_batch as fixtures

VAN='TEST_VAN'
VAN_HASH=0x1029384756ABCDEF


class MixedBatchTests(unittest.TestCase):
    def setUp(self):
        self.helper=fixtures.BatchControllerTests()

    def fixture(self):
        editor,client,snap=self.helper.fixture()
        snap.models[VAN]=dict(eligible=True,type=3,model_hash=VAN_HASH)
        return editor,client,snap

    def stage(self,*,count=4,color='cycle',choices=None,experimental=False):
        editor,client,snap=self.fixture()
        self.helper.stage(editor,client,snap,count=min(count,8),action=lambda:
            editor.add_mixed_behind(9,choices or [dict(model_id=fixtures.CAR),dict(model_id=VAN)],
                                   10,count,color_mode=color,experimental=experimental))
        return editor,client,snap

    def publish(self,editor,client,snap):
        final=copy.copy(snap)
        final.vehicles=dict(snap.vehicles)
        for number,(probe,item) in enumerate(zip(editor.pending.probes,editor.pending.items)):
            index=max(final.vehicles)+1
            child_id=index+1 if item['secondary_model_id'] is not None else None
            row=fixtures.vehicle(index,fixtures.TRUCK if child_id else fixtures.CAR,
                                 child=child_id,node_index=100+number)
            row.update(model_id=item['model_id'],model_hash=item['model_hash'],type=item['type'],
                       progress=200-(number+1)*editor.pending.gap,position=[200-(number+1)*editor.pending.gap,10.,0.])
            final.vehicles[index]=row
            if child_id is not None:
                child=fixtures.vehicle(child_id,fixtures.TRAILER,parent=index)
                final.vehicles[child_id]=child
                client.store(child['address'],b'actor-sentinel')
            client.store(probe,struct.pack('<3I',2,row['address'],row['node']))
            client.store(row['address'],b'actor-sentinel')
            client.store(row['address']+0xA0,struct.pack('<I',index))
        client.store(editor.pending.completion_address,struct.pack('<I',editor.pending.completion_token))
        client.store(s.HOOK,s.ORIGINAL)
        client.writes.clear()
        client.patch_calls.clear()
        return final

    def context(self,editor,client,snap):
        context,*other=self.helper.poll_context(editor,client,snap,align=lambda *_a,**_k:[])
        return context,other

    def test_native_requests_alternate_models_types_and_visual_indices(self):
        editor,_client,_snap=self.stage(count=4)
        pending=editor.pending
        requests=s.match_batch_scratch(pending.scratch,bytes.fromhex(pending.nonce))['requests']
        self.assertEqual([r['model_hash'] for r in requests],[fixtures.HASHES[fixtures.CAR],VAN_HASH]*2)
        self.assertEqual([r['type_code'] for r in requests],[1,3]*2)
        self.assertEqual([r['variant'] for r in requests],[0,1,2,3])
        self.assertEqual(len(pending.probes),4)

    def test_completed_mixed_batch_records_each_actual_model_and_variant(self):
        editor,client,snap=self.stage()
        final=self.publish(editor,client,snap)
        context,_other=self.context(editor,client,final)
        with context:
            result=editor.poll()
        self.assertFalse(result['pending'])
        self.assertEqual([op['model_id'] for op in editor.recipe],[fixtures.CAR,VAN]*2)
        self.assertEqual([op.get('variant',0) for op in editor.recipe],[0,1,2,3])
        self.assertEqual([op['target']['kind'] for op in editor.recipe],['initial','created','created','created'])
        self.assertEqual(client.read_bytes(s.CAVE,4096),s.clean_batch_scratch())

    def test_wrong_later_instance_cleans_code_without_alignment_or_recipe(self):
        editor,client,snap=self.stage()
        final=self.publish(editor,client,snap)
        final.vehicles[max(final.vehicles)]['model_hash']^=1
        context,other=self.context(editor,client,final)
        with context:
            result=editor.poll()
        self.assertTrue(result['warning'])
        self.assertFalse(result['pending'])
        self.assertEqual(editor.recipe,[])
        other[2].assert_not_called()
        self.assertTrue(all(address==s.CAVE for address,_ in client.writes))

    def test_bad_later_choice_bus_spacing_or_total_pair_budget_causes_no_write(self):
        for failure in ('model','bus','capacity','color','choice'):
            with self.subTest(failure=failure):
                editor,client,snap=self.fixture()
                choices=[dict(model_id=fixtures.CAR),dict(model_id=VAN)]
                count=4
                color='cycle'
                if failure=='model': choices.append(dict(model_id='MISSING'))
                elif failure=='bus': snap.models[VAN]['type']=5
                elif failure=='capacity': snap.inspection['counts']['free_objects']=4
                elif failure=='color': color='red'
                else: choices[1]['variant']=3
                with self.assertRaises(c.EditorError):
                    self.helper.stage(editor,client,snap,action=lambda:
                        editor.add_mixed_behind(9,choices,10,count,color_mode=color))
                self.assertEqual(client.writes,[])
                self.assertIsNone(editor.pending)

    def test_queue_keeps_global_sequence_and_replays_as_another_mixed_group(self):
        editor,client,snap=self.stage(count=10,experimental=True)
        self.assertEqual([op['model_id'] for op in editor.replay_queue],[fixtures.CAR,VAN])
        self.assertEqual([op.get('variant',0) for op in editor.replay_queue],[0,1])
        final=self.publish(editor,client,snap)
        context,_other=self.context(editor,client,final)
        with context,patch.object(batch,'_state_digest',return_value='synthetic'), \
             patch.object(profile,'lane',side_effect=lambda _m,_p,progress,_l:dict(point=[progress,10.,0.],lane=[0.,0.,10.])), \
             patch.object(profile,'behind_progress',side_effect=lambda _m,_p,progress,_l,gap,**_k:progress-gap):
            result=editor.poll()
        self.assertTrue(result['pending'])
        self.assertEqual(len(editor.recipe),8)
        self.assertEqual([item['model_id'] for item in editor.pending.items],[fixtures.CAR,VAN])
        self.assertEqual([item['variant'] for item in editor.pending.items],[0,1])
        self.assertEqual(editor.replay_queue,[])

    def test_existing_single_model_api_can_cycle_visual_arguments(self):
        editor,client,snap=self.fixture()
        self.helper.stage(editor,client,snap,action=lambda:
            editor.add_many_behind(9,fixtures.CAR,10,3,color_mode='cycle'))
        self.assertEqual([item['model_id'] for item in editor.pending.items],[fixtures.CAR]*3)
        self.assertEqual([item['variant'] for item in editor.pending.items],[0,1,2])

    def test_alternating_car_and_native_truck_preserves_compound_requests_and_recipe(self):
        editor,client,snap=self.fixture()
        choices=[dict(model_id=fixtures.CAR),dict(model_id=fixtures.TRUCK,secondary_model_id=fixtures.TRAILER)]
        self.helper.stage(editor,client,snap,action=lambda:
            editor.add_mixed_behind(9,choices,30,4,color_mode='cycle'))
        requests=s.match_batch_scratch(editor.pending.scratch,bytes.fromhex(editor.pending.nonce))['requests']
        self.assertEqual([r['type_code'] for r in requests],[1,4,1,4])
        self.assertEqual([r['secondary_type_code'] for r in requests],[0,11,0,11])
        final=self.publish(editor,client,snap)
        context,_other=self.context(editor,client,final)
        with context: result=editor.poll()
        self.assertFalse(result['pending'])
        self.assertEqual([op.get('secondary_model_id') for op in editor.recipe],[None,fixtures.TRAILER,None,fixtures.TRAILER])

    def test_reservation_counts_cargo_objects_before_installing_first_group(self):
        editor,client,snap=self.fixture()
        snap.inspection['counts']['free_objects']=6
        choices=[dict(model_id=fixtures.CAR),dict(model_id=fixtures.TRUCK,secondary_model_id=fixtures.TRAILER)]
        with self.assertRaisesRegex(c.EditorError,'pools'):
            self.helper.stage(editor,client,snap,action=lambda:
                editor.add_mixed_behind(9,choices,30,4))
        self.assertEqual(client.writes,[])

    def test_saved_mixed_recipe_replays_as_one_heterogeneous_group(self):
        editor,client,snap=self.stage()
        final=self.publish(editor,client,snap)
        context,_other=self.context(editor,client,final)
        with context: editor.poll()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mixed.json'
            editor.save_preset(str(path))
            replay,other,initial=self.fixture()
            with patch.object(profile,'snapshot',return_value=initial), \
                 patch.object(batch,'_state_digest',return_value='synthetic'), \
                 patch.object(profile,'lane',side_effect=lambda _m,_p,progress,_l:dict(point=[progress,10.,0.],lane=[0.,0.,10.])), \
                 patch.object(profile,'behind_progress',side_effect=lambda _m,_p,progress,_l,gap,**_k:progress-gap):
                self.assertTrue(replay.load_preset(str(path))['pending'])
            self.assertEqual([item['model_id'] for item in replay.pending.items],[fixtures.CAR,VAN]*2)
            self.assertEqual([item['variant'] for item in replay.pending.items],[0,1,2,3])

    def test_bad_later_visual_variant_rejected_before_preset_mutations(self):
        editor,client,snap=self.fixture()
        ref=dict(kind='initial',id=9,model_id=fixtures.CAR,path=fixtures.PATH)
        operations=[dict(op='add_behind',target=ref,model_id=fixtures.CAR,gap=10,created_key=1),
                    dict(op='add_behind',target=dict(kind='created',key=1),model_id=VAN,gap=10,created_key=2,variant=8)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json'
            path.write_text(json.dumps(dict(format='burnout3-current-event-recipe',version=1,
                profile='SLUS-21050/BEBF8793',baseline=c._fingerprint(snap),operations=operations)),encoding='utf8')
            with patch.object(profile,'snapshot',return_value=snap),self.assertRaisesRegex(c.EditorError,'visual variant'):
                editor.load_preset(str(path))
        self.assertEqual(client.writes,[])


if __name__=='__main__':
    unittest.main()
