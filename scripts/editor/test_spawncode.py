"""Control-flow/ABI tests for emitted bytes; no emulator or game assets needed."""
import struct
import unittest

from spawncode import (ALLOCATOR, CAVE, DATA, END, HOOK, MAGIC,
                       MAGIC_ADDRESS, MANAGER, NONCE_ADDRESS, ORIGINAL,
                       RETURN, build_spawn)


PARAMS = dict(manager=MANAGER, type_code=2, model_hash=0x5B55839B95F21600,
              path_descriptor=0x522EC8, progression=240.131047893,
              speed=30, spacing=0.0, variant=3, nonce=b'0123456789abcdef')


class RoutineMachine:
    """Decode the emitted subset independently and stub only the allocator.

    This deliberately checks branch/delay-slot flow and full-width saved
    registers, rather than claiming to emulate EE physics or the allocator.
    """
    def __init__(self, result):
        self.request = build_spawn(**PARAMS)
        self.memory = {}
        self.store(CAVE, self.request['scratch_bytes'])
        self.gpr = [0] * 32
        self.fpr = [0x3F000000 + n for n in range(32)]
        self.gpr[29] = self.sp = 0x1FF000
        self.gpr[2] = self.saved_v0 = 0xAABBCCDDEEFF00112233445566778899
        self.gpr[3] = self.saved_v1 = 0x99887766554433221100FFEEDDCCBBAA
        self.saved_fpr = self.fpr.copy()
        self.saved_s8 = 0x7766554433221100FFEEDDCCBBAA0099
        self.return_ra = 0x19A69C
        self.store_int(self.sp + 0xA0, self.return_ra, 8)
        self.store_int(self.sp + 0x90, self.saved_s8, 16)
        self.store_int(self.sp + 8, 0x41424344, 4)
        self.calls = 0
        self.result = result
        self.completions = []

    def load(self, address, size):
        return bytes(self.memory.get(address + n, 0) for n in range(size))

    def store(self, address, value):
        for n, byte in enumerate(value):
            self.memory[address + n] = byte

    def store_int(self, address, value, size):
        self.store(address, (value & ((1 << (8 * size)) - 1)).to_bytes(size, 'little'))

    def integer(self, address, size):
        return int.from_bytes(self.load(address, size), 'little')

    def allocator(self):
        self.calls += 1
        self.asserted_args = {
            'manager': self.gpr[4], 'type_code': self.gpr[5],
            'model_hash': self.gpr[6], 'secondary_type': self.gpr[7],
            'secondary_hash': self.gpr[8], 'path_descriptor': self.gpr[9],
            'variant': self.gpr[10], 'secondary_variant': self.gpr[11],
            'flags': self.integer(self.gpr[29], 1),
            'floats': [struct.unpack('<f', self.fpr[n].to_bytes(4, 'little'))[0]
                       for n in (12, 13, 14)],
            'state_during_call': self.integer(DATA, 4),
            'stack_alignment': self.gpr[29] % 16,
        }
        back = self.gpr[31]
        # Model the documented clobbers, including the parameter-base register.
        for reg in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 24, 25):
            self.gpr[reg] = 0x12345678
        for reg in (0, 1, 12, 13, 14, 22):
            self.fpr[reg] = 0xDEADBEEF
        self.gpr[2] = self.result
        if self.result:
            self.store_int(self.result + 0x114, 0x551C30, 4)
        return back

    def run(self):
        pc, delayed = CAVE, None
        for _ in range(256):
            if pc == ALLOCATOR:
                pc = self.allocator()
                continue
            if pc == RETURN:
                return
            if not CAVE <= pc < CAVE + len(self.request['code_bytes']):
                raise AssertionError(f'Unexpected execution target {pc:#x}')
            word = self.integer(pc, 4)
            op, rs, rt = word >> 26, (word >> 21) & 31, (word >> 16) & 31
            imm = word & 65535
            signed = imm if imm < 32768 else imm - 65536
            next_jump = None
            address = self.gpr[rs] + signed
            if word == 0:
                pass
            elif op == 9:
                self.gpr[rt] = self.gpr[rs] + signed
            elif op == 15:
                self.gpr[rt] = imm << 16
            elif op == 13:
                self.gpr[rt] = self.gpr[rs] | imm
            elif op in (35, 55, 30):
                self.gpr[rt] = self.integer(address, {35: 4, 55: 8, 30: 16}[op])
            elif op in (43, 31):
                self.store_int(address, self.gpr[rt], 4 if op == 43 else 16)
                if address == DATA and self.gpr[rt] == 2:
                    self.completions.append((self.integer(DATA + 4, 4),
                                             self.integer(DATA + 8, 4)))
            elif op == 57:
                self.store_int(address, self.fpr[rt], 4)
            elif op == 49:
                self.fpr[rt] = self.integer(address, 4)
            elif op == 0 and word & 63 == 0x21:
                self.gpr[(word >> 11) & 31] = self.gpr[rs] + self.gpr[rt]
            elif op in (4, 5):
                equal = self.gpr[rs] == self.gpr[rt]
                next_jump = pc + 4 + signed * 4 if equal == (op == 4) else pc + 8
            elif op in (2, 3):
                next_jump = ((pc + 4) & 0xF0000000) | ((word & 0x3FFFFFF) << 2)
                if op == 3:
                    self.gpr[31] = pc + 8
            else:
                raise AssertionError(f'Unsupported generated instruction {word:#x}')
            if delayed is not None and next_jump is not None:
                raise AssertionError('Control transfer emitted inside a delay slot')
            next_pc = delayed if delayed is not None else pc + 4
            pc, delayed = next_pc, next_jump
            self.gpr[0] = 0
        raise AssertionError('Routine did not return within its bound')


