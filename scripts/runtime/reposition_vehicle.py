"""Write a NEW test savestate with one independent traffic vehicle translated.

Experimental SLUS_210.50 USA profile only. This is an offline savestate tool,
not an in-game editor or an event/resource patcher. Input is never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import zipfile
import zlib

from inspect_savestate import Memory, inspect_memory, index_for_pointer, RAM_SIZE, VEHICLES, VEHICLE_STRIDE, NODES, NODE_STRIDE, POOL_COUNT
from savestate_zip import MAX_ARCHIVE_BYTES, read_member, replace_member


PROFILE_ELF_SHA256 = "e118dba952bf9fde6a04ee284bb1f06fa0bb49c9e04bbe762af1039dcc443c66"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new_path(path: Path) -> Path:
    if os.path.lexists(path):
        raise ValueError(f"Refusing to overwrite an existing path: {path}")
    resolved = path.resolve()
    if not resolved.parent.is_dir():
        raise ValueError(f"Output parent directory must already exist: {resolved.parent}")
    return resolved


def create_variant(source: Path, output: Path, report_path: Path, expected_sha256: str,
                   vehicle_index: int, dx: float, dz: float, lateral: float | None) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("--source-sha256 must contain exactly 64 hexadecimal characters")
    if not 0 <= vehicle_index < POOL_COUNT:
        raise ValueError(f"--vehicle-index must be in 0..{POOL_COUNT - 1}")
    if not all(math.isfinite(value) for value in (dx, dz)):
        raise ValueError("Displacement must be finite")
    if lateral is not None and (not math.isfinite(lateral) or not 0 <= lateral <= 1):
        raise ValueError("--lateral must be finite and in 0..1")
    source = source.resolve(strict=True)
    if not source.is_file() or source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Input must be a bounded savestate file")
    output, report_path = _new_path(output), _new_path(report_path)
    if source in (output, report_path) or output == report_path:
        raise ValueError("Input, output and report paths must be distinct")
    original = source.read_bytes()
    original_hash = digest(original)
    if original_hash != expected_sha256.lower():
        raise ValueError("Source SHA-256 does not match the explicitly supplied reference")
    ram = read_member(original, "eeMemory.bin")
    if len(ram) != RAM_SIZE:
        raise ValueError("Expected exactly 32 MiB of EE RAM")
    memory = Memory(ram)
    inspection = inspect_memory(memory, 0)
    if not inspection["candidate_structure_consistent"]:
        failed = [name for name, passed in inspection["validation"].items() if not passed]
        raise ValueError(f"Traffic-pool invariants failed: {failed}")
    if not all(inspection["original_code_word_matches"].values()):
        raise ValueError("The four known code hooks must match the stock USA profile")
    address = VEHICLES + vehicle_index * VEHICLE_STRIDE
    parent, child = memory.u32(address + 0x10C), memory.u32(address + 0x110)
    if not memory.u8(address + 0x174) & 1 or parent or child:
        raise ValueError("Selected object must be active and independent, without parent/child links")
    node = memory.u32(address + 0x114)
    node_index = index_for_pointer(node, NODES, NODE_STRIDE)
    if node_index is None or not memory.u8(node + 0x4B) & 8 or memory.u8(node + 0x4A) != vehicle_index:
        raise ValueError("Selected object must have a valid active node and backlink")
    for offset in (0, 0x30, 0xA0):
        if not all(math.isfinite(value) for value in memory.xyz(address + offset)):
            raise ValueError("The two anchor positions and current translation must be finite")
    if math.dist(memory.xyz(address), memory.xyz(address + 0x30)) <= 1e-6:
        raise ValueError("Selected object's physical anchors are degenerate or uninitialized; "
                         "advance until it receives nearby physics updates, then capture a new reference")
    if not all(math.isfinite(value) for value in memory.read(node + 0x30, "<2f")):
        raise ValueError("Node progression and lateral fraction must be finite")

    changed = bytearray(ram)
    fields = []
    permitted = set()

    def set_float(where: int, value: float, label: str) -> None:
        if not math.isfinite(value):
            raise ValueError("Requested coordinate is not finite")
        try:
            packed = struct.pack("<f", value)
        except (OverflowError, struct.error) as error:
            raise ValueError("Requested coordinate is outside float32 range") from error
        rounded = struct.unpack("<f", packed)[0]
        if not math.isfinite(rounded):
            raise ValueError("Requested coordinate rounds to a nonfinite float32")
        old = ram[where:where + 4]
        changed[where:where + 4] = packed
        permitted.update(range(where, where + 4))
        fields.append({"address": hex(where), "field": label, "old_bytes_le": old.hex(),
                       "new_bytes_le": packed.hex(), "old_float": struct.unpack("<f", old)[0],
                       "new_float": rounded, "effective_float_delta": rounded - struct.unpack("<f", old)[0]})

    for offset, label in ((0, "anchor0"), (0x30, "anchor1"), (0xA0, "current_translation")):
        set_float(address + offset, memory.read(address + offset, "<f")[0] + dx, f"{label}.x")
        set_float(address + offset + 8, memory.read(address + offset + 8, "<f")[0] + dz, f"{label}.z")
    if lateral is not None:
        set_float(node + 0x34, lateral, "node.lateral_fraction")
    changed_ram = bytes(changed)
    # Scan all 32 MiB to verify the write boundary, rather than trusting the setters.
    differences = [i for i, (a, b) in enumerate(zip(ram, changed_ram)) if a != b]
    if not set(differences).issubset(permitted) or len(differences) > 4 * len(fields):
        raise AssertionError("RAM differences escaped the selected float fields")
    result, zip_checks = replace_member(original, "eeMemory.bin", changed_ram)
    if read_member(result, "eeMemory.bin") != changed_ram:
        raise AssertionError("In-memory ZIP readback differs")
    if digest(source.read_bytes()) != original_hash:
        raise ValueError("Source changed during preparation; output was not written")
    with output.open("xb") as handle:
        handle.write(result)
    written = output.read_bytes()
    if written != result or read_member(written, "eeMemory.bin") != changed_ram:
        raise AssertionError("Written output failed readback")
    final_source_hash = digest(source.read_bytes())
    if final_source_hash != original_hash:
        raise ValueError("Source changed during final verification")
    report = {
        "profile": {"name": "Experimental SLUS_210.50 USA traffic savestate translation", "reference_elf_sha256": PROFILE_ELF_SHA256,
                    "four_known_hooks_stock": True, "pool_invariants": inspection["validation"]},
        "source": {"path": str(source), "sha256_before": original_hash, "sha256_after": final_source_hash,
                   "bytes": len(original), "unchanged": True},
        "output": {"path": str(output), "sha256": digest(written), "bytes": len(written)},
        "selection": {"vehicle_index": vehicle_index, "object_address": hex(address), "type_byte": memory.u8(address + 0x173),
                      "node_index": node_index, "node_address": hex(node), "path_index_byte": memory.u8(node + 0x41),
                      "independent": True},
        "requested": {"dx": dx, "dz": dz, "lateral": lateral}, "fields": fields,
        "ram_verification": {"size_bytes": len(ram), "allowed_field_count": len(fields),
                             "maximum_allowed_changed_bytes": 4 * len(fields), "changed_byte_count": len(differences),
                             "changed_byte_addresses": [hex(i) for i in differences],
                             "all_other_ram_bytes_identical": True,
                             "y_normals_lists_velocities_cached_target_and_collider_unedited": True},
        "zip_verification": zip_checks,
        "limitations": ["Offline test-copy tool, not an in-game editor or persistent event/resource patcher.",
                        "Four stock hooks and inferred pool invariants do not prove every byte of the source is unmodified.",
                        "Runtime evidence covers one stationary scene and one moving Grand Slam object over short configured frame advances; visual identification of the Grand Slam target, impacts, other models and long-term behavior need separate testing.",
                        "The cached target and collider bounds are left untouched so the game can update them; that update is not guaranteed by file generation."]
    }
    with report_path.open("x", encoding="utf8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--vehicle-index", type=int, required=True)
    parser.add_argument("--dx", type=float, required=True)
    parser.add_argument("--dz", type=float, required=True)
    parser.add_argument("--lateral", type=float)
    args = parser.parse_args()
    try:
        report = create_variant(args.input, args.output, args.report, args.source_sha256,
                                args.vehicle_index, args.dx, args.dz, args.lateral)
    except (ValueError, OSError, KeyError, AssertionError, struct.error, zipfile.BadZipFile, zlib.error) as error:
        parser.exit(2, f"Error: {error}\n")
    print(json.dumps({"output": report["output"], "changed_ram_bytes": report["ram_verification"]["changed_byte_count"],
                      "report": str(args.report.resolve()), "source_unchanged": report["source"]["unchanged"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
