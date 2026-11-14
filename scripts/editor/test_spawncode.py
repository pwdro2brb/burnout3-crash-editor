"""Control-flow/ABI tests for emitted bytes; no emulator or game assets needed."""
import hashlib
import base64
import struct
import unittest
import zlib
from unittest.mock import Mock, patch

from spawncode import (ALLOCATOR, BATCH_CODE_STRIDE, BATCH_MAX_REQUESTS,
                       BATCH_RECORD_BASE, BATCH_RECORD_STRIDE,
                       CAVE, DATA, END, HOOK, LANDING, LANDING_SIZE, MAGIC,
                       MAGIC_ADDRESS, MANAGER, NONCE_ADDRESS, ORIGINAL,
                       PROBE_SIZE, RETURN, SECONDARY_MODEL_OFFSET,
                       build_batch, build_spawn, clean_batch_scratch,
                       completion_token, match_batch_scratch)


PARAMS = dict(manager=MANAGER, type_code=2, model_hash=0x5B55839B95F21600,
              path_descriptor=0x522EC8, progression=240.131047893,
              speed=30, spacing=0.0, variant=3, nonce=b'0123456789abcdef')
PAIR_PARAMS = {**PARAMS, 'type_code': 4,
               'model_hash': 0xFEDCBA9887654321,
               'secondary_type_code': 11,
               'secondary_model_hash': 0x8BADF00D01234567}

# Frozen own-code fixture from the Landing-based v1 format, with three
# synthetic completed records. It contains no game data or emulator snapshot.
V1_FIXTURE_B85 = (
    'c${nazgJy>VNtyS!{T}eh6T@E7#2SFU|93qhhgpW0ETtXxfvvF7_2PK85k`3r5G5*8GwM1K|%${UoXI*($B=esv^Olc3;'
    'tgfkDv$h$BEMxKtDvH2WDC7OdA`&^fNdpnKeaLGSpKNvu2|S(uqD3`*;n85{&aVj_&rJsb?m>zSZt1Kn~Q=$7L^w;'
    'Tt$<v7qS$ARvw2D-Dlfnl%u0*3wfIT*GbpTMxM+Tjcn2LqX)fe8OM;PF2T)c@QJ>?#%v8uvl|XC%V^4OH}h1C9O9V2#'
    '`Vj9B8IiJ17erk?-Bfac}oTAJ^xmav(?AOSSjV*R$`5;hz_HpncnefE~-AhSQ5CqJx4!6+C7qhJ(_g5d&~fLLH%FoS_i'
    'D46e15(JSD`!scSb7=GlJqW)?vA~&u;e#Wo<~td?x|A6*Fc=sb8Jn1znOj&UCMBn&rXkxuVSO+|1DgGc&Z+G)cHQ|0w?'
    'DBEX#Wqm{pqgCjJzM#c2mQCfsMfo7YO-(VUaV)IBNTU6pVsVFmQkgiOoy{^J$;|E!M}*W+l5%0{~`Y<ev'
)


