"""Wire-level tests using an isolated scripted socket, never an emulator."""
import struct
import unittest
from unittest.mock import patch

import pine as p


def reply(data=b'', status=0):
    return struct.pack('<I', 5 + len(data)) + bytes((status,)) + data


def integer(value):
    return reply(struct.pack('<I', value))


def string(text):
    data = text.encode() + b'\0'
    return struct.pack('<I', len(data)) + data


class ScriptedSocket:
    def __init__(self, responses, fragment=1):
        self.incoming = bytearray(b''.join(responses))
        self.sent = []
        self.fragment = fragment
        self.closed = False

    def sendall(self, data):
        if self.closed:
            raise OSError('closed')
        self.sent.append(data)

    def recv(self, size):
        count = min(size, self.fragment, len(self.incoming))
        value = bytes(self.incoming[:count])
        del self.incoming[:count]
        return value

    def close(self):
        self.closed = True


def client(responses, *, allow=False, fragment=1):
    instance = p.PineClient(allow_writes=allow)
    sock = ScriptedSocket(responses, fragment)
    instance._socket = sock
    return instance, sock


class WireTests(unittest.TestCase):
    def test_fragmented_batched_memory_reads_have_exact_frames(self):
        values = [0xA4, 0xBB11, 0x12345678, 0xFEDCBA9876543210]
        requests = [(0x10, 1), (0x12, 2), (0x20, 4), (0x28, 8)]
        data = b''.join(v.to_bytes(w, 'little') for v, (_, w) in zip(values, requests))
        c, sock = client([reply(data)])
        self.assertEqual(c.read_many(requests), values)
        payload = b''.join(bytes((i,)) + struct.pack('<I', a)
                           for i, (a, _) in enumerate(requests))
        self.assertEqual(sock.sent, [struct.pack('<I', 4 + len(payload)) + payload])

    def test_metadata_length_and_nul_framing(self):
        c, sock = client([reply(string('PCSX2 Nightly - v1.7.2521')
                               + string('SLUS-21050') + string('BEBF8793'))])
        self.assertEqual(c.identity()['game_id'], 'SLUS-21050')
        self.assertEqual(sock.sent[0], b'\x07\0\0\0\x08\x0c\x0d')

    def test_read_bytes_handles_alignment_and_batch_boundaries(self):
        data = bytes(range(1, 19))
        c, sock = client([reply(data[:3]), reply(data[3:15]), reply(data[15:])])
        with patch.object(p, 'MAX_COMMANDS', 2):
            self.assertEqual(c.read_bytes(1, 18), data)
        self.assertEqual(len(sock.sent), 3)

    def test_readonly_client_cannot_mutate_or_save(self):
        c, sock = client([])
        with self.assertRaises(p.PineWriteDisabled):
            c.write(0x100, 1)
        with self.assertRaises(p.PineWriteDisabled):
            c.request_save_state(5)
        self.assertEqual(sock.sent, [])

    def test_invalid_write_batch_preflight_sends_nothing(self):
        c, sock = client([], allow=True)
        with self.assertRaises(ValueError):
            c.write_many([p.Write(0x100, 4, 1), p.Write(0x104, 1, 256)])
        self.assertEqual(sock.sent, [])

    def test_running_vm_prevents_guarded_write(self):
        c, sock = client([integer(0)], allow=True)
        with self.assertRaises(p.PineNotPaused):
            c.write(0x100, 4)
        self.assertEqual(sock.sent, [b'\x05\0\0\0\x0f'])

    def test_write_bytes_uses_aligned_exact_coverage(self):
        c, sock = client([integer(1), reply(), integer(1)], allow=True)
        c.write_bytes(1, bytes(range(1, 19)))
        payload = sock.sent[1][4:]
        expected = b''.join(bytes((4 + (1,2,4,8).index(w),))
                            + struct.pack('<I', a) + bytes(range(a, a+w))
                            for a,w in [(1,1),(2,2),(4,4),(8,8),(16,2),(18,1)])
        self.assertEqual(payload, expected)
        c2, sock2 = client([], allow=True)
        with self.assertRaises(ValueError):
            c2.write_bytes(0, bytes(65537))
        self.assertEqual(sock2.sent, [])

    def test_paused_guard_write_and_postcheck(self):
        c, sock = client([integer(1), reply(), integer(1)], allow=True)
        c.write(0x100, 0x01020304)
        self.assertEqual(sock.sent[1], b'\x0d\0\0\0\x06\0\x01\0\0\x04\x03\x02\x01')
        self.assertEqual(len(sock.sent), 3)

    def test_resume_race_is_reported_without_blind_rollback(self):
        c, sock = client([integer(1), reply(), integer(0)], allow=True)
        with self.assertRaises(p.PineNotPaused):
            c.write(0x100, 1)
        self.assertEqual(len(sock.sent), 3)

    def test_patch_expected_mismatch_prevents_all_writes(self):
        c, sock = client([integer(1), integer(42)], allow=True)
        with self.assertRaises(p.PinePatchConflict):
            c.apply_patch([p.Patch(0x100, 4, 41, 99)])
        self.assertEqual(len(sock.sent), 2)
        self.assertEqual(sock.sent[1][4], 2)

    def test_patch_checks_initial_expected_and_final_readback(self):
        c, sock = client([integer(1), integer(41), integer(1), reply(), integer(1), integer(99)], allow=True)
        c.apply_patch([p.Patch(0x100, 4, 41, 99)])
        self.assertEqual(len(sock.sent), 6)

    def test_server_failure_closes_no_retry_and_has_partial_batch_warning(self):
        c, sock = client([reply(status=255)])
        with self.assertRaisesRegex(p.PineRemoteError, 'earlier commands'):
            c.read(0x100)
        self.assertTrue(sock.closed)
        self.assertEqual(len(sock.sent), 1)

    def test_truncated_reply_is_ambiguous_and_not_retried(self):
        c, sock = client([b'\x09\0\0\0\0\x01'])
        with self.assertRaises(p.PineTransportError) as found:
            c.read(0x100)
        self.assertTrue(found.exception.may_have_executed)
        self.assertTrue(sock.closed)
        self.assertEqual(len(sock.sent), 1)

    def test_malformed_lengths_and_strings_close(self):
        for data in [b'\x04\0\0\0', struct.pack('<I', p.MAX_REPLY + 1),
                     reply(struct.pack('<I', 2) + b'AB')]:
            c, sock = client([data])
            with self.assertRaises(p.PineProtocolError):
                c.identity()
            self.assertTrue(sock.closed)

    def test_state_command_is_only_an_ack_and_slot_is_bounded(self):
        c, sock = client([integer(1), reply()], allow=True)
        c.request_save_state(5)
        self.assertEqual(sock.sent[1], b'\x06\0\0\0\x09\x05')
        c2, sock2 = client([], allow=True)
        with self.assertRaises(ValueError):
            c2.request_load_state(10)
        self.assertEqual(sock2.sent, [])

    def test_loopback_and_physical_ram_boundaries(self):
        with self.assertRaises(TypeError):
            p.PineClient(allow_writes='false')
        for host in ['192.168.1.2', 'localhost', 'example.com']:
            with self.assertRaises(ValueError):
                p.PineClient(host)
        c, sock = client([])
        for address, width in [(1, 4), (p.RAM_SIZE, 1), (-1, 1), (0x100, 3)]:
            with self.assertRaises(ValueError):
                c.read(address, width)
        with self.assertRaises(ValueError):
            c.read_bytes(p.RAM_SIZE - 2, 3)
        self.assertEqual(sock.sent, [])


if __name__ == '__main__':
    unittest.main()
