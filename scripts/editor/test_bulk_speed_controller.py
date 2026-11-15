"""Controller speed batches use synthetic actors, with no emulator or assets."""
from contextlib import ExitStack
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import controller as c, profile
from editor.pine import PineVerificationError
from test_controller import SparseClient
import test_speed as speed_fixtures


class BulkSpeedControllerTests(unittest.TestCase):
    def fixture(self):
        state=speed_fixtures.SpeedTests().multiple_fixture()
        for row in state.vehicles.values():
            row.update(model_id=f"TEST_{row['id']}",lateral=.5,position=[20.,0.,0.])
        client=SparseClient.__new__(SparseClient)
        client.memory=state.memory.data
        client.writes=[]
        client.fail_cleanup=False
        editor=c.EditorController(client=client)
        def snapshot(*_args,**_kwargs):
            for row in state.vehicles.values():
                row['speed']=state.memory.read(row['node'],'<f')[0]
            return state
        stack=ExitStack()
        stack.enter_context(patch.object(profile,'snapshot',side_effect=snapshot))
        stack.enter_context(patch.object(c,'_state_digest',return_value='synthetic-digest'))
        self.addCleanup(stack.close)
        return editor,client,state

    def test_whole_selection_uses_one_guarded_write_and_only_desired_words(self):
        editor,client,state=self.fixture()
        before=dict(client.memory)
        with patch.object(client,'apply_patch',wraps=client.apply_patch) as applied:
            result=editor.set_speeds([9,10,11],0)
        self.assertFalse(result['pending'])
        self.assertIn('3 veículo(s)',result['message'])
        applied.assert_called_once()
        self.assertEqual(len(applied.call_args.args[0]),3)
        allowed={row['node']+offset for row in state.vehicles.values() for offset in range(4)}
        self.assertEqual({a:v for a,v in client.memory.items() if a not in allowed},
                         {a:v for a,v in before.items() if a not in allowed})
        for row in state.vehicles.values():
            self.assertEqual(state.memory.read(row['node'],'<f')[0],0.)
            self.assertEqual(state.memory.read(row['node']+0x2C,'<f')[0],row['travel_speed'])
        self.assertEqual([op['target']['id'] for op in editor.recipe],[9,10,11])

    def test_invalid_final_actor_or_stale_owner_causes_no_write_or_recipe(self):
        for stale in (False,True):
            with self.subTest(stale=stale):
                editor,client,state=self.fixture()
                if stale:
                    state.memory.store(state.vehicles[11]['node']+0x4A,'<B',100)
                else:
                    state.vehicles[11]['initialized']=False
                before=dict(client.memory)
                with self.assertRaises(profile.ProfileError):
                    editor.set_speeds([9,10,11],30)
                self.assertEqual(client.memory,before)
                self.assertEqual(client.writes,[])
                self.assertEqual(editor.recipe,[])
                self.assertIsNone(editor.baseline)

    def test_bulk_recipe_round_trip_preserves_individual_logical_targets(self):
        source,original,_state=self.fixture()
        source.set_speeds([9,10,11],35)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'bulk.json')
            source.save_preset(path)
            replay,client,_other=self.fixture()
            result=replay.load_preset(path)
            self.assertFalse(result['pending'])
            self.assertEqual(replay.recipe,source.recipe)
            self.assertEqual(client.memory,original.memory)

    def test_created_and_initial_targets_are_recorded_in_one_batch(self):
        editor,_client,state=self.fixture()
        editor._start_recipe(state)
        editor.actor_keys[11]=7
        editor.set_speeds([9,11],40)
        self.assertEqual(editor.recipe[0]['target']['kind'],'initial')
        self.assertEqual(editor.recipe[1]['target'],dict(kind='created',key=7))

    def test_untracked_native_actor_remains_editable_but_json_is_refused(self):
        editor,_client,state=self.fixture()
        editor._start_recipe(state)
        del editor.baseline_refs[11]
        editor.set_speeds([9,11],40)
        self.assertEqual(editor.recipe[1]['target']['kind'],'observed')
        self.assertEqual(state.memory.read(state.vehicles[11]['node'],'<f')[0],40.)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'unreplayable.json'
            with self.assertRaisesRegex(c.EditorError,'Salvar estado'):
                editor.save_preset(str(path))
            self.assertFalse(path.exists())

    def test_observed_target_in_imported_recipe_rejected_before_any_write(self):
        editor,client,state=self.fixture()
        ref=dict(kind='initial',id=9,model_id=state.vehicles[9]['model_id'],path=2)
        operations=[dict(op='set_speed',target=ref,control_value=20),
                    dict(op='set_speed',target={**ref,'kind':'observed'},control_value=30)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'unreplayable.json'
            path.write_text(json.dumps(dict(format='burnout3-current-event-recipe',version=1,
                profile='SLUS-21050/BEBF8793',baseline=c._fingerprint(state),operations=operations)),encoding='utf8')
            with self.assertRaisesRegex(c.EditorError,'Referência'):
                editor.load_preset(str(path))
        self.assertEqual(client.writes,[])
        self.assertEqual(editor.recipe,[])

    def test_ambiguous_bulk_write_blocks_edits_without_recording_success(self):
        editor,client,_state=self.fixture()
        with patch.object(client,'apply_patch',side_effect=PineVerificationError('Partial write')):
            with self.assertRaisesRegex(c.EditorError,'não puderam ser confirmadas'):
                editor.set_speeds([9,10,11],30)
        self.assertTrue(editor.unsafe)
        self.assertEqual(editor.recipe,[])
        with self.assertRaisesRegex(c.EditorError,'última escrita'):
            editor.set_speeds([9,10,11],20)


if __name__=='__main__':
    unittest.main()
