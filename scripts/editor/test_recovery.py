"""Recovery is explicit, journal-bound, retired and confined to owned code."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import controller as c,profile,recovery,spawncode as s
from editor.catalog import encode_identifier
from editor.pine import Status
from test_batch import BatchClient


class RecoveryTests(unittest.TestCase):
    def fixture(self,folder,version=2):
        requests = [dict(manager=s.MANAGER,type_code=1,model_hash=encode_identifier('COMPCAR14'),
            path_descriptor=s.PATHS+21*s.PATH_STRIDE,progression=150-i*10,
            speed=30,spacing=1,secondary_type_code=0,secondary_model_hash=0) for i in range(3)]
        payload = s._build_batch(requests,bytes(range(16)),format_version=version)
        client = BatchClient()
        client.store(s.CAVE,payload['scratch_bytes'])
        for i,p in enumerate(payload['probes']):
            client.store(p['address'],struct.pack('<3I',2,0x539C10+(12+i)*0x180,0x551910+(10+i)*0x50))
        client.store(s.DATA,struct.pack('<I',payload['completion_token']))
        row = dict(event='batch_staged',nonce=bytes(range(16)).hex(),model_id='COMPCAR14',
                   secondary_model_id=None,count=3,path=21,progressions=[150,140,130])
        log = Path(folder)/'editor-actions.jsonl'
        log.write_text(json.dumps(row)+'\n',encoding='utf8')
        editor = c.EditorController(client=client,journal_dir=folder)
        return editor,client,payload,row,log

    def mixed_fixture(self,folder):
        editor,client,_payload,row,log = self.fixture(folder)
        items = [dict(model_id='COMPCAR14',secondary_model_id=None,type_code=1,variant=0),
                 dict(model_id='HEVYCAR17',secondary_model_id=None,type_code=3,variant=3),
                 dict(model_id='HEVYCAR22',secondary_model_id='HEVYCAR27',type_code=4,variant=6)]
        requests = [dict(manager=s.MANAGER,type_code=item['type_code'],
            model_hash=encode_identifier(item['model_id']),path_descriptor=s.PATHS+21*s.PATH_STRIDE,
            progression=150-i*10,speed=30,spacing=1,variant=item['variant'],
            secondary_type_code=11 if item['secondary_model_id'] else 0,
            secondary_model_hash=encode_identifier(item['secondary_model_id']) if item['secondary_model_id'] else 0)
            for i,item in enumerate(items)]
        payload = s.build_batch(requests,nonce=bytes(range(16)))
        client.store(s.CAVE,payload['scratch_bytes'])
        for i,p in enumerate(payload['probes']):
            client.store(p['address'],struct.pack('<3I',2,0x539C10+(12+i)*0x180,0x551910+(10+i)*0x50))
        client.store(s.DATA,struct.pack('<I',payload['completion_token']))
        row['items'] = items
        log.write_text(json.dumps(row)+'\n',encoding='utf8')
        return editor,client,payload,row,log

    def test_old_and_new_completed_requests_clean_only_owned_area_once(self):
        for version in (1,2):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as folder:
                editor,client,payload,_row,_log = self.fixture(folder,version)
                editor.recipe = [{'op':'existing-operation'}]
                editor.replay_queue = [{'op':'unconfirmed-operation'}]
                with patch.object(profile,'snapshot',side_effect=AssertionError('No traffic profile needed')):
                    result = editor.finalize_pending()
                self.assertTrue(result['warning'])
                self.assertFalse(result['pending'])
                self.assertEqual(client.read_bytes(s.CAVE,4096),s.clean_batch_scratch())
                self.assertEqual(client.read_bytes(s.HOOK,8),s.ORIGINAL)
                self.assertEqual(client.writes,[(s.CAVE,payload['clean_scratch'])])
                self.assertEqual(editor.recipe,[{'op':'existing-operation'}])
                self.assertEqual(editor.replay_queue,[])
                self.assertIn(payload['completion_token'],editor.completion_tokens)
                before = list(client.writes)
                self.assertFalse(editor.finalize_pending()['pending'])
                self.assertEqual(client.writes,before)

    def test_journal_must_match_nonce_and_every_request_parameter(self):
        for field,value in [('nonce','11'*16),('model_id','COMPCAR15'),('path',20),
                            ('count',2),('secondary_model_id','HEVYCAR27'),
                            ('progressions',[150,140,129])]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as folder:
                editor,client,_payload,row,log = self.fixture(folder)
                row[field] = value
                log.write_text(json.dumps(row),encoding='utf8')
                before = client.memory.copy()
                with self.assertRaises(c.EditorError):
                    editor.finalize_pending()
                self.assertEqual(client.memory,before)
                self.assertEqual(client.writes,[])

    def test_missing_journal_never_authorizes_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            editor,client,_payload,_row,log = self.fixture(folder)
            log.unlink()
            with self.assertRaisesRegex(c.EditorError,'local log'):
                editor.finalize_pending()
            self.assertEqual(client.writes,[])

    def test_modified_code_arguments_nonce_padding_or_landing_are_not_cleaned(self):
        for address in (s.CAVE+0x30,s.BATCH_RECORD_BASE+0x10,s.BATCH_RECORD_BASE+0x28,
                        s.NONCE_ADDRESS,s.CAVE+0x950,s.LANDING,s.DATA+4):
            with self.subTest(address=hex(address)),tempfile.TemporaryDirectory() as folder:
                editor,client,_payload,_row,_log = self.fixture(folder)
                client.memory[address] ^= 1
                before = client.memory.copy()
                with self.assertRaises(c.EditorError):
                    editor.finalize_pending()
                self.assertEqual(client.memory,before)
                self.assertEqual(client.writes,[])

    def test_running_incomplete_wrong_generation_or_active_hook_never_clean(self):
        for kind in ('running','incomplete','master0','master2','hook'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                editor,client,payload,_row,_log = self.fixture(folder)
                if kind == 'running': client.core_status = Status.RUNNING
                elif kind == 'incomplete': client.store(payload['probes'][1]['address'],struct.pack('<I',1))
                elif kind in ('master0','master2'): client.store(s.DATA,struct.pack('<I',int(kind[-1])))
                else: client.store(s.HOOK,payload['hook_bytes'])
                with self.assertRaises(c.EditorError):
                    editor.finalize_pending()
                self.assertEqual(client.writes,[])

    def test_state_change_after_validation_prevents_the_first_write(self):
        with tempfile.TemporaryDirectory() as folder:
            editor,client,_payload,_row,_log = self.fixture(folder)
            original = client.read_bytes
            reads = 0
            def concurrent_change(address,length):
                nonlocal reads
                if address == s.CAVE:
                    reads += 1
                    if reads == 2: client.memory[s.CAVE+0x20] ^= 1
                return original(address,length)
            with patch.object(client,'read_bytes',side_effect=concurrent_change):
                with self.assertRaisesRegex(c.EditorError,'changed'):
                    editor.finalize_pending()
            self.assertEqual(client.writes,[])

    def test_failed_cleanup_keeps_the_editor_unsafe(self):
        with tempfile.TemporaryDirectory() as folder:
            editor,client,_payload,_row,_log = self.fixture(folder)
            client.fail_cleanup = True
            with self.assertRaisesRegex(c.EditorError,'could not be confirmed'):
                editor.finalize_pending()
            self.assertTrue(editor.unsafe)
            with self.assertRaises(c.EditorError):
                editor.finalize_pending()

    def test_explicit_completion_can_release_owned_code_after_profile_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            editor,client,_payload,_row,_log = self.fixture(folder)
            editor.pending = type('Pending',(),{'batch':True})()
            with patch.object(editor,'poll',side_effect=profile.ProfileError('Traffic expired')):
                result = editor.finalize_pending()
            self.assertTrue(result['warning'])
            self.assertIsNone(editor.pending)
            self.assertTrue(all(address == s.CAVE for address,_data in client.writes))

    def test_mixed_completed_batch_matches_every_model_type_cargo_and_variant(self):
        with tempfile.TemporaryDirectory() as folder:
            editor,client,payload,_row,_log = self.mixed_fixture(folder)
            client.store(0x539C10,b'unchanged actor')
            result=editor.finalize_pending()
            self.assertFalse(result['pending'])
            self.assertTrue(result['warning'])
            self.assertEqual(client.writes,[(s.CAVE,payload['clean_scratch'])])
            self.assertEqual(client.read_bytes(0x539C10,len(b'unchanged actor')),b'unchanged actor')

    def test_wrong_later_mixed_item_never_authorizes_cleanup(self):
        cases=[(1,'model_id','HEVYCAR18'),(1,'type_code',2),(1,'variant',4),
               (1,'variant',True),(1,'type_code',True),(2,'secondary_model_id','HEVYCAR29'),
               (2,'secondary_model_id',None),(2,'secondary_type_code',0),
               (2,'variant',8),(1,'type_code',None)]
        for index,key,value in cases:
            with self.subTest(index=index,key=key,value=value),tempfile.TemporaryDirectory() as folder:
                editor,client,_payload,row,log = self.mixed_fixture(folder)
                row['items'][index][key]=value
                log.write_text(json.dumps(row),encoding='utf8')
                before=client.memory.copy()
                with self.assertRaisesRegex(c.EditorError,'local log'):
                    editor.finalize_pending()
                self.assertEqual(client.memory,before)
                self.assertEqual(client.writes,[])

    def test_malformed_or_missing_mixed_items_never_fall_back_to_a_legacy_record(self):
        for value in (None,{},[],[None,None,None]):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as folder:
                editor,client,_payload,row,log=self.fixture(folder)
                row['items']=value
                log.write_text(json.dumps(row),encoding='utf8')
                with self.assertRaisesRegex(c.EditorError,'local log'):editor.finalize_pending()
                self.assertEqual(client.writes,[])

    def test_legacy_journal_cannot_authorize_nonzero_appearance_variants(self):
        with tempfile.TemporaryDirectory() as folder:
            editor,client,_payload,row,_log=self.fixture(folder)
            matched=s.match_batch_scratch(client.read_bytes(s.CAVE,4096),bytes(range(16)))
            requests=matched['requests']
            requests[1]['variant']=1
            self.assertFalse(recovery._matches_record(row,bytes(range(16)).hex(),requests))


if __name__ == '__main__':
    unittest.main()
