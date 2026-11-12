"""Read-only, bounded inspection of a candidate Burnout 3 USA traffic pool.

This profile is inferred from SLUS_210.50 SHA-256
e118dba952bf9fde6a04ee284bb1f06fa0bb49c9e04bbe762af1039dcc443c66
and corroborated against selected existing PCSX2 save states. It does not
establish the current game mode, event, visibility, or runtime call behavior.
No ZIP members are extracted and no source file is written.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import add_paths, resolve_paths
RAM_SIZE = 32 * 1024 * 1024
MANAGER = 0x527440
VEHICLES = 0x539C10
VEHICLE_STRIDE = 0x180
NODES = 0x551910
NODE_STRIDE = 0x50
MATRICES = 0x556870
MATRIX_STRIDE = 0x50
POOL_COUNT = (NODES - VEHICLES) // VEHICLE_STRIDE
ORIGINAL_WORDS = {
    0x164D84: 0x46800860,
    0x164D88: 0x46800020,
    0x161FAC: 0x11C002CF,
    0x15BB80: 0x0C0F3244,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Memory:
    def __init__(self, data: bytes):
        if len(data) != RAM_SIZE:
            raise ValueError(f"Expected {RAM_SIZE} EE RAM bytes, got {len(data)}")
        self.data = data

    def read(self, address: int, format_: str):
        size = struct.calcsize(format_)
        if address < 0 or address + size > len(self.data):
            raise ValueError(f"RAM read outside bounds: {address:#x}+{size:#x}")
        return struct.unpack_from(format_, self.data, address)

    def u8(self, address: int) -> int:
        return self.read(address, "<B")[0]

    def u32(self, address: int) -> int:
        return self.read(address, "<I")[0]

    def xyz(self, address: int) -> list[float]:
        return list(self.read(address, "<3f"))


def index_for_pointer(pointer: int, base: int, stride: int) -> int | None:
    """Admit exact low-RAM coordinates only; do not silently mask bad pointers."""
    relative = pointer - base
    if 0 <= relative < POOL_COUNT * stride and relative % stride == 0:
        return relative // stride
    return None


def walk_free_list(memory: Memory, head: int, *, node: bool):
    base, stride = (NODES, NODE_STRIDE) if node else (VEHICLES, VEHICLE_STRIDE)
    found = []
    problems = []
    pointer = head
    while pointer:
        index = index_for_pointer(pointer, base, stride)
        if index is None:
            problems.append({"pointer": hex(pointer), "error": "outside_or_unaligned"})
            break
        if index in found:
            problems.append({"index": index, "error": "cycle"})
            break
        found.append(index)
        if node:
            next_index = memory.u8(pointer + 0x44)
            if next_index == 0xFF:
                pointer = 0
            elif next_index >= POOL_COUNT:
                problems.append({"index": index, "invalid_next_index": next_index})
                break
            else:
                pointer = NODES + next_index * NODE_STRIDE
        else:
            pointer = memory.u32(pointer + 0x108)
    return found, problems


def finite_or_none(values):
    return [value if math.isfinite(value) else None for value in values]


def inspect_memory(memory: Memory, max_examples: int):
    vehicle_bitmap = [memory.u32(MANAGER + 0x362E0 + i * 4) for i in range(8)]
    node_bitmap = [memory.u32(MANAGER + 0x36300 + i * 4) for i in range(8)]

    def bitmap_indices(words):
        return {i for i in range(POOL_COUNT) if words[i // 32] >> (i % 32) & 1}

    active = bitmap_indices(vehicle_bitmap)
    active_nodes = bitmap_indices(node_bitmap)
    flags_active = {i for i in range(POOL_COUNT)
                    if memory.u8(VEHICLES + i * VEHICLE_STRIDE + 0x174) & 1}
    flags_nodes = {i for i in range(POOL_COUNT)
                   if memory.u8(NODES + i * NODE_STRIDE + 0x4B) & 8}
    bad_vehicle_indices = [i for i in range(POOL_COUNT)
                           if memory.u8(VEHICLES + i * VEHICLE_STRIDE + 0x177) != i]
    bad_node_indices = [i for i in range(POOL_COUNT)
                        if memory.u8(NODES + i * NODE_STRIDE + 0x49) != i]
    free_head = memory.u32(MANAGER + 0x36364)
    node_head = memory.u32(MANAGER + 0x3636C)
    free, free_errors = walk_free_list(memory, free_head, node=False)
    node_free, node_errors = walk_free_list(memory, node_head, node=True)

    link_errors = []
    association_errors = []
    nonfinite = []
    no_node_types = Counter()
    examples = []
    for i in sorted(active):
        address = VEHICLES + i * VEHICLE_STRIDE
        type_ = memory.u8(address + 0x173)
        parent = memory.u32(address + 0x10C)
        child = memory.u32(address + 0x110)
        node_pointer = memory.u32(address + 0x114)
        for relation, pointer, reciprocal in [("parent", parent, 0x110),
                                                ("child", child, 0x10C)]:
            if not pointer:
                continue
            linked = index_for_pointer(pointer, VEHICLES, VEHICLE_STRIDE)
            if linked is None or linked not in active:
                link_errors.append({"vehicle": i, "relation": relation,
                                    "pointer": hex(pointer), "error": "not_active_pool_object"})
            elif memory.u32(pointer + reciprocal) != address:
                link_errors.append({"vehicle": i, "relation": relation,
                                    "pointer": hex(pointer), "error": "nonreciprocal"})
        ni = index_for_pointer(node_pointer, NODES, NODE_STRIDE)
        if not node_pointer:
            no_node_types[type_] += 1
        elif ni is None or ni not in active_nodes:
            association_errors.append({"vehicle": i, "node_pointer": hex(node_pointer),
                                       "error": "not_active_node"})
        elif memory.u8(node_pointer + 0x4A) != i:
            association_errors.append({"vehicle": i, "node": ni, "error": "wrong_backlink"})
        object_xyz = memory.xyz(address + 0xA0)
        matrix_xyz = memory.xyz(MATRICES + ni * MATRIX_STRIDE + 0x30) if ni is not None else None
        if not all(math.isfinite(value) for value in object_xyz + (matrix_xyz or [])):
            nonfinite.append(i)
        if len(examples) < max_examples:
            examples.append({"vehicle_index": i, "vehicle_address": hex(address),
                             "type_byte_0x173": type_,
                             "flags_byte_0x174": memory.u8(address + 0x174),
                             "model_pointer_0xb0": hex(memory.u32(address + 0xB0)),
                             "parent_pointer_0x10c": hex(parent),
                             "child_pointer_0x110": hex(child),
                             "node_pointer_0x114": hex(node_pointer), "node_index": ni,
                             "object_xyz_0xa0": finite_or_none(object_xyz),
                             "node_matrix_xyz_0x30": finite_or_none(matrix_xyz) if matrix_xyz else None})

    counter = memory.u8(MANAGER + 0x363AC)
    bitmap_high_bits = bool(vehicle_bitmap[-1] & 0xC0000000 or node_bitmap[-1] & 0xC0000000)
    checks = {
        "all_254_vehicle_self_indices_match": not bad_vehicle_indices,
        "all_254_node_self_indices_match": not bad_node_indices,
        "vehicle_free_list_valid": not free_errors,
        "node_free_list_valid": not node_errors,
        "vehicle_free_active_partition_complete": set(free).isdisjoint(active)
            and set(free) | active == set(range(POOL_COUNT)),
        "node_free_active_partition_complete": set(node_free).isdisjoint(active_nodes)
            and set(node_free) | active_nodes == set(range(POOL_COUNT)),
        "vehicle_flags_match_bitmap": flags_active == active,
        "node_flags_match_bitmap": flags_nodes == active_nodes,
        "vehicle_counter_matches_bitmap": counter == len(active),
        "unused_bitmap_bits_clear": not bitmap_high_bits,
        "nonnull_node_associations_valid": not association_errors,
        "parent_child_links_valid": not link_errors,
        "active_xyz_fields_finite": not nonfinite,
    }
    return {
        "candidate_profile": {"name": "SLUS_210.50 USA inferred traffic pool",
                              "manager_address": hex(MANAGER), "vehicle_base": hex(VEHICLES),
                              "vehicle_stride": VEHICLE_STRIDE, "node_base": hex(NODES),
                              "node_stride": NODE_STRIDE, "matrix_base": hex(MATRICES),
                              "matrix_stride": MATRIX_STRIDE, "candidate_pool_count": POOL_COUNT},
        "counts": {"capacity_budget_byte_0x363ab": memory.u8(MANAGER + 0x363AB),
                   "active_counter_byte_0x363ac": counter, "active_objects": len(active),
                   "free_objects": len(free), "active_nodes": len(active_nodes),
                   "free_nodes": len(node_free), "null_node_pointer_types": dict(no_node_types)},
        "free_lists": {"vehicle_head": hex(free_head),
                       "vehicle_tail_field": hex(memory.u32(MANAGER + 0x36368)),
                       "vehicle_first_indices": free[:3], "vehicle_last_index": free[-1] if free else None,
                       "node_head": hex(node_head), "node_first_indices": node_free[:3]},
        "validation": checks, "candidate_structure_consistent": all(checks.values()),
        "diagnostics": {"bad_vehicle_self_indices": bad_vehicle_indices,
                        "bad_node_self_indices": bad_node_indices,
                        "vehicle_free_errors": free_errors, "node_free_errors": node_errors,
                        "node_association_errors": association_errors,
                        "parent_child_errors": link_errors, "nonfinite_position_indices": nonfinite},
        "original_code_word_matches": {hex(a): memory.u32(a) == word for a, word in ORIGINAL_WORDS.items()},
        "code_words": {hex(a): hex(memory.u32(a)) for a in ORIGINAL_WORDS},
        "examples": examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_paths(parser)
    parser.add_argument("savestate", type=Path)
    parser.add_argument("--output", default=Path("traffic_pool.json"), type=Path,
                        help="New JSON filename/path confined to --output-root")
    parser.add_argument("--max-examples", type=int, default=8, choices=range(0, 17), metavar="0..16")
    args = parser.parse_args()
    _, output_root = resolve_paths(parser, args, require_game=False)
    source = args.savestate.resolve(strict=True)
    output = (output_root / args.output).resolve()
    if not output.is_relative_to(output_root) or output == source:
        parser.error("Output must be a different file confined to --output-root")
    if output.exists():
        parser.error("Refusing to overwrite an existing report; choose a new output path")
    stat_before = source.stat()
    hash_before = sha256_file(source)
    with zipfile.ZipFile(source) as archive:
        matches = [i for i in archive.infolist() if i.filename == "eeMemory.bin"]
        if len(matches) != 1 or matches[0].file_size != RAM_SIZE:
            raise ValueError("Expected exactly one 32 MiB eeMemory.bin entry")
        result = inspect_memory(Memory(archive.read(matches[0])), args.max_examples)
    hash_after = sha256_file(source)
    stat_after = source.stat()
    stable = (hash_before == hash_after and stat_before.st_size == stat_after.st_size
              and stat_before.st_mtime_ns == stat_after.st_mtime_ns)
    result["source"] = {"path": str(source), "bytes": stat_before.st_size,
                        "sha256_before": hash_before, "sha256_after": hash_after,
                        "stable_during_read": stable}
    result["limitations"] = [
        "Offline observation of a historical save state, not execution of the game.",
        "Addresses and structures are a specific inferred USA executable profile, not a general PCSX2 parser.",
        "Vehicle objects can represent linked components; active object count is not necessarily road vehicle count.",
        "Some active objects may legitimately have a null node pointer; observed type 11 uses parent links.",
        "XYZ field interpretation is inferred from code and values; visibility and current Crash event are unknown.",
        "Matching four original code words does not prove the entire save is unmodified.",
        "Invalid or unstable sources are reported as unverified; no save, PNACH or BIOS is written.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as report:
        json.dump(result, report, indent=2, allow_nan=False)
        report.write("\n")
    print(json.dumps({"output": str(output), "stable": stable,
                      "candidate_structure_consistent": result["candidate_structure_consistent"],
                      "counts": result["counts"]}))
    return 0 if stable and result["candidate_structure_consistent"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Inspection failed: {error}", file=sys.stderr)
        raise SystemExit(1)
