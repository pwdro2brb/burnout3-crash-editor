"""Synthetic ZIP and in-memory queued-load tests; no game or emulator files."""
from pathlib import Path
import hashlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import state_restore as restore, state_store as store, spawncode as spawn, profile
from editor.pine import Status
from runtime.inspect_savestate import ORIGINAL_WORDS
import test_state_store as export_fixtures


def memory(seed=0, *, landing=False):
    data=bytearray(store.EE_MEMORY_SIZE)
    for address,word in ORIGINAL_WORDS.items():
        struct.pack_into('<I',data,address,word)
    data[spawn.HOOK:spawn.HOOK+8]=spawn.ORIGINAL
    data[spawn.CAVE:spawn.END]=(spawn.clean_batch_scratch() if landing else bytes(4096))
    for address,length in restore.PROOF_REGIONS:
        data[address:address+length]=bytes([seed])*length
    return data


def archive(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as out:
        out.writestr('eeMemory.bin',data)
        out.writestr('Version.id',b'synthetic restore test')


class Client:
    def __init__(self,target,*,delay=4,load=True,after_load=None):
        self.data=memory(7)
        self.target=target
        self.delay=delay
        self.load=load
        self.after_load=after_load
        self.requests=[]
        self.writes=[]
        self.pending=False
        self.polls=0
        self.current_status=Status.PAUSED
        self.current_identity=dict(version='PCSX2 1.7.2521',game_id='SLUS-21050',game_crc='BEBF8793')

    def status(self):
        if self.pending:
            self.polls+=1
            if self.load and self.polls>=self.delay:
                self.data[:]=self.target
                self.pending=False
                if self.after_load:
                    self.after_load()
        return self.current_status

    def identity(self):
        return dict(self.current_identity)

    def read_bytes(self,address,length):
        return bytes(self.data[address:address+length])

    def write_bytes(self,address,data):
        self.writes.append((address,bytes(data)))
        self.data[address:address+len(data)]=data

    def request_load_state(self,slot):
        self.requests.append(slot)
        self.pending=True


class StateRestoreTests(unittest.TestCase):
    def setUp(self):
        self.clock=0.
        def monotonic():
            return self.clock
        def sleep(amount):
            self.clock+=max(.001,amount)
        self.monotonic=patch.object(restore.time,'monotonic',side_effect=monotonic)
        self.sleep=patch.object(restore.time,'sleep',side_effect=sleep)
        self.monotonic.start()
        self.sleep.start()
        self.addCleanup(self.monotonic.stop)
        self.addCleanup(self.sleep.stop)

    def fixture(self,base,*,landing=False,**client_options):
        root=base/'emulator'
        ini=export_fixtures.portable(root)
        target=memory(2,landing=landing)
        source=base/'project'/'scene.p2s'
        archive(source,target)
        return root,ini,source,target,Client(target,**client_options)

    def test_delayed_load_requires_marker_disappearance_and_preserves_originals(self):
        for landing in (False,True):
            with self.subTest(landing=landing),tempfile.TemporaryDirectory() as folder:
                root,ini,source,target,client=self.fixture(Path(folder),landing=landing)
                before=(ini.read_bytes(),source.read_bytes())
                result=restore.restore_state(client,root,source,timeout=2)
                self.assertEqual(client.requests,[9])
                self.assertGreaterEqual(client.polls,client.delay)
                self.assertEqual(client.data,target)
                self.assertEqual(len(client.writes),1)
                self.assertEqual(client.writes[0][0],spawn.NONCE_ADDRESS)
                self.assertEqual(len(client.writes[0][1]),16)
                self.assertNotEqual(client.writes[0][1],bytes(16))
                self.assertEqual(result['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertTrue(result['core_paused'])
                self.assertTrue(result['temporary_removed'])
                self.assertFalse(result['warning'])
                self.assertEqual((ini.read_bytes(),source.read_bytes()),before)
                self.assertFalse((root/'sstates'/store.STATE_NAME.format(slot=9)).exists())

    def test_queued_ack_with_identical_current_scene_does_not_confirm_a_load(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,target,client=self.fixture(Path(folder),load=False)
            client.data[:]=target
            with self.assertRaises(restore.RestoreError) as caught:
                restore.restore_state(client,root,source,timeout=.2)
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(client.requests,[9])
            self.assertEqual(len(client.writes),1)
            self.assertEqual(client.data[spawn.NONCE_ADDRESS:spawn.NONCE_ADDRESS+16],client.writes[0][1])
            self.assertTrue((root/'sstates'/store.STATE_NAME.format(slot=9)).exists())

    def test_original_occupied_flat_or_nested_slots_are_never_replaced(self):
        for nested in (False,True):
            with self.subTest(nested=nested),tempfile.TemporaryDirectory() as folder:
                root,_ini,source,_target,client=self.fixture(Path(folder))
                candidates=store._candidates(root/'sstates',9)
                occupied=candidates[int(nested)]
                occupied.parent.mkdir(parents=True,exist_ok=True)
                occupied.write_bytes(b'user save')
                result=restore.restore_state(client,root,source,timeout=2)
                self.assertEqual(client.requests,[8])
                self.assertEqual(result['loaded_slot'],8)
                self.assertEqual(occupied.read_bytes(),b'user save')

    def test_all_slots_occupied_refuses_before_marker_or_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,_target,client=self.fixture(Path(folder))
            for slot in range(10):
                path=root/'sstates'/store.STATE_NAME.format(slot=slot)
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(bytes([slot]))
            with self.assertRaisesRegex(restore.RestoreError,'All ten') as caught:
                restore.restore_state(client,root,source)
            self.assertFalse(caught.exception.uncertain)
            self.assertEqual(client.requests,[])
            self.assertEqual(client.writes,[])

    def test_incompatible_code_pending_source_or_pending_current_refuses_without_write(self):
        for invalid in ('code','saved_hook','saved_cave','current_hook','current_cave'):
            with self.subTest(invalid=invalid),tempfile.TemporaryDirectory() as folder:
                root,_ini,source,target,client=self.fixture(Path(folder))
                if invalid=='code':
                    target[next(iter(ORIGINAL_WORDS))]^=1
                elif invalid=='saved_hook':
                    target[spawn.HOOK]^=1
                elif invalid=='saved_cave':
                    target[spawn.CAVE]=1
                elif invalid=='current_hook':
                    client.data[spawn.HOOK]^=1
                else:
                    client.data[spawn.CAVE]=1
                if invalid.startswith('saved') or invalid=='code':
                    archive(source,target)
                with self.assertRaises(restore.RestoreError) as caught:
                    restore.restore_state(client,root,source)
                self.assertFalse(caught.exception.uncertain)
                self.assertEqual(client.requests,[])
                self.assertEqual(client.writes,[])

    def test_wrong_identity_after_load_is_uncertain_and_never_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,_target,client=self.fixture(Path(folder))
            client.after_load=lambda:client.current_identity.update(game_crc='00000000')
            with self.assertRaisesRegex(restore.RestoreError,'profile') as caught:
                restore.restore_state(client,root,source)
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(client.requests,[9])
            self.assertEqual(len(client.writes),1)
            self.assertTrue((root/'sstates'/store.STATE_NAME.format(slot=9)).exists())

    def test_bad_target_traffic_proof_never_confirms_even_after_marker_disappears(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,_target,client=self.fixture(Path(folder))
            def wrong_scene():
                client.data[restore.PROOF_REGIONS[0][0]]^=1
            client.after_load=wrong_scene
            with self.assertRaises(restore.RestoreError) as caught:
                restore.restore_state(client,root,source,timeout=.3)
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(client.requests,[9])

    def test_replaced_temporary_file_is_preserved_after_confirmed_load(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,_target,client=self.fixture(Path(folder))
            temporary=root/'sstates'/store.STATE_NAME.format(slot=9)
            client.after_load=lambda:temporary.write_bytes(b'a new user file')
            result=restore.restore_state(client,root,source)
            self.assertTrue(result['warning'])
            self.assertFalse(result['temporary_removed'])
            self.assertEqual(temporary.read_bytes(),b'a new user file')
            self.assertEqual(Path(result['temporary_path']),temporary.resolve())

    def test_failed_marker_write_blocks_without_sending_the_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,_target,client=self.fixture(Path(folder))
            with patch.object(client,'write_bytes',side_effect=OSError('connection lost')):
                with self.assertRaises(restore.RestoreError) as caught:
                    restore.restore_state(client,root,source)
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(client.requests,[])

    def test_wrong_current_identity_running_core_invalid_archive_and_timeout_are_preflight(self):
        for invalid in ('identity','running','archive','timeout'):
            with self.subTest(invalid=invalid),tempfile.TemporaryDirectory() as folder:
                root,_ini,source,_target,client=self.fixture(Path(folder))
                if invalid=='identity':
                    client.current_identity['game_id']='SLUS-00000'
                elif invalid=='running':
                    client.current_status=Status.RUNNING
                elif invalid=='archive':
                    source.write_bytes(b'invalid archive')
                with self.assertRaises(restore.RestoreError) as caught:
                    restore.restore_state(client,root,source,timeout=0 if invalid=='timeout' else 2)
                self.assertFalse(caught.exception.uncertain)
                self.assertEqual(client.requests,[])
                self.assertEqual(client.writes,[])

    def test_manual_verification_accepts_current_scene_without_load_write_or_free_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,target,client=self.fixture(Path(folder),landing=True)
            client.data[:]=target
            for slot in range(10):
                path=root/'sstates'/store.STATE_NAME.format(slot=slot)
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'occupied')
            before=bytes(client.data),source.read_bytes()
            result=restore.verify_current_state(client,source)
            self.assertTrue(result['verified_current'])
            self.assertTrue(result['core_paused'])
            self.assertEqual(result['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(Path(result['path']),source.resolve())
            self.assertEqual((bytes(client.data),source.read_bytes()),before)
            self.assertEqual(client.requests,[])
            self.assertEqual(client.writes,[])

    def test_manual_mismatch_running_identity_or_pending_state_never_mutates(self):
        for invalid in ('traffic','hook','cave','running','identity','saved_pending'):
            with self.subTest(invalid=invalid),tempfile.TemporaryDirectory() as folder:
                _root,_ini,source,target,client=self.fixture(Path(folder))
                client.data[:]=target
                if invalid=='traffic':
                    client.data[restore.PROOF_REGIONS[0][0]]^=1
                elif invalid=='hook':
                    client.data[spawn.HOOK]^=1
                elif invalid=='cave':
                    client.data[spawn.NONCE_ADDRESS]=1
                elif invalid=='running':
                    client.current_status=Status.RUNNING
                elif invalid=='identity':
                    client.current_identity['game_crc']='00000000'
                else:
                    target[spawn.CAVE]=1
                    archive(source,target)
                before=bytes(client.data)
                with self.assertRaises(restore.RestoreError) as caught:
                    restore.verify_current_state(client,source)
                self.assertFalse(caught.exception.uncertain)
                self.assertEqual(bytes(client.data),before)
                self.assertEqual(client.requests,[])
                self.assertEqual(client.writes,[])

    def test_manual_proof_must_stay_matching_for_the_second_paused_read(self):
        with tempfile.TemporaryDirectory() as folder:
            _root,_ini,source,target,client=self.fixture(Path(folder))
            client.data[:]=target
            original_sleep=restore.time.sleep
            def change_after_first(amount):
                original_sleep(amount)
                client.data[restore.PROOF_REGIONS[-1][0]]^=1
            with patch.object(restore.time,'sleep',side_effect=change_after_first):
                with self.assertRaises(restore.RestoreError) as caught:
                    restore.verify_current_state(client,source)
            self.assertFalse(caught.exception.uncertain)
            self.assertEqual(client.requests,[])
            self.assertEqual(client.writes,[])

    def test_manual_proof_rejects_changed_paths_player_pointer_and_player_transform(self):
        for changed in ('paths','player_pointer','player_transform'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as folder:
                _root,_ini,source,target,client=self.fixture(Path(folder))
                player=0x700000
                struct.pack_into('<I',target,profile.PLAYER_TRANSFORM_POINTER,player)
                target[player:player+0x40]=bytes(range(0x40))
                archive(source,target)
                client.data[:]=target
                address=(profile.PATHS+profile.PATH_STRIDE*254 if changed=='paths' else
                         profile.PLAYER_TRANSFORM_POINTER if changed=='player_pointer' else player+0x30)
                client.data[address]^=1
                with self.assertRaises(restore.RestoreError) as caught:
                    restore.verify_current_state(client,source)
                self.assertFalse(caught.exception.uncertain)
                self.assertEqual(client.requests,[])
                self.assertEqual(client.writes,[])

    def test_manual_proof_follows_only_bounded_aligned_nonzero_player_pointers(self):
        for pointer in (0,0x700000,store.EE_MEMORY_SIZE-0x20,0xFFFFFFF0,0x700001):
            with self.subTest(pointer=hex(pointer)),tempfile.TemporaryDirectory() as folder:
                _root,_ini,source,target,client=self.fixture(Path(folder))
                struct.pack_into('<I',target,profile.PLAYER_TRANSFORM_POINTER,pointer)
                archive(source,target)
                client.data[:]=target
                with patch.object(client,'read_bytes',wraps=client.read_bytes) as reader:
                    result=restore.verify_current_state(client,source)
                self.assertTrue(result['verified_current'])
                reads=[call.args for call in reader.call_args_list]
                self.assertTrue(all(0<=address<=store.EE_MEMORY_SIZE-length for address,length in reads))
                self.assertEqual((pointer,0x40) in reads,pointer==0x700000)
                self.assertEqual(client.requests,[])
                self.assertEqual(client.writes,[])

    def test_manifest_hash_binds_both_apis_before_any_marker_or_load(self):
        for automatic in (False,True):
            with self.subTest(automatic=automatic),tempfile.TemporaryDirectory() as folder:
                root,_ini,source,target,client=self.fixture(Path(folder))
                manifest_hash=hashlib.sha256(source.read_bytes()).hexdigest()
                # A valid finalized archive replaces the file after the caller
                # has checked its manifest. The callee must bind that same hash.
                target[restore.PROOF_REGIONS[0][0]]^=1
                archive(source,target)
                client.data[:]=target
                with self.assertRaisesRegex(restore.RestoreError,'signature recorded') as caught:
                    if automatic:
                        restore.restore_state(client,root,source,expected_sha256=manifest_hash)
                    else:
                        restore.verify_current_state(client,source,expected_sha256=manifest_hash)
                self.assertFalse(caught.exception.uncertain)
                self.assertEqual(client.writes,[])
                self.assertEqual(client.requests,[])
                self.assertFalse((root/'sstates').exists())

    def test_expected_hash_rejects_invalid_values_and_accepts_exact_uppercase(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_ini,source,target,client=self.fixture(Path(folder))
            client.data[:]=target
            for expected in ('',False,1,'z'*64,'a'*63,'a'*65):
                for automatic in (False,True):
                    with self.subTest(expected=expected,automatic=automatic):
                        with self.assertRaisesRegex(restore.RestoreError,'expected signature') as caught:
                            if automatic:
                                restore.restore_state(client,root,source,expected_sha256=expected)
                            else:
                                restore.verify_current_state(client,source,expected_sha256=expected)
                        self.assertFalse(caught.exception.uncertain)
                        self.assertEqual(client.writes,[])
                        self.assertEqual(client.requests,[])
            expected=hashlib.sha256(source.read_bytes()).hexdigest().upper()
            self.assertTrue(restore.verify_current_state(client,source,expected_sha256=expected)['verified_current'])
            self.assertEqual(restore.restore_state(client,root,source,expected_sha256=expected)['loaded_slot'],9)


if __name__=='__main__':
    unittest.main()
