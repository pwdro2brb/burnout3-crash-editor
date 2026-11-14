"""State-export tests use generated zero RAM ZIPs, never game/emulator files."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor import state_store as store
from editor.pine import Status


def make_archive(path, size=store.EE_MEMORY_SIZE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        with archive.open('eeMemory.bin', 'w') as stream:
            block = bytes(1024*1024)
            remaining = size
            while remaining:
                count = min(remaining, len(block))
                stream.write(block[:count])
                remaining -= count
        archive.writestr('Version.id', b'synthetic test metadata')


def portable(root, *, folder='sstates', default='disabled', encoding='utf-8', root_keys=''):
    root.mkdir()
    (root/'portable.ini').write_bytes(b'')
    (root/'inis').mkdir()
    config = root/'inis'/'PCSX2_ui.ini'
    config.write_text(root_keys+f'[Folders]\nUseDefaultSavestates={default}\nSavestates={folder}\n', encoding=encoding)
    return config


class FakeClient:
    def __init__(self, write, *, delay=0):
        self.write = write
        self.delay = delay
        self.requests = []
        self.polls_after_request = 0
        self.current_status = Status.PAUSED
        self.pending = None

    def status(self):
        if self.pending is not None:
            self.polls_after_request += 1
            if self.polls_after_request >= self.delay:
                slot, self.pending = self.pending, None
                self.write(slot)
        return self.current_status

    def request_save_state(self, slot):
        self.requests.append(slot)
        if self.delay:
            self.pending = slot
        else:
            self.write(slot)


class StateExportTests(unittest.TestCase):
    def setUp(self):
        self.poll = patch.object(store, 'POLL_INTERVAL', .001)
        self.poll.start()
        self.addCleanup(self.poll.stop)

    def test_utf16_relative_nested_waits_for_queued_save_and_preserves_occupied_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, states = base/'emulator', base/'emulator'/'custom-states'
            config = portable(root, folder='custom-states', encoding='utf-16')
            config_before = config.read_bytes()
            occupied = states/store.STATE_NAME.format(slot=9)
            occupied.parent.mkdir()
            occupied.write_bytes(b'existing user state')
            created = []

            def save(slot):
                path = states/store.STATE_DIRECTORY/store.STATE_NAME.format(slot=slot)
                make_archive(path)
                created.append(path)

            client = FakeClient(save, delay=3)
            destination = base/'exports'/'edited.p2s'
            result = store.export_state(client, root, destination, timeout=2)
            self.assertEqual(client.requests, [8])
            self.assertGreaterEqual(client.polls_after_request, 3)
            self.assertEqual(occupied.read_bytes(), b'existing user state')
            self.assertEqual(config.read_bytes(), config_before)
            self.assertFalse(created[0].exists())
            self.assertTrue(result['temporary_removed'])
            self.assertFalse(result['warning'])
            self.assertEqual(result['saved_slot'], 8)
            self.assertEqual(result['path'], str(destination.resolve()))
            self.assertEqual(result['sha256'], hashlib.sha256(destination.read_bytes()).hexdigest())
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(archive.getinfo('eeMemory.bin').file_size, store.EE_MEMORY_SIZE)
                self.assertIsNone(archive.testzip())

    def test_utf8_absolute_folder_and_default_folder_flat_layout(self):
        for use_default in (False, True):
            with self.subTest(use_default=use_default), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                root = base/'emulator'
                states = root/'sstates' if use_default else base/'absolute-state-directory'
                configured = str(base/'ignored') if use_default else str(states)
                portable(root, folder=configured, default='enabled' if use_default else 'disabled', encoding='utf-8-sig')
                source = states/store.STATE_NAME.format(slot=9)
                client = FakeClient(lambda slot: make_archive(source))
                result = store.export_state(client, root, base/'flat.p2s', timeout=2)
                self.assertEqual(client.requests, [9])
                self.assertTrue(result['temporary_removed'])
                self.assertFalse(source.exists())

    def test_wx_root_keys_before_folders_are_supported_in_utf8_and_utf16(self):
        for encoding in ('utf-8-sig', 'utf-16'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as temporary:
                base, root = Path(temporary), Path(temporary)/'emulator'
                config = portable(root, folder='actual-folder', encoding=encoding,
                    root_keys='MainGuiPosition=421,186\nSavestates=wrong-root-folder\nUseDefaultSavestates=enabled\n')
                original = config.read_bytes()
                source = root/'actual-folder'/store.STATE_NAME.format(slot=9)
                client = FakeClient(lambda slot: make_archive(source))
                result = store.export_state(client, root, base/'wx-root-keys.p2s', timeout=2)
                self.assertEqual(client.requests, [9])
                self.assertTrue(result['temporary_removed'])
                self.assertEqual(config.read_bytes(), original)
                self.assertFalse((root/'wrong-root-folder').exists())
                self.assertFalse((root/'sstates').exists())

    def test_trailing_nul_newline_padding_is_read_only_in_utf8_and_utf16(self):
        for encoding in ('utf-8-sig', 'utf-16'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)/'emulator'
                config = portable(root, folder='padded-states', encoding=encoding,
                                  root_keys='MainGuiPosition=421,186\n')
                text = config.read_text(encoding=encoding)
                config.write_text(text+'\0'*4096+'\r\n\0\n', encoding=encoding)
                original = config.read_bytes()
                self.assertEqual(store._states_directory(root), (root/'padded-states').resolve())
                self.assertEqual(config.read_bytes(), original)

    def test_embedded_nul_is_rejected_instead_of_repairing_paths_or_keys(self):
        cases = ('Save\0states=sstates\n', 'Savestates=bad\0folder\n',
                 'Savestates=bad\0\n', '\0\n[More]\nKey=Value\n', '\0\n  ')
        for encoding in ('utf-8-sig', 'utf-16'):
            for invalid in cases:
                with self.subTest(encoding=encoding, invalid=repr(invalid)), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)/'emulator'
                    config = portable(root, encoding=encoding)
                    text = '[Folders]\nUseDefaultSavestates=disabled\n'+invalid
                    config.write_text(text, encoding=encoding)
                    original = config.read_bytes()
                    with self.assertRaisesRegex(store.StateStoreError, 'nulo'):
                        store._states_directory(root)
                    self.assertEqual(config.read_bytes(), original)

    def test_all_slots_occupied_in_either_layout_refuses_without_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, root = Path(temporary), Path(temporary)/'emulator'
            portable(root)
            originals = {}
            for slot in range(10):
                parent = root/'sstates' if slot % 2 else root/'sstates'/store.STATE_DIRECTORY
                parent.mkdir(parents=True, exist_ok=True)
                path = parent/store.STATE_NAME.format(slot=slot)
                originals[path] = f'user slot {slot}'.encode()
                path.write_bytes(originals[path])
            client = FakeClient(lambda slot: self.fail('Must not queue an occupied slot'))
            with self.assertRaisesRegex(store.StateStoreError, 'Todos os dez slots'):
                store.export_state(client, root, base/'export.p2s', timeout=1)
            self.assertEqual(client.requests, [])
            self.assertEqual({p: p.read_bytes() for p in originals}, originals)

    def test_invalid_preconditions_never_queue_or_replace_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, root = Path(temporary), Path(temporary)/'emulator'
            portable(root)
            client = FakeClient(lambda slot: self.fail('Invalid request was queued'))
            existing = base/'existing.p2s'
            existing.write_bytes(b'user archive')
            with self.assertRaises(store.StateStoreError):
                store.export_state(client, root, existing)
            self.assertEqual(existing.read_bytes(), b'user archive')
            for timeout in (0, -1, 21, True, float('nan')):
                with self.subTest(timeout=timeout), self.assertRaises(store.StateStoreError):
                    store.export_state(client, root, base/'unused.p2s', timeout=timeout)
            with self.assertRaises(store.StateStoreError):
                store.export_state(client, root, base/'wrong.txt')
            client.current_status = Status.RUNNING
            with self.assertRaises(store.StateStoreError):
                store.export_state(client, root, base/'running.p2s')
            client.current_status = Status.PAUSED
            (root/'portable.ini').unlink()
            with self.assertRaises(store.StateStoreError):
                store.export_state(client, root, base/'not-portable.p2s')
            self.assertEqual(client.requests, [])

    def test_invalid_or_ambiguous_capture_is_preserved_without_destination_copy(self):
        for case in ('not_zip', 'short_ee', 'two_candidates'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                base, root = Path(temporary), Path(temporary)/'emulator'
                portable(root)
                states = root/'sstates'
                paths = store._candidates(states.resolve(), 9)

                def save(slot):
                    if case == 'not_zip':
                        paths[0].parent.mkdir(parents=True)
                        paths[0].write_bytes(b'incomplete ZIP')
                    elif case == 'short_ee':
                        make_archive(paths[0], 1024)
                    else:
                        make_archive(paths[0])
                        make_archive(paths[1])

                client = FakeClient(save)
                with self.assertRaises(store.StateStoreError):
                    store.export_state(client, root, base/'invalid.p2s', timeout=.02)
                self.assertEqual(client.requests, [9])
                self.assertTrue(paths[0].exists())
                self.assertFalse((base/'invalid.p2s').exists())
                if case == 'two_candidates':
                    self.assertTrue(paths[1].exists())

    def test_destination_created_after_preflight_is_not_overwritten_and_slot_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, root = Path(temporary), Path(temporary)/'emulator'
            portable(root)
            destination = base/'race.p2s'
            source = root/'sstates'/store.STATE_NAME.format(slot=9)

            def save(slot):
                make_archive(source)
                destination.write_bytes(b'new user file')

            with self.assertRaises(store.StateStoreError):
                store.export_state(FakeClient(save), root, destination, timeout=2)
            self.assertEqual(destination.read_bytes(), b'new user file')
            self.assertTrue(source.exists())

    def test_source_changed_after_copy_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, root = Path(temporary), Path(temporary)/'emulator'
            portable(root)
            source = root/'sstates'/store.STATE_NAME.format(slot=9)
            destination = base/'changed.p2s'
            original_copy = store._copy_exclusive

            def copy_then_change(incoming, outgoing):
                original_copy(incoming, outgoing)
                with incoming.open('ab') as stream:
                    stream.write(b'changed after copy')

            with patch.object(store, '_copy_exclusive', side_effect=copy_then_change):
                with self.assertRaisesRegex(store.StateStoreError, 'cópia não pôde ser confirmada'):
                    store.export_state(FakeClient(lambda slot: make_archive(source)), root, destination, timeout=2)
            self.assertTrue(source.exists())
            self.assertTrue(destination.exists())
            self.assertNotEqual(hashlib.sha256(source.read_bytes()).digest(), hashlib.sha256(destination.read_bytes()).digest())

    def test_cleanup_failure_returns_verified_copy_and_preserves_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, root = Path(temporary), Path(temporary)/'emulator'
            portable(root)
            source = root/'sstates'/store.STATE_NAME.format(slot=9)
            destination = base/'kept.p2s'
            with patch.object(Path, 'unlink', side_effect=PermissionError('Synthetic locked slot')):
                result = store.export_state(FakeClient(lambda slot: make_archive(source)), root, destination, timeout=2)
            self.assertTrue(result['warning'])
            self.assertFalse(result['temporary_removed'])
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), destination.read_bytes())
            self.assertEqual(result['sha256'], hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