class SpawnCodeTests(unittest.TestCase):
    def test_profile_epilogue_and_original_encoding(self):
        self.assertEqual(HOOK, 0x166D6C)
        self.assertEqual(ORIGINAL, struct.pack('<II', 0xC7B60008, 0x7BBE0090))
        r = build_spawn(**PARAMS)
        words = struct.unpack('<' + 'I' * (len(r['code_bytes']) // 4), r['code_bytes'])
        self.assertEqual(words[0], 0x27BDFF80)
        self.assertIn(0x7FA20020, words)  # sq v0,0x20(sp), full128 bits.
        self.assertIn(0x7BA20020, words)  # lq v0,0x20(sp).
        self.assertEqual(words[-5:-2], (0xDFBF00A0, 0xC7B60008, 0x7BBE0090))
        self.assertEqual(words[-2:], (0x08000000 | (RETURN >> 2), 0))

    def test_parameters_and_owned_scratch(self):
        r = build_spawn(**PARAMS)
        scratch = r['scratch_bytes']
        self.assertEqual(len(scratch), END - CAVE)
        base = DATA - CAVE
        self.assertEqual(scratch[base:base + 12], bytes(12))
        self.assertEqual(struct.unpack_from('<I', scratch, base + 0x10)[0], MANAGER)
        self.assertEqual(struct.unpack_from('<Q', scratch, base + 0x18)[0], PARAMS['model_hash'])
        self.assertEqual(scratch[MAGIC_ADDRESS - CAVE:NONCE_ADDRESS - CAVE], MAGIC)
        self.assertEqual(scratch[NONCE_ADDRESS - CAVE:NONCE_ADDRESS - CAVE + 16], PARAMS['nonce'])

    def check_execution(self, returned):
        m = RoutineMachine(returned)
        m.run()
        self.assertEqual(m.calls, 1)
        args = m.asserted_args
        for key in ('manager', 'type_code', 'model_hash', 'path_descriptor', 'variant'):
            self.assertEqual(args[key], PARAMS[key])
        for key in ('secondary_type', 'secondary_hash', 'secondary_variant', 'flags', 'stack_alignment'):
            self.assertEqual(args[key], 0)
        self.assertEqual(args['state_during_call'], 1)
        self.assertEqual(args['floats'], [struct.unpack('<f', struct.pack('<f', PARAMS[k]))[0]
                                         for k in ('progression', 'speed', 'spacing')])
        self.assertEqual(m.completions, [(returned, 0x551C30 if returned else 0)])
        self.assertEqual(m.integer(DATA, 4), 2)
        self.assertEqual(m.gpr[29], m.sp)
        self.assertEqual(m.gpr[2], m.saved_v0)
        self.assertEqual(m.gpr[3], m.saved_v1)
        self.assertEqual(m.gpr[30], m.saved_s8)
        self.assertEqual(m.gpr[31], m.return_ra)
        self.assertEqual(m.fpr[22], 0x41424344)
        for reg in (0, 1, 12, 13, 14):
            self.assertEqual(m.fpr[reg], m.saved_fpr[reg])
        immutable = bytearray(m.load(CAVE, END - CAVE))
        immutable[DATA - CAVE:DATA - CAVE + 12] = bytes(12)
        self.assertEqual(bytes(immutable), m.request['scratch_bytes'])
        # A second traversal of the installed routine must not allocate again.
        m.run()
        self.assertEqual(m.calls, 1)
        self.assertEqual(len(m.completions), 1)

    def test_allocator_success_and_one_shot(self):
        self.check_execution(0x53AE10)

    def test_allocator_failure_marks_done_without_dereferencing_zero(self):
        self.check_execution(0)

    def test_invalid_requests_rejected_before_emitting_bytes(self):
        invalid = dict(manager=MANAGER + 4, type_code=3, model_hash=0,
                       path_descriptor=0x522EC9, progression=float('nan'),
                       speed=-1, spacing=float('inf'), variant=8, nonce=b'short')
        for key, value in invalid.items():
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    build_spawn(**{**PARAMS, key: value})
        with self.assertRaises(ValueError):
            build_spawn(**{**PARAMS, 'type_code': True})


if __name__ == '__main__':
    unittest.main()
