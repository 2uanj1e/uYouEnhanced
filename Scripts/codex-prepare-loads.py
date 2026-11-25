#!/usr/bin/env python3
"""Normalize only two unused, trailing weak dylib loads in the pinned input.

The input already declares YouMute, although its prebuilt package omitted that
file. The build supplies a freshly compiled YouMute. No new load-command space
is required. All code/data offsets and bytes beyond the original command region
are preserved; the caller later re-signs its copied bundle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

EXPECTED_MAIN_SHA256 = 'c8cfdf6aa8f6a6284b88f51699f66eaee8d014d38cb4abc702700739fac94815'
REMOVE = ['@rpath/iSponsorBlock.dylib', '@rpath/YTUHD.dylib']
LOAD_KINDS = {0xC, 0x80000018, 0x8000001F, 0x20, 0x80000023}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalize(binary, record):
    data = binary.read_bytes()
    assert sha(data) == EXPECTED_MAIN_SHA256, 'Not the audited 21.20.4 main executable'
    magic, cpu, subtype, filetype, ncmds, size, flags, reserved = struct.unpack_from('<8I', data)
    assert magic == 0xFEEDFACF and cpu == 0x0100000C and filetype == 2
    end = 32 + size
    commands, loads, fixups, cryptids, section_offsets = [], [], [], [], []
    cursor = 32
    for index in range(ncmds):
        kind, length = struct.unpack_from('<II', data, cursor)
        assert length >= 8 and length % 8 == 0 and cursor + length <= end
        raw = data[cursor:cursor + length]
        item = {'index': index, 'offset': cursor, 'kind': kind, 'raw': raw, 'name': None}
        if kind in LOAD_KINDS:
            name_offset = struct.unpack_from('<I', raw, 8)[0]
            assert 24 <= name_offset < length
            item['name'] = raw[name_offset:].split(b'\0', 1)[0].decode('utf-8')
            loads.append(item)
        if kind == 0x80000034:
            fixups.append(struct.unpack_from('<II', raw, 8))
        if kind in (0x22, 0x80000022):
            raise AssertionError('Unaudited classic dyld bind tables; no modification made')
        if kind == 0x2C:
            cryptids.append(struct.unpack_from('<I', raw, 16)[0])
        if kind == 0x19:
            count = struct.unpack_from('<I', raw, 64)[0]
            for i in range(count):
                start = 72 + i * 80
                offset = struct.unpack_from('<I', raw, start + 48)[0]
                if offset:
                    section_offsets.append(offset)
        commands.append(item)
        cursor += length
    assert cursor == end and cryptids and set(cryptids) == {0}
    assert min(section_offsets) >= end
    assert [x['name'] for x in loads[-2:]] == REMOVE
    assert all(x['kind'] == 0x80000018 for x in loads[-2:])
    assert len(fixups) == 1

    # No imports may bind to either removed library ordinal. Since these are
    # the last two dylib loads, every retained library ordinal stays unchanged.
    fixoff, fixsize = fixups[0]
    assert fixoff + fixsize <= len(data)
    version, starts, imports, symbols, count, form, symform = struct.unpack_from('<7I', data, fixoff)
    assert version == 0 and form in (1, 2, 3)
    stride = {1: 4, 2: 8, 3: 16}[form]
    assert imports + stride * count <= fixsize
    ordinals = []
    for i in range(count):
        off = fixoff + imports + stride * i
        bits = struct.unpack_from('<Q' if form == 3 else '<I', data, off)[0]
        width = 16 if form == 3 else 8
        ordinal = bits & ((1 << width) - 1)
        if ordinal >= (1 << (width - 1)):
            ordinal -= 1 << width
        ordinals.append(ordinal)
    assert all(o <= len(loads) - 2 for o in ordinals if o > 0), 'Removed load has imports'
    removed = [x for x in commands if x['name'] in REMOVE]
    assert len(removed) == 2
    kept = [x for x in commands if x['name'] not in REMOVE]
    packed = b''.join(x['raw'] for x in kept)
    changed = bytearray(data)
    struct.pack_into('<II', changed, 16, len(kept), len(packed))
    changed[32:end] = packed + bytes(size - len(packed))
    assert len(changed) == len(data) and changed[end:] == data[end:]
    assert changed[:16] == data[:16] and changed[24:32] == data[24:32]
    result = {
        'before_sha256': sha(data), 'after_sha256': sha(changed),
        'before_ncmds': ncmds, 'after_ncmds': len(kept),
        'before_sizeofcmds': size, 'after_sizeofcmds': len(packed),
        'removed': [{'name': x['name'], 'original_offset': x['offset'], 'cmdsize': len(x['raw'])} for x in removed],
        'retained_dylib_ordinals_unchanged': True,
        'chained_imports_count': count, 'chained_imports_format': form,
        'highest_positive_import_ordinal': max((o for o in ordinals if o > 0), default=0),
        'first_removed_library_ordinal': len(loads) - 1,
        'bytes_after_original_command_region_sha256': sha(data[end:]),
        'bytes_after_original_command_region_unchanged': True,
        'first_section_offset': min(section_offsets), 'file_length_unchanged': True,
        'retained_dependencies': [x['name'] for x in loads[:-2]],
        'signature_note': 'Load-command edit invalidates old signature; caller must re-sign copied bundle.'
    }
    binary.write_bytes(changed)
    assert sha(binary.read_bytes()) == result['after_sha256']
    record.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: removed only trailing optional weak loads; retained imports, code/data and offsets unchanged')
    print('before_sha256=' + result['before_sha256'])
    print('after_sha256=' + result['after_sha256'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--record', type=Path, required=True)
    a = p.parse_args()
    normalize(a.binary, a.record)
