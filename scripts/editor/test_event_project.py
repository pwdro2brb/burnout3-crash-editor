"""Project persistence tests use generated ZIPs containing zero RAM only."""
from pathlib import Path
import hashlib
import json
import shutil
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import event_project as projects
import test_state_store as state_fixtures


class EventProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archives=tempfile.TemporaryDirectory()
        cls.base_archive=Path(cls.archives.name)/'reference.p2s'
        state_fixtures.make_archive(cls.base_archive)
        cls.edited_archive=Path(cls.archives.name)/'edited.p2s'
        shutil.copyfile(cls.base_archive,cls.edited_archive)
        with zipfile.ZipFile(cls.edited_archive,'a',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('Synthetic.scene',b'a new synthetic scene')

    @classmethod
    def tearDownClass(cls):
        cls.archives.cleanup()

    def fixture(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root=Path(folder.name)
        project=projects.create(root/'event','Teste de cruzamento',self.base_archive,
            recipe={'operations':[]},summary={'active_objects':3})
        return root,project

    def rewrite(self,project,change):
        path=Path(project['path'])
        data=json.loads(path.read_text(encoding='utf8'))
        change(data)
        path.write_text(json.dumps(data),encoding='utf8')

    def test_create_named_project_copies_base_and_initial_scene_shares_it(self):
        before=self.base_archive.read_bytes()
        root,project=self.fixture()
        self.assertEqual(project['name'],'Teste de cruzamento')
        self.assertEqual(project['base_path'],str((root/'event'/'base.p2s').resolve()))
        self.assertEqual(project['scene_path'],project['base_path'])
        self.assertEqual(project['scene']['revision'],0)
        self.assertEqual(Path(project['base_path']).read_bytes(),before)
        self.assertEqual(self.base_archive.read_bytes(),before)
        self.assertEqual(sorted(p.name for p in (root/'event').iterdir()),['base.p2s',projects.MANIFEST])
        self.assertEqual(projects.public_info(project),dict(path=project['path'],name=project['name'],
            base_path=project['base_path'],scene_path=project['scene_path'],scene_revision=0))
        persisted=json.loads(Path(project['path']).read_text(encoding='utf8'))
        self.assertNotIn('path',persisted)
        self.assertNotIn(str(root),json.dumps(persisted))

    def test_save_publishes_new_revision_and_preserves_base_and_all_older_scenes(self):
        _root,initial=self.fixture()
        base=Path(initial['base_path']).read_bytes()
        edited=projects.save_scene(initial,self.edited_archive,
            recipe={'operations':[{'op':'synthetic'}]},summary={'active_objects':5})
        self.assertEqual(edited['scene']['revision'],1)
        self.assertNotEqual(edited['scene_path'],edited['base_path'])
        self.assertEqual(Path(edited['scene_path']).read_bytes(),self.edited_archive.read_bytes())
        second=projects.save_scene(edited,self.base_archive)
        self.assertEqual(second['scene']['revision'],2)
        self.assertNotEqual(second['scene_path'],edited['scene_path'])
        self.assertEqual(Path(edited['scene_path']).read_bytes(),self.edited_archive.read_bytes())
        self.assertEqual(Path(second['base_path']).read_bytes(),base)
        self.assertEqual(projects.load(Path(initial['path'])),second)

    def test_failed_publish_preserves_previous_manifest_and_snapshots(self):
        _root,initial=self.fixture()
        path=Path(initial['path'])
        before=path.read_bytes()
        with patch.object(projects.os,'replace',side_effect=OSError('Synthetic publish failure')):
            with self.assertRaisesRegex(projects.ProjectError,'Previous versions'):
                projects.save_scene(initial,self.edited_archive)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(projects.load(path),initial)
        self.assertFalse((path.parent/'.event-write.lock').exists())

    def test_stale_project_cannot_replace_a_more_recent_save(self):
        _root,initial=self.fixture()
        current=projects.save_scene(initial,self.edited_archive)
        before=Path(current['path']).read_bytes()
        with self.assertRaisesRegex(projects.ProjectError,'since it was opened'):
            projects.save_scene(initial,self.base_archive)
        self.assertEqual(Path(current['path']).read_bytes(),before)
        self.assertEqual(projects.load(Path(current['path'])),current)

    def test_existing_project_directory_and_invalid_source_are_never_overwritten(self):
        root,project=self.fixture()
        before=Path(project['path']).read_bytes()
        with self.assertRaises(projects.ProjectError):
            projects.create(root/'event','Outro nome',self.edited_archive)
        self.assertEqual(Path(project['path']).read_bytes(),before)
        bad=root/'bad.p2s'
        bad.write_bytes(b'not an archive')
        with self.assertRaises(projects.ProjectError):
            projects.save_scene(project,bad)
        self.assertEqual(Path(project['path']).read_bytes(),before)

    def test_modified_base_or_scene_is_rejected_before_returning_project(self):
        for edit_scene in (False,True):
            with self.subTest(edit_scene=edit_scene):
                _root,project=self.fixture()
                if edit_scene:
                    project=projects.save_scene(project,self.edited_archive)
                target=Path(project['scene_path'] if edit_scene else project['base_path'])
                with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('Tampered.id',b'changed')
                with self.assertRaisesRegex(projects.ProjectError,'hash'):
                    projects.load(Path(project['path']))

    def test_external_and_traversal_references_are_refused(self):
        cases=['../outside.p2s','..\\outside.p2s','/outside.p2s',
               'C:\\outside.p2s','sub/base.p2s','base.p2s:alternate',
               'scene-not-a-uuid.p2s','scene-'+'A'*32+'.p2s']
        for filename in cases:
            with self.subTest(filename=filename):
                _root,project=self.fixture()
                self.rewrite(project,lambda p:p['scene'].update(file=filename,revision=1))
                with self.assertRaises(projects.ProjectError):
                    projects.load(Path(project['path']))

    def test_linked_state_and_linked_manifest_are_refused(self):
        for which in ('base','manifest','directory'):
            with self.subTest(which=which):
                root,project=self.fixture()
                path=Path(project['path'])
                try:
                    if which=='directory':
                        link=root/'linked-event'
                        link.symlink_to(path.parent,target_is_directory=True)
                        requested=link/projects.MANIFEST
                    else:
                        target=Path(project['base_path']) if which=='base' else path
                        outside=root/('outside.p2s' if which=='base' else 'outside.json')
                        target.replace(outside)
                        target.symlink_to(outside)
                        requested=path
                except (OSError,NotImplementedError):
                    self.skipTest('Creating links is unavailable on this host')
                with self.assertRaises(projects.ProjectError):
                    projects.load(requested)

    def test_mocked_windows_reparse_attributes_reject_files_and_project_directory(self):
        # Exercise the Windows metadata branches even without the privilege to
        # create symlinks/junctions. All other mode bits still describe a normal
        # regular file or directory, so the reparse flag must cause rejection.
        path=Path('synthetic-reparse-target')
        with patch.object(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400,create=True):
            for mode,checker in ((stat.S_IFREG,projects._regular),(stat.S_IFDIR,projects._directory)):
                with self.subTest(mode=mode):
                    attrs=SimpleNamespace(st_mode=mode,st_file_attributes=0)
                    with patch.object(Path,'lstat',return_value=attrs):
                        self.assertTrue(checker(path))
                        attrs.st_file_attributes=0x400
                        self.assertFalse(checker(path))
            attrs=SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
            with patch.object(Path,'lstat',return_value=attrs):
                with self.assertRaisesRegex(projects.ProjectError,'redirect'):
                    projects._root(path)

    def test_external_name_change_rejects_stale_save_and_caller_name_cannot_rename_disk_project(self):
        _root,project=self.fixture()
        original_name=project['name']
        project['name']='Caller-only changed name'
        saved=projects.save_scene(project,self.edited_archive)
        self.assertEqual(saved['name'],original_name)
        self.rewrite(saved,lambda data:data.update(name='Externally renamed event'))
        before=Path(saved['path']).read_bytes()
        with self.assertRaisesRegex(projects.ProjectError,'since it was opened'):
            projects.save_scene(saved,self.base_archive)
        self.assertEqual(Path(saved['path']).read_bytes(),before)
        self.assertEqual(projects.load(Path(saved['path']))['name'],'Externally renamed event')

    def test_schema_version_profile_revision_and_metadata_are_bounded(self):
        changes=[lambda p:p.update(format='other'),lambda p:p.update(version=True),
                 lambda p:p.update(profile='SLUS00000/00000000'),
                 lambda p:p.update(emulator='another version'),
                 lambda p:p['scene'].update(revision=True),
                 lambda p:p['scene'].update(revision=-1),
                 lambda p:p['scene'].update(revision=projects.MAX_REVISION+1),
                 lambda p:p.update(summary=[]),lambda p:p.update(recipe={'bad':float('nan')}),
                 lambda p:p.update(name='\n'),lambda p:p.update(extra='unknown')]
        for change in changes:
            with self.subTest(change=change):
                _root,project=self.fixture()
                self.rewrite(project,change)
                with self.assertRaises(projects.ProjectError):
                    projects.load(Path(project['path']))

    def test_duplicate_fields_and_oversized_manifest_are_rejected(self):
        _root,project=self.fixture()
        path=Path(project['path'])
        raw=path.read_text(encoding='utf8')
        path.write_text(raw.replace('{','{"name":"duplicate",',1),encoding='utf8')
        with self.assertRaisesRegex(projects.ProjectError,'repeated'):
            projects.load(path)
        path.write_bytes(b' '* (projects.MAX_MANIFEST_BYTES+1))
        with self.assertRaises(projects.ProjectError):
            projects.load(path)

    def test_write_lock_blocks_simultaneous_save_without_replacing_anything(self):
        _root,project=self.fixture()
        path=Path(project['path'])
        before=path.read_bytes()
        lock=path.parent/'.event-write.lock'
        lock.write_bytes(b'owned by another save')
        with self.assertRaisesRegex(projects.ProjectError,'Another project write'):
            projects.save_scene(project,self.edited_archive)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(lock.read_bytes(),b'owned by another save')

    def test_verified_source_replacement_is_rejected_before_create_or_save_publishes(self):
        root,project=self.fixture()
        source=root/'verified-then-changed.p2s'
        shutil.copyfile(self.base_archive,source)
        verified_digest=hashlib.sha256(source.read_bytes()).hexdigest()
        # Still a complete, valid state ZIP. Its new bytes must not inherit the
        # controller's earlier proof just because ZIP validation also succeeds.
        with zipfile.ZipFile(source,'a',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('Replaced.payload',b'new state payload after verification')
        before=Path(project['path']).read_bytes()
        base_before=Path(project['base_path']).read_bytes()
        files_before={p.name:p.read_bytes() for p in Path(project['path']).parent.iterdir()}
        with self.assertRaisesRegex(projects.ProjectError,'since the check'):
            projects.create(root/'new-event','New event',source,
                            expected_source_sha256=verified_digest)
        self.assertFalse((root/'new-event'/projects.MANIFEST).exists())
        self.assertFalse((root/'new-event'/'base.p2s').exists())
        with self.assertRaisesRegex(projects.ProjectError,'since the check'):
            projects.save_scene(project,source,expected_source_sha256=verified_digest)
        self.assertEqual(Path(project['path']).read_bytes(),before)
        self.assertEqual(Path(project['base_path']).read_bytes(),base_before)
        self.assertEqual({p.name:p.read_bytes() for p in Path(project['path']).parent.iterdir()},files_before)
        self.assertEqual(projects.load(Path(project['path'])),project)

    def test_expected_source_hash_accepts_the_proven_file_and_rejects_bad_digest_format(self):
        root,project=self.fixture()
        digest=hashlib.sha256(self.edited_archive.read_bytes()).hexdigest()
        created=projects.create(root/'verified-event','Verified',self.edited_archive,
                                expected_source_sha256=digest)
        saved=projects.save_scene(project,self.edited_archive,expected_source_sha256=digest)
        self.assertEqual(created['base']['sha256'],digest)
        self.assertEqual(saved['scene']['sha256'],digest)
        for bad in ('',digest.upper(),digest[:-1],True,42):
            with self.subTest(bad=bad):
                new=root/'bad-digest-event'
                with self.assertRaisesRegex(projects.ProjectError,'expected hash'):
                    projects.create(new,'Bad digest',self.edited_archive,expected_source_sha256=bad)
                self.assertFalse(new.exists())
                before=Path(saved['path']).read_bytes()
                with self.assertRaisesRegex(projects.ProjectError,'expected hash'):
                    projects.save_scene(saved,self.edited_archive,expected_source_sha256=bad)
                self.assertEqual(Path(saved['path']).read_bytes(),before)


if __name__=='__main__':
    unittest.main()
