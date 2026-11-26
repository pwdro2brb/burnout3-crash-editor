"""Project lifecycle with real manifests, generated states and fake PINE only."""
from pathlib import Path
import hashlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import controller as c, event_project, profile, state_restore
from editor.pine import Status
import test_batch as batch_fixtures
import test_state_store as state_fixtures


class EventProjectControllerTests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder=Path(temporary.name)
        client=batch_fixtures.BatchClient()
        pause_control=SimpleNamespace(supports=lambda:True,emulator_root=lambda:folder/'emulator')
        editor=c.EditorController(client=client,pause_control=pause_control)
        snap=batch_fixtures.initial_snapshot()
        self.addCleanup(patch.stopall)
        patch.object(profile,'snapshot',return_value=snap).start()
        patch.object(c,'_state_digest',return_value='synthetic-recovery').start()
        captures=[]
        def capture(destination):
            path=Path(destination)
            state_fixtures.make_archive(path)
            with zipfile.ZipFile(path,'a') as archive:
                archive.writestr('test-revision',str(len(captures)))
            captures.append(path)
            return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        pending=False,core_paused=True)
        patch.object(editor,'export_state',side_effect=capture).start()
        return editor,client,snap,folder,captures

    def test_create_save_reopen_preserves_base_and_cleans_successful_staging(self):
        editor,client,_snap,folder,captures=self.fixture()
        created=editor.create_project(str(folder/'event'),'Cruzamento personalizado')
        self.assertEqual(created['project']['name'],'Cruzamento personalizado')
        self.assertEqual(created['project']['scene_revision'],0)
        self.assertTrue(created['core_paused'])
        base=Path(editor.project['base_path']).read_bytes()
        saved=editor.save_project()
        self.assertEqual(saved['project']['scene_revision'],1)
        self.assertEqual(Path(editor.project['base_path']).read_bytes(),base)
        self.assertNotEqual(Path(editor.project['scene_path']).read_bytes(),base)
        self.assertTrue(all(not path.exists() for path in captures))
        self.assertEqual(client.writes,[])
        reopened=event_project.load(Path(saved['project']['path']))
        self.assertEqual(reopened['scene'],editor.project['scene'])

    def test_invalid_name_existing_folder_pending_or_running_never_capture(self):
        for failure in ('name','folder','pending','running'):
            with self.subTest(failure=failure):
                editor,client,_snap,folder,captures=self.fixture()
                destination=folder/'event'
                name='Nome'
                if failure=='name': name='\x7f'
                elif failure=='folder': destination.mkdir()
                elif failure=='pending': editor.pending=object()
                else: client.core_status=Status.RUNNING
                with self.assertRaises(c.EditorError):
                    editor.create_project(str(destination),name)
                self.assertEqual(captures,[])
                self.assertEqual(client.writes,[])

    def test_test_action_saves_scene_before_resuming(self):
        editor,_client,_snap,folder,_captures=self.fixture()
        editor.create_project(str(folder/'event'),'Teste')
        def resumed():
            self.assertEqual(editor.project['scene']['revision'],1)
            self.assertTrue(Path(editor.project['scene_path']).exists())
            return dict(pending=False,core_paused=False)
        with patch.object(editor,'resume',side_effect=resumed) as resume:
            result=editor.test_project()
        resume.assert_called_once()
        self.assertFalse(result['core_paused'])
        self.assertEqual(result['project']['scene_revision'],1)

    def test_resume_error_reports_saved_scene_without_retry(self):
        editor,_client,_snap,folder,_captures=self.fixture()
        editor.create_project(str(folder/'event'),'Teste')
        with patch.object(editor,'resume',side_effect=RuntimeError('Native pause unavailable')) as resume:
            result=editor.test_project()
        self.assertTrue(result['warning'])
        self.assertIn('scene was saved',result['message'])
        self.assertEqual(result['project']['scene_revision'],1)
        resume.assert_called_once()

    def test_open_restart_and_base_restore_route_to_the_correct_verified_file(self):
        editor,client,_snap,folder,_captures=self.fixture()
        editor.create_project(str(folder/'event'),'Teste')
        editor.save_project()
        project=editor.project
        editor.actor_keys[100]=8
        editor.recipe.append(dict(op='old-edit'))
        def restore(_client,_root,source,**options):
            self.assertIs(_client,client)
            self.assertEqual(options['expected_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            return dict(sha256=hashlib.sha256(source.read_bytes()).hexdigest(),core_paused=True)
        with patch.object(state_restore,'restore_state',side_effect=restore) as restored:
            for action,expected in ((lambda:editor.open_project(project['path']),project['scene_path']),
                                    (editor.restart_project,project['scene_path']),
                                    (editor.restore_project_base,project['base_path'])):
                result=action()
                self.assertTrue(result['core_paused'])
                self.assertEqual(str(restored.call_args.args[2]),expected)
                self.assertEqual(editor.recipe,[])
                self.assertEqual(editor.actor_keys,{})
                self.assertFalse(editor.unsafe)
        self.assertEqual(editor.project['scene'],project['scene'])

    def test_uncertain_restore_blocks_future_mutations_and_keeps_project(self):
        editor,_client,_snap,folder,_captures=self.fixture()
        editor.create_project(str(folder/'event'),'Teste')
        old=editor.project
        with patch.object(state_restore,'restore_state',side_effect=state_restore.RestoreError('Timeout',uncertain=True)):
            with self.assertRaisesRegex(c.EditorError,'Timeout'):
                editor.restart_project()
        self.assertTrue(editor.unsafe)
        self.assertIs(editor.project,old)
        with self.assertRaisesRegex(c.EditorError,'last write'):
            editor.save_project()

    def test_preflight_restore_failure_does_not_mark_the_scene_unsafe(self):
        editor,_client,_snap,folder,_captures=self.fixture()
        editor.create_project(str(folder/'event'),'Teste')
        with patch.object(state_restore,'restore_state',side_effect=state_restore.RestoreError('All slots occupied',uncertain=False)):
            with self.assertRaises(c.EditorError): editor.restart_project()
        self.assertFalse(editor.unsafe)

    def test_rejected_profile_after_load_blocks_further_edits(self):
        editor,_client,_snap,folder,_captures=self.fixture()
        editor.create_project(str(folder/'event'),'Teste')
        with patch.object(state_restore,'restore_state',return_value=dict(sha256='verified')), \
             patch.object(editor,'_snapshot',side_effect=[batch_fixtures.initial_snapshot(),profile.ProfileError('Bad scene')]):
            with self.assertRaisesRegex(c.EditorError,'profile did not confirm'):
                editor.restart_project()
        self.assertTrue(editor.unsafe)

    def test_corrupted_or_stale_project_cannot_capture_or_load_a_state(self):
        editor,_client,_snap,folder,captures=self.fixture()
        editor.create_project(str(folder/'event'),'Teste')
        old=editor.project
        source=folder/'external.p2s'
        state_fixtures.make_archive(source)
        event_project.save_scene(old,source)
        with self.assertRaisesRegex(c.EditorError,'another session'):
            editor.save_project()
        self.assertEqual(len(captures),1)
        Path(old['base_path']).write_bytes(b'corrupt')
        with patch.object(state_restore,'restore_state') as restored:
            with self.assertRaises(event_project.ProjectError):
                editor.restart_project()
        restored.assert_not_called()

    def test_manual_import_and_scene_save_need_no_capture_or_load_request(self):
        editor,client,_snap,folder,captures=self.fixture()
        manual=folder/'manual.p2s'
        state_fixtures.make_archive(manual)
        original=manual.read_bytes()
        def verified(_client,source):
            self.assertIs(_client,client)
            return dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        with patch.object(state_restore,'verify_current_state',side_effect=verified) as verify, \
             patch.object(state_restore,'restore_state') as load:
            created=editor.import_project(str(folder/'event'),'Sem slot livre',str(manual))
            self.assertEqual(created['project']['scene_revision'],0)
            saved=editor.save_project_from_state(str(manual))
            self.assertEqual(saved['project']['scene_revision'],1)
        self.assertEqual(verify.call_count,2)
        load.assert_not_called()
        self.assertEqual(captures,[])
        self.assertEqual(manual.read_bytes(),original)
        self.assertEqual(client.writes,[])

    def test_manual_confirmation_selects_saved_scene_or_original_base(self):
        editor,client,_snap,folder,_captures=self.fixture()
        editor.create_project(str(folder/'event'),'Manual')
        editor.save_project()
        project=editor.project
        def verified(_client,source,**options):
            self.assertIs(_client,client)
            return dict(path=str(source),sha256='verified')
        with patch.object(state_restore,'verify_current_state',side_effect=verified) as verify, \
             patch.object(state_restore,'restore_state') as load:
            for base in (False,True):
                editor.recipe.append(dict(op='old-edit'))
                result=editor.confirm_project(project['path'],base=base)
                expected=project['base_path'] if base else project['scene_path']
                self.assertEqual(str(verify.call_args.args[1]),expected)
                self.assertTrue(result['core_paused'])
                self.assertEqual(editor.recipe,[])
                self.assertEqual(editor.project['scene'],project['scene'])
        load.assert_not_called()

    def test_manual_mismatch_does_not_adopt_project_or_lose_existing_edits(self):
        editor,_client,_snap,folder,captures=self.fixture()
        manual=folder/'manual.p2s'
        state_fixtures.make_archive(manual)
        editor.recipe.append(dict(op='existing'))
        with patch.object(state_restore,'verify_current_state',side_effect=state_restore.RestoreError('Mismatch')):
            with self.assertRaises(state_restore.RestoreError):
                editor.import_project(str(folder/'must-not-exist'),'Manual',str(manual))
        self.assertIsNone(editor.project)
        self.assertEqual(editor.recipe,[dict(op='existing')])
        self.assertFalse((folder/'must-not-exist').exists())
        self.assertFalse(editor.unsafe)
        self.assertEqual(captures,[])


if __name__=='__main__':
    unittest.main()
