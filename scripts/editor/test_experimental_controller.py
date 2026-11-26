"""Experimental controls retain pool/code guards and queue without duplication."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import batch,controller as c,placement,profile,spawncode
from editor.pine import Patch
import test_batch as fixtures


class ExperimentalControllerTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixtures.BatchControllerTests()

    @staticmethod
    def align(state,index,_lateral,**_options):
        row = state.vehicles[index]
        return [Patch(row['address']+0xA0,4,index,index+100)]

    def stage_many(self,editor,client,snap,count=9,gap=1):
        return self.helper.stage(editor,client,snap,
            action=lambda:editor.add_many_behind(9,fixtures.CAR,gap,count,experimental=True))

    def test_large_request_uses_successive_groups_and_records_each_actor_once(self):
        editor,client,snap = self.helper.fixture()
        result,_planned = self.stage_many(editor,client,snap)
        self.assertTrue(result['pending'])
        self.assertEqual(len(editor.pending.probes),8)
        self.assertEqual(len(editor.replay_queue),1)
        final,_ids = self.helper.publish(editor,client,snap)
        context,*_ = self.helper.poll_context(editor,client,final,align=self.align)
        with context,patch.object(profile,'behind_progress',side_effect=lambda _m,_p,t,_l,g,**kw:t-g), \
             patch.object(profile,'lane',side_effect=lambda _m,_p,t,_l:{'point':[t,10.,0.]}), \
             patch.object(batch,'_state_digest',return_value='recovery'):
            next_group = editor.poll()
        self.assertTrue(next_group['pending'])
        self.assertEqual(editor.pending.created_keys,[9])
        self.assertEqual(len(editor.recipe),8)
        self.assertEqual(editor.replay_queue,[])
        last,_ids = self.helper.publish(editor,client,final,first_index=20)
        context,*_ = self.helper.poll_context(editor,client,last,align=self.align)
        with context:
            result = editor.poll()
        self.assertFalse(result['pending'])
        self.assertEqual(len(editor.recipe),9)
        self.assertEqual([r['created_key'] for r in editor.recipe],list(range(1,10)))
        self.assertTrue(all(r['experimental'] for r in editor.recipe))
        self.assertEqual(len(editor.actor_keys),9)

    def test_full_request_capacity_is_checked_before_the_first_group(self):
        editor,client,snap = self.helper.fixture()
        snap.inspection['counts']['free_objects'] = 9
        with self.assertRaisesRegex(c.EditorError,'pools'):
            self.stage_many(editor,client,snap)
        self.assertEqual(client.writes,[])
        self.assertIsNone(editor.pending)

    def test_experimental_flag_relaxes_spacing_but_not_unknown_code(self):
        editor,client,snap = self.helper.fixture()
        client.memory[spawncode.HOOK] ^= 1
        with self.assertRaisesRegex(c.EditorError,'code'):
            self.stage_many(editor,client,snap,count=1,gap=.1)
        self.assertEqual(client.writes,[])

    def test_cancel_queue_keeps_current_request_and_never_allocates_again(self):
        editor,client,snap = self.helper.fixture()
        self.stage_many(editor,client,snap,count=17)
        pending,before = editor.pending,list(client.writes)
        result = editor.cancel_queue()
        self.assertTrue(result['pending'])
        self.assertIs(editor.pending,pending)
        self.assertEqual(editor.replay_queue,[])
        self.assertEqual(client.writes,before)

    def test_late_queue_failure_preserves_completed_group_without_retry(self):
        editor,client,snap = self.helper.fixture()
        self.stage_many(editor,client,snap)
        final,_ids = self.helper.publish(editor,client,snap)
        context,*_ = self.helper.poll_context(editor,client,final,align=self.align)
        with context,patch.object(editor,'_continue_recipe',side_effect=c.EditorError('Next group no longer fits')):
            result = editor.poll()
        self.assertTrue(result['warning'])
        self.assertFalse(result['pending'])
        self.assertEqual(len(editor.recipe),8)
        self.assertEqual(editor.replay_queue,[])
        self.assertEqual(client.read_bytes(spawncode.CAVE,4096),spawncode.clean_batch_scratch())

    def test_native_point_request_uses_projection_instead_of_behind_distance(self):
        editor,client,snap = self.helper.fixture()
        projected = dict(reference_id=9,path=fixtures.PATH,progression=150.,lateral=.8,
                         point=[150.,10.,0.],error_distance=.25)
        with patch.object(placement,'project_target',return_value=projected) as projector:
            result,planned = self.helper.stage(editor,client,snap,
                action=lambda:editor.add_at(9,fixtures.CAR,150,2))
        planned.assert_not_called()
        projector.assert_called_once_with(snap,None,150,2,experimental=False)
        matched = spawncode.match_batch_scratch(editor.pending.scratch,bytes.fromhex(editor.pending.nonce))
        self.assertEqual(matched['requests'][0]['progression'],150.)
        self.assertEqual(editor.pending.lateral,.8)
        self.assertTrue(result['pending'])
        final,_ids = self.helper.publish(editor,client,snap)
        context,*_ = self.helper.poll_context(editor,client,final,align=self.align)
        with context:
            editor.poll()
        self.assertEqual(editor.recipe[0]['op'],'add_at')
        self.assertEqual((editor.recipe[0]['x'],editor.recipe[0]['z']),(150,2))

    def test_distant_normal_point_is_rejected_without_writing(self):
        editor,client,snap = self.helper.fixture()
        with patch.object(placement,'project_target',return_value={'error_distance':26}):
            with self.assertRaisesRegex(c.EditorError,'far from'):
                self.helper.stage(editor,client,snap,action=lambda:editor.add_at(9,fixtures.CAR,1,2))
        self.assertEqual(client.writes,[])

    def test_experimental_recipe_requires_current_explicit_opt_in(self):
        editor,client,snap = self.helper.fixture()
        payload = dict(format='burnout3-current-event-recipe',version=1,profile='SLUS-21050/BEBF8793',
            baseline=c._fingerprint(snap),operations=[dict(op='add_behind',
                target={'kind':'initial','id':9,'model_id':fixtures.CAR,'path':fixtures.PATH},
                model_id=fixtures.CAR,gap=1,created_key=1,experimental=True)])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'experimental.json'
            path.write_text(json.dumps(payload),encoding='utf8')
            with patch.object(profile,'snapshot',return_value=snap):
                with self.assertRaisesRegex(c.EditorError,'Enable'):
                    editor.load_preset(path)
            self.assertEqual(client.writes,[])
            result,_planned=self.helper.stage(editor,client,snap,
                action=lambda:editor.load_preset(path,experimental=True))
            self.assertTrue(result['pending'])

    def test_invalid_later_fraction_in_recipe_cannot_apply_an_earlier_move(self):
        editor,client,snap=self.helper.fixture()
        ref={'kind':'initial','id':9,'model_id':fixtures.CAR,'path':fixtures.PATH}
        data=dict(format='burnout3-current-event-recipe',version=1,profile='SLUS-21050/BEBF8793',
            baseline=c._fingerprint(snap),operations=[
                dict(op='move_lateral',target=ref,lateral_percent=55),
                dict(op='move_lateral',target=ref,lateral_percent=1e308,experimental=True)])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad-later-position.json'
            path.write_text(json.dumps(data),encoding='utf8')
            with patch.object(profile,'snapshot',return_value=snap), \
                 patch.object(editor,'move',side_effect=AssertionError('No earlier mutation')):
                with self.assertRaisesRegex(c.EditorError,'float32'):
                    editor.load_preset(path,experimental=True)
        self.assertEqual(client.writes,[])

    def test_point_replay_locks_the_path_reference_recorded_in_the_recipe(self):
        editor,client,snap=self.helper.fixture()
        editor.replay_queue=[dict(op='add_at',
            target={'kind':'initial','id':9,'model_id':fixtures.CAR,'path':fixtures.PATH},
            model_id=fixtures.CAR,x=150,z=2,created_key=1)]
        projected=dict(reference_id=9,path=fixtures.PATH,progression=150.,lateral=.8,
            point=[150.,10.,0.],error_distance=.25)
        with patch.object(placement,'project_target',return_value=projected) as projector:
            self.helper.stage(editor,client,snap,action=editor._continue_recipe)
        projector.assert_called_once_with(snap,9,150,2,experimental=False)

    def test_wide_normal_point_is_refused_before_native_allocation(self):
        editor,client,snap=self.helper.fixture()
        projected=dict(reference_id=9,path=fixtures.PATH,progression=150.,lateral=.8,
            point=[150.,10.,0.],error_distance=0.)
        with patch.object(profile,'snapshot',return_value=snap), \
             patch.object(profile,'lane',return_value={'point':[200.,10.,0.],'lane':[0.,0.,30.]}), \
             patch.object(placement,'project_target',return_value=projected):
            with self.assertRaisesRegex(c.EditorError,'large lateral offset'):
                editor.add_at(9,fixtures.CAR,150,2)
        self.assertEqual(client.writes,[])


if __name__ == '__main__':
    unittest.main()