class RoutineMachine:
    """Decode the emitted subset independently and stub only the allocator.

    This deliberately checks branch/delay-slot flow and full-width saved
    registers, rather than claiming to emulate EE physics or the allocator.
    """
    def __init__(self, result, params=None, request=None):
        self.request = request if request is not None else build_spawn(**(PARAMS if params is None else params))
        self.code_addresses = {row['address'] for row in self.request['rows']}
        self.probe_addresses = ([probe['address'] for probe in self.request['probes']]
                                if 'probes' in self.request else [self.request['probe_address']])
        self.memory = {}
        self.store(CAVE, self.request['scratch_bytes'])
        self.store(HOOK, self.request['hook_bytes'])
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
        self.asserted_calls = []
        self.completions = []
        self.completed_probe_addresses = []
        self.events = []
        self.master_publications = []
        self.returned = False

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
        probe_address = self.gpr[25]
        self.asserted_args = {
            'manager': self.gpr[4], 'type_code': self.gpr[5],
            'model_hash': self.gpr[6], 'secondary_type': self.gpr[7],
            'secondary_hash': self.gpr[8], 'path_descriptor': self.gpr[9],
            'variant': self.gpr[10], 'secondary_variant': self.gpr[11],
            'flags': self.integer(self.gpr[29], 1),
            'floats': [struct.unpack('<f', self.fpr[n].to_bytes(4, 'little'))[0]
                       for n in (12, 13, 14)],
            'state_during_call': self.integer(probe_address, 4),
            'probe_address': probe_address,
            'stack_pointer': self.gpr[29],
            'stack_alignment': self.gpr[29] % 16,
        }
        self.asserted_calls.append(self.asserted_args)
        back = self.gpr[31]
        # Model the documented clobbers, including the parameter-base register.
        for reg in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 24, 25):
            self.gpr[reg] = 0x12345678
        for reg in (0, 1, 12, 13, 14, 22):
            self.fpr[reg] = 0xDEADBEEF
        result = self.result[self.calls - 1] if isinstance(self.result, (list, tuple)) else self.result
        self.gpr[2] = result
        if result:
            self.store_int(result + 0x114, 0x551C30 + (self.calls - 1) * 0x50, 4)
        return back

    def run(self, *, continuation=None, stop_after=None):
        pc, delayed = (CAVE, None) if continuation is None else continuation
        for _ in range(256 * len(self.probe_addresses)):
            if pc == ALLOCATOR:
                pc = self.allocator()
                continue
            if pc == RETURN:
                self.returned = True
                return
            if pc not in self.code_addresses:
                raise AssertionError(f'Unexpected execution target {pc:#x}')
            word = self.integer(pc, 4)
            op, rs, rt = word >> 26, (word >> 21) & 31, (word >> 16) & 31
            imm = word & 65535
            signed = imm if imm < 32768 else imm - 65536
            next_jump = None
            instruction_address = pc
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
                width = 4 if op == 43 else 16
                value = self.gpr[rt] & ((1 << (8 * width)) - 1)
                self.store_int(address, value, width)
                self.events.append((pc, address, value))
                if address in self.probe_addresses and self.gpr[rt] == 2:
                    self.completions.append((self.integer(address + 4, 4),
                                             self.integer(address + 8, 4)))
                    self.completed_probe_addresses.append(address)
                if address == self.request.get('completion_address'):
                    self.master_publications.append({'pc': pc, 'state': self.integer(address, 4),
                                                     'hook': self.load(HOOK, 8)})
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
            if instruction_address == stop_after:
                return pc, delayed
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

    def check_execution(self, returned, params=None):
        params = PARAMS if params is None else params
        m = RoutineMachine(returned, params)
        m.run()
        self.assertEqual(m.calls, 1)
        args = m.asserted_args
        for key in ('manager', 'type_code', 'model_hash', 'path_descriptor', 'variant'):
            self.assertEqual(args[key], params[key])
        self.assertEqual(args['secondary_type'], params.get('secondary_type_code', 0))
        self.assertEqual(args['secondary_hash'], params.get('secondary_model_hash', 0))
        for key in ('secondary_variant', 'flags', 'stack_alignment'):
            self.assertEqual(args[key], 0)
        self.assertEqual(args['state_during_call'], 1)
        self.assertEqual(args['floats'], [struct.unpack('<f', struct.pack('<f', params[k]))[0]
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

    def test_independent_requests_preserve_previous_bytes(self):
        # Captured before adding paired support: preserve the proven 204-byte
        # routine and its immutable data layout for both existing constructors.
        cases = (
            (1, 0, 'e21e1ca95b9d63bb4d17ef2166bcb51e6c2ff384f2670f19e1ac21089860fedc',
             'b942171078c3042d24b9322cd6271b128f0c6415e7afc05918711c669b72ae59'),
            (2, 3, '4dd916c14363d0319b979e7b671c4ee7ac7284e52c9a7213a734a8213be40d89',
             '583cbb7ee786171f8abb69a926a00006b3259d72d9e2a32e2407a4340c92bf1e'),
        )
        for type_code, variant, code_digest, scratch_digest in cases:
            with self.subTest(type_code=type_code):
                params = {**PARAMS, 'type_code': type_code, 'variant': variant}
                request = build_spawn(**params)
                self.assertEqual(hashlib.sha256(request['code_bytes']).hexdigest(), code_digest)
                self.assertEqual(hashlib.sha256(request['scratch_bytes']).hexdigest(), scratch_digest)
                self.check_execution(0x53AE10, params)

    def test_pair_keeps_hook_probe_and_owned_scratch_contract(self):
        independent = build_spawn(**PARAMS)
        paired = build_spawn(**PAIR_PARAMS)
        self.assertEqual(paired['hook_bytes'], independent['hook_bytes'])
        self.assertEqual(len(paired['code_bytes']), len(independent['code_bytes']))
        self.assertEqual(paired['probe_size'], PROBE_SIZE)
        self.assertEqual(PROBE_SIZE, 12)
        self.assertEqual(SECONDARY_MODEL_OFFSET, 0x38)
        self.assertEqual(struct.unpack_from('<Q', paired['scratch_bytes'],
                                           DATA - CAVE + SECONDARY_MODEL_OFFSET)[0],
                         PAIR_PARAMS['secondary_model_hash'])
        words = struct.unpack('<' + 'I' * (len(paired['code_bytes']) // 4), paired['code_bytes'])
        self.assertIn(0x2407000B, words)  # addiu a3,zero,11.
        self.assertIn(0xDF280038, words)  # ld t0,0x38(t9), the full secondary ID.
        self.assertEqual(paired['scratch_bytes'][DATA - CAVE:DATA - CAVE + PROBE_SIZE],
                         bytes(PROBE_SIZE))

    def test_pair_passes_both_full_width_ids_and_completes_once(self):
        for returned in (0, 0x53AE10):
            with self.subTest(returned=returned):
                self.check_execution(returned, PAIR_PARAMS)

    def test_single_constructor_types_three_and_five_preserve_independent_abi(self):
        for type_code in (3, 5):
            with self.subTest(type_code=type_code):
                self.check_execution(0x53AE10, {**PARAMS, 'type_code': type_code})
                with self.assertRaises(ValueError):
                    build_spawn(**{**PAIR_PARAMS, 'type_code': type_code})
        for type_code in (0, 6, 7, 8, 9, 10, 11):
            with self.subTest(rejected_type=type_code):
                with self.assertRaises(ValueError):
                    build_spawn(**{**PARAMS, 'type_code': type_code})

    def test_allocator_success_and_one_shot(self):
        self.check_execution(0x53AE10)

    def test_allocator_failure_marks_done_without_dereferencing_zero(self):
        self.check_execution(0)

    def test_invalid_requests_rejected_before_emitting_bytes(self):
        invalid = dict(manager=MANAGER + 4, type_code=6, model_hash=0,
                       path_descriptor=0x522EC9, progression=float('nan'),
                       speed=-1, spacing=float('inf'), variant=8, nonce=b'short')
        for key, value in invalid.items():
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    build_spawn(**{**PARAMS, key: value})
        with self.assertRaises(ValueError):
            build_spawn(**{**PARAMS, 'type_code': True})

    def test_unlinked_or_invalid_secondary_components_rejected(self):
        cases = (
            {**PARAMS, 'type_code': 4},
            {**PARAMS, 'type_code': 11},
            {**PAIR_PARAMS, 'secondary_type_code': 0},
            {**PAIR_PARAMS, 'secondary_type_code': 2},
            {**PAIR_PARAMS, 'secondary_type_code': True},
            {**PAIR_PARAMS, 'secondary_model_hash': 0},
            {**PAIR_PARAMS, 'secondary_model_hash': -1},
            {**PAIR_PARAMS, 'secondary_model_hash': 1 << 64},
            {**PAIR_PARAMS, 'secondary_model_hash': True},
            {**PAIR_PARAMS, 'secondary_model_hash': 1.0},
            {**PARAMS, 'secondary_model_hash': PAIR_PARAMS['secondary_model_hash']},
            {**PARAMS, 'secondary_type_code': 11},
            {**PAIR_PARAMS, 'type_code': 1},
        )
        for index, params in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    build_spawn(**params)

    @staticmethod
    def batch_requests(count):
        requests = []
        for index in range(count):
            params = dict(PAIR_PARAMS if index % 3 == 1 else PARAMS)
            params.pop('nonce')
            params['progression'] += index * 1.25
            params['speed'] += index
            params['variant'] = index % 8
            if index % 3 == 2:
                params['type_code'] = 1
            requests.append(params)
        return requests

    def test_batch_layout_and_all_relocated_targets(self):
        requests = self.batch_requests(BATCH_MAX_REQUESTS)
        batch = build_batch(requests, PARAMS['nonce'])
        scratch = batch['scratch_bytes']
        self.assertEqual(len(scratch), 4096)
        self.assertEqual(batch['hook_bytes'], build_spawn(**PARAMS)['hook_bytes'])
        self.assertEqual(batch['request_count'], 8)
        self.assertEqual(batch['completion_address'], DATA)
        self.assertEqual(batch['landing_address'], LANDING)
        self.assertEqual(batch['format_version'], 2)
        self.assertEqual(batch['completion_token'], completion_token(PARAMS['nonce']))
        self.assertEqual(struct.unpack_from('<I', scratch, DATA - CAVE + 4)[0], batch['completion_token'])
        self.assertEqual(struct.unpack_from('<I', scratch, DATA - CAVE + 0x0C)[0], 8)
        self.assertEqual(scratch[MAGIC_ADDRESS - CAVE:NONCE_ADDRESS - CAVE], MAGIC)
        self.assertEqual(scratch[NONCE_ADDRESS - CAVE:NONCE_ADDRESS - CAVE + 16], PARAMS['nonce'])
        expected_probes = [{'address': BATCH_RECORD_BASE + index * BATCH_RECORD_STRIDE,
                            'offset': BATCH_RECORD_BASE - CAVE + index * BATCH_RECORD_STRIDE}
                           for index in range(8)]
        self.assertEqual(batch['probes'], expected_probes)
        self.assertLessEqual(CAVE + len(batch['code_bytes']), BATCH_RECORD_BASE)
        self.assertLessEqual(BATCH_RECORD_BASE + 8 * BATCH_RECORD_STRIDE, DATA)
        for index, probe in enumerate(batch['probes']):
            with self.subTest(index=index):
                start = CAVE + index * BATCH_CODE_STRIDE
                rows = [row for row in batch['rows'] if start <= row['address'] < start + BATCH_CODE_STRIDE]
                code_size = 204 if index < 7 else 252
                self.assertEqual(len(rows) * 4, code_size)
                self.assertLessEqual(code_size, BATCH_CODE_STRIDE)
                target = start + BATCH_CODE_STRIDE if index < 7 else LANDING
                self.assertEqual(rows[-2]['word'], 0x08000000 | (target >> 2))
                self.assertEqual(rows[-1]['word'], 0)
                self.assertIn(0x0C000000 | (ALLOCATOR >> 2), [row['word'] for row in rows])
                for row in rows:
                    if 'branch_target' in row:
                        self.assertTrue(start <= row['branch_target'] < start + code_size)
                offset = probe['offset']
                self.assertEqual(scratch[offset:offset + PROBE_SIZE], bytes(PROBE_SIZE))
                self.assertEqual(scratch[offset + 0x60:offset + 0x68], MAGIC)
                self.assertEqual(scratch[offset + 0x68:offset + 0x78], PARAMS['nonce'])
                self.assertEqual(struct.unpack_from('<Q', scratch, offset + 0x18)[0], requests[index]['model_hash'])
                self.assertEqual(struct.unpack_from('<Q', scratch, offset + 0x38)[0], requests[index].get('secondary_model_hash', 0))

    def check_batch_execution(self, count, results):
        requests = self.batch_requests(count)
        batch = build_batch(requests, PARAMS['nonce'])
        machine = RoutineMachine(results, request=batch)
        machine.run()
        self.assertEqual(machine.calls, count)
        self.assertEqual(machine.completed_probe_addresses, [probe['address'] for probe in batch['probes']])
        for index, (args, expected, probe, returned) in enumerate(zip(
                machine.asserted_calls, requests, batch['probes'], results)):
            with self.subTest(index=index):
                for key in ('manager', 'type_code', 'model_hash', 'path_descriptor', 'variant'):
                    self.assertEqual(args[key], expected[key])
                self.assertEqual(args['secondary_type'], expected.get('secondary_type_code', 0))
                self.assertEqual(args['secondary_hash'], expected.get('secondary_model_hash', 0))
                self.assertEqual(args['secondary_variant'], 0)
                self.assertEqual(args['flags'], 0)
                self.assertEqual(args['floats'], [struct.unpack('<f', struct.pack('<f', expected[key]))[0]
                                                 for key in ('progression', 'speed', 'spacing')])
                self.assertEqual(args['probe_address'], probe['address'])
                self.assertEqual(args['state_during_call'], 1)
                self.assertEqual(args['stack_pointer'], machine.sp - 0x80)
                self.assertEqual(args['stack_alignment'], 0)
                self.assertEqual(machine.integer(probe['address'], 4), 2)
                self.assertEqual(machine.completions[index],
                                 (returned, 0x551C30 + index * 0x50 if returned else 0))
        self.assertEqual(machine.gpr[29], machine.sp)
        self.assertEqual(machine.gpr[2], machine.saved_v0)
        self.assertEqual(machine.gpr[3], machine.saved_v1)
        self.assertEqual(machine.gpr[30], machine.saved_s8)
        self.assertEqual(machine.gpr[31], machine.return_ra)
        self.assertEqual(machine.fpr[22], 0x41424344)
        for reg in (0, 1, 12, 13, 14):
            self.assertEqual(machine.fpr[reg], machine.saved_fpr[reg])
        immutable = bytearray(machine.load(CAVE, END - CAVE))
        for probe in batch['probes']:
            immutable[probe['offset']:probe['offset'] + PROBE_SIZE] = bytes(PROBE_SIZE)
        completion_offset = batch['completion_address'] - CAVE
        immutable[completion_offset:completion_offset + 4] = bytes(4)
        self.assertEqual(bytes(immutable), batch['scratch_bytes'])
        self.assertEqual(machine.integer(DATA, 4), batch['completion_token'])
        self.assertEqual(machine.load(HOOK, 8), ORIGINAL)
        self.assertEqual(machine.master_publications, [{'pc': LANDING, 'state': batch['completion_token'], 'hook': ORIGINAL}])
        machine.run()
        self.assertEqual(machine.calls, count)
        self.assertEqual(len(machine.completions), count)

    def test_batch_continues_after_middle_failure_without_retrying(self):
        self.check_batch_execution(3, [0x53AE10, 0, 0x53B110])

    def test_full_batch_preserves_stack_registers_and_each_request_abi(self):
        self.check_batch_execution(8, [0, 0x53AF90, 0, 0x53B290,
                                       0, 0x53B590, 0, 0x53B890])

    def test_batch_skips_done_and_executing_records_independently(self):
        batch = build_batch(self.batch_requests(3), PARAMS['nonce'])
        machine = RoutineMachine([0x53AE10], request=batch)
        first, second, third = (probe['address'] for probe in batch['probes'])
        machine.store_int(first, 2, 4)
        machine.store_int(first + 4, 0x53A210, 4)
        machine.store_int(first + 8, 0x551A50, 4)
        machine.store_int(second, 1, 4)
        machine.run()
        self.assertEqual(machine.calls, 1)
        self.assertEqual(machine.asserted_args['probe_address'], third)
        self.assertEqual(machine.completed_probe_addresses, [third])
        self.assertEqual(machine.integer(first + 4, 4), 0x53A210)
        self.assertEqual(machine.integer(first + 8, 4), 0x551A50)
        self.assertEqual(machine.integer(second, 4), 1)
        self.assertEqual(machine.integer(second + 4, 4), 0)
        self.assertEqual(machine.integer(DATA, 4), batch['completion_token'])  # Token does not replace record checks.
        machine.run()
        self.assertEqual(machine.calls, 1)

    def test_batch_clean_baseline_contains_only_the_fixed_landing(self):
        self.assertEqual(LANDING, CAVE + 0xFC0)
        self.assertEqual(LANDING_SIZE, 12)
        baseline = clean_batch_scratch()
        expected = bytearray(4096)
        expected[0xFC0:0xFCC] = bytes.fromhex('000038af5d9b050800000000')
        self.assertEqual(baseline, bytes(expected))
        batch = build_batch(self.batch_requests(3), PARAMS['nonce'])
        self.assertEqual(batch['clean_scratch'], baseline)
        self.assertEqual(batch['scratch_bytes'][0xFC0:0xFCC], baseline[0xFC0:0xFCC])
        self.assertEqual(build_spawn(**PARAMS)['scratch_bytes'][0xFC0:0xFCC], bytes(12))
        landing_rows = [row for row in batch['rows'] if LANDING <= row['address'] < LANDING + 12]
        self.assertEqual([row['address'] for row in landing_rows], [LANDING, LANDING + 4, LANDING + 8])
        self.assertEqual(b''.join(struct.pack('<I', row['word']) for row in landing_rows), baseline[0xFC0:0xFCC])

    def test_completion_tokens_are_nonce_bound_and_do_not_reuse_the_predecessor(self):
        requests = self.batch_requests(1)
        token = completion_token(PARAMS['nonce'])
        self.assertNotIn(token, (0, 1, 2))
        self.assertEqual(completion_token(PARAMS['nonce']), token)
        other = completion_token(bytes(range(16)))
        self.assertNotEqual(other, token)
        with self.assertRaises(ValueError):
            build_batch(requests, PARAMS['nonce'], previous_completion_token=token)
        self.assertEqual(build_batch(requests, PARAMS['nonce'],
                                     previous_completion_token=other)['completion_token'], token)
        for previous in (True, -1, 1 << 32):
            with self.subTest(previous=previous), self.assertRaises(ValueError):
                build_batch(requests, PARAMS['nonce'], previous_completion_token=previous)
        digests = [Mock(digest=Mock(return_value=n.to_bytes(4, 'little') + bytes(28)))
                   for n in (0, 2, 0x89ABCDEF)]
        with patch('spawncode.hashlib.sha256', side_effect=digests):
            self.assertEqual(completion_token(PARAMS['nonce']), 0x89ABCDEF)

    def test_old_landing_publication_cannot_retire_the_next_generation(self):
        old_token = completion_token(bytes(range(16)))
        batch = build_batch(self.batch_requests(1), PARAMS['nonce'],
                            previous_completion_token=old_token)
        machine = RoutineMachine([0x53AE10], request=batch)
        # Model resuming the previous generation at the permanent SW after a
        # new payload was installed. Its carried T8 publishes an old token.
        machine.gpr[24], machine.gpr[25] = old_token, DATA
        continuation = machine.run(continuation=(LANDING, None), stop_after=LANDING)
        self.assertEqual(machine.integer(DATA, 4), old_token)
        self.assertNotEqual(machine.integer(DATA, 4), batch['completion_token'])
        machine.run(continuation=continuation)
        hook_restore = [row['address'] for row in batch['rows']
                        if row['address'] < LANDING and row['instruction'] == 'sw t8,0(t9)'][-1]
        continuation = machine.run(stop_after=hook_restore)
        self.assertEqual(machine.load(HOOK, 8), ORIGINAL)
        self.assertTrue(all(machine.integer(probe['address'], 4) == 2 for probe in batch['probes']))
        self.assertEqual(machine.integer(DATA, 4), old_token)
        self.assertNotEqual(machine.integer(DATA, 4), batch['completion_token'])
        machine.run(continuation=continuation)
        self.assertEqual(machine.integer(DATA, 4), batch['completion_token'])
        self.assertEqual(machine.calls, 1)

    def test_matcher_reconstructs_v2_parameters_and_frozen_publications(self):
        batch = build_batch(self.batch_requests(3), PARAMS['nonce'])
        machine = RoutineMachine([0x53AE10, 0, 0x53B110], request=batch)
        machine.run()
        scratch = machine.load(CAVE, END - CAVE)
        matched = match_batch_scratch(scratch, PARAMS['nonce'])
        self.assertIsNotNone(matched)
        self.assertEqual(matched['format_version'], 2)
        self.assertEqual(matched['payload']['scratch_bytes'], batch['scratch_bytes'])
        self.assertEqual(matched['payload']['completion_token'], batch['completion_token'])
        self.assertEqual(matched['master_value'], batch['completion_token'])
        self.assertEqual(matched['publications'], [[2, 0x53AE10, 0x551C30],
                                                  [2, 0, 0], [2, 0x53B110, 0x551CD0]])
        for actual, expected in zip(matched['requests'], self.batch_requests(3)):
            for key in ('manager', 'type_code', 'model_hash', 'path_descriptor', 'variant'):
                self.assertEqual(actual[key], expected[key])
            for key in ('progression', 'speed', 'spacing'):
                self.assertEqual(actual[key], struct.unpack('<f', struct.pack('<f', expected[key]))[0])
        # A matching code/nonce template is not retirement: the caller still
        # must compare the master value with this payload's completion token.
        stale = bytearray(scratch)
        struct.pack_into('<I', stale, DATA - CAVE, 0xDEADBEEF)
        matched = match_batch_scratch(bytes(stale), PARAMS['nonce'])
        self.assertIsNotNone(matched)
        self.assertNotEqual(matched['master_value'], matched['payload']['completion_token'])

    def test_matcher_recognizes_frozen_landing_v1_but_not_prelanding_code(self):
        scratch = zlib.decompress(base64.b85decode(V1_FIXTURE_B85))
        self.assertEqual(hashlib.sha256(scratch).hexdigest(),
                         '35ee75156c8bd298adeafdbd8e4a9ef1723c56302ffcc566a67eea956aabd74b')
        matched = match_batch_scratch(scratch, PARAMS['nonce'])
        self.assertIsNotNone(matched)
        self.assertEqual(matched['format_version'], 1)
        self.assertEqual(matched['payload']['completion_token'], 2)
        self.assertEqual(matched['master_value'], 2)
        self.assertEqual(matched['publications'], [[2, 0x53AE10, 0x551C30],
                                                  [2, 0x53AF90, 0x551C80],
                                                  [2, 0x53B110, 0x551CD0]])
        self.assertEqual([r['type_code'] for r in matched['requests']], [2, 4, 1])
        old = bytearray(scratch)
        old[LANDING - CAVE:LANDING - CAVE + LANDING_SIZE] = bytes(LANDING_SIZE)
        last = 2 * BATCH_CODE_STRIDE
        struct.pack_into('<2I', old, last + 0xC4, 0x08000000 | (RETURN >> 2), 0)
        old[last + 0xCC:last + 0xF8] = bytes(0xF8 - 0xCC)
        self.assertIsNone(match_batch_scratch(bytes(old), PARAMS['nonce']))

    def test_matcher_rejects_unknown_code_nonce_layout_and_invalid_publications(self):
        batch = build_batch(self.batch_requests(3), PARAMS['nonce'])
        scratch = batch['scratch_bytes']
        addresses = [0x10, LANDING - CAVE, NONCE_ADDRESS - CAVE, DATA - CAVE + 4,
                     DATA - CAVE + 0x0C]
        for index in range(3):
            record = BATCH_RECORD_BASE - CAVE + index * BATCH_RECORD_STRIDE
            addresses += [record + 0x14, record + 0x20, record + 0x68]
        for offset in addresses:
            with self.subTest(offset=hex(offset)):
                altered = bytearray(scratch)
                altered[offset] ^= 1
                self.assertIsNone(match_batch_scratch(bytes(altered), PARAMS['nonce']))
        record = batch['probes'][0]['offset']
        for publication in ((3, 0, 0), (0, 0x53AE10, 0), (2, 0, 0x551C30),
                            (2, 0x53AE11, 0x551C30), (2, 0x53AE10, 0),
                            (2, 0x53AE10, 0x551C31), (2, 0x100, 0x200)):
            with self.subTest(publication=publication):
                altered = bytearray(scratch)
                struct.pack_into('<3I', altered, record, *publication)
                self.assertIsNone(match_batch_scratch(bytes(altered), PARAMS['nonce']))
        altered = bytearray(scratch)
        struct.pack_into('<3I', altered, record, 1, 0x53AE10, 0)
        self.assertIsNotNone(match_batch_scratch(bytes(altered), PARAMS['nonce']))
        self.assertIsNone(match_batch_scratch(scratch, bytes(range(16))))
        self.assertIsNone(match_batch_scratch(scratch[:-1], PARAMS['nonce']))
        self.assertIsNone(match_batch_scratch(build_spawn(**PARAMS)['scratch_bytes'], PARAMS['nonce']))

    def test_batch_publishes_outside_removable_code_and_resumes_after_cleanup(self):
        for count in (1, 3, 8):
            with self.subTest(count=count):
                batch = build_batch(self.batch_requests(count), PARAMS['nonce'])
                machine = RoutineMachine([0x53AE10 + index * 0x180 for index in range(count)], request=batch)
                last_start = CAVE + (count - 1) * BATCH_CODE_STRIDE
                guard = next(row for row in batch['rows']
                             if last_start <= row['address'] < last_start + BATCH_CODE_STRIDE
                             and row['instruction'] == 'bne t8,zero,restore')
                # Every actor can be DONE while the last stub still needs its
                # original frame and return path. Global DONE must remain zero.
                continuation = machine.run(stop_after=guard['branch_target'] - 4)
                self.assertEqual(machine.calls, count)
                self.assertTrue(all(machine.integer(p['address'], 4) == 2 for p in batch['probes']))
                self.assertEqual(machine.integer(DATA, 4), 0)
                self.assertEqual(machine.load(HOOK, 8), batch['hook_bytes'])
                self.assertFalse(machine.returned)
                continuation = machine.run(continuation=continuation, stop_after=LANDING)
                self.assertEqual(continuation, (LANDING + 4, None))
                self.assertEqual(machine.master_publications, [{'pc': LANDING, 'state': batch['completion_token'], 'hook': ORIGINAL}])
                hook_events = [(address, value) for _pc, address, value in machine.events
                               if address in (HOOK, HOOK + 4)]
                self.assertEqual(hook_events, [(HOOK + 4, 0x7BBE0090), (HOOK, 0xC7B60008)])
                self.assertEqual(machine.gpr[29], machine.sp)
                self.assertEqual(machine.gpr[31], machine.return_ra)
                self.assertFalse(machine.returned)
                # Model the host pausing just after the publication SW and
                # removing every temporary code/data byte. Landing J+NOP stay.
                machine.store(CAVE, batch['clean_scratch'])
                machine.run(continuation=continuation)
                self.assertTrue(machine.returned)
                self.assertEqual(machine.calls, count)
                self.assertEqual(machine.load(CAVE, 4096), batch['clean_scratch'])
                self.assertEqual(machine.load(HOOK, 8), ORIGINAL)
                self.assertEqual(machine.gpr[2], machine.saved_v0)
                self.assertEqual(machine.gpr[3], machine.saved_v1)
                self.assertEqual(machine.gpr[30], machine.saved_s8)
                self.assertEqual(machine.fpr[22], 0x41424344)
                for register in (0, 1, 12, 13, 14):
                    self.assertEqual(machine.fpr[register], machine.saved_fpr[register])

    def test_invalid_batches_rejected(self):
        valid = self.batch_requests(1)
        for requests in ([], valid * 9, None, {}, [True], [{}], [{**valid[0], 'nonce': PARAMS['nonce']}],
                         [{**valid[0], 'unexpected': 1}], [{**valid[0], 'type_code': 4}]):
            with self.subTest(requests=requests):
                with self.assertRaises(ValueError):
                    build_batch(requests, PARAMS['nonce'])
        for nonce in (b'short', bytearray(16), True):
            with self.subTest(nonce=nonce):
                with self.assertRaises(ValueError):
                    build_batch(valid, nonce)


if __name__ == '__main__':
    unittest.main()
