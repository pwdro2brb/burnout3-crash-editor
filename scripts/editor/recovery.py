"""Explicit cleanup of a retired, journal-owned batch restored from a state.

No traffic profile, object identity or actor write is needed. Ownership and
code lifetime are established separately from a successful vehicle creation.
"""
from __future__ import annotations

import json
from pathlib import Path
import struct

from . import spawncode
from .catalog import encode_identifier
from .controller import EditorError
from .pine import Status


MAX_JOURNAL_BYTES = 32*1024*1024


def journal_rows(directory):
    if directory is None:
        return []
    path = Path(directory)/'editor-actions.jsonl'
    try:
        if path.stat().st_size > MAX_JOURNAL_BYTES:
            raise EditorError('The local log exceeded the recovery limit of this version.')
        rows = []
        with path.open(encoding='utf8') as stream:
            for line in stream:
                if len(line) > 16384:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row,dict):
                    rows.append(row)
        return rows
    except FileNotFoundError:
        return []
    except (OSError,UnicodeError) as error:
        raise EditorError('Could not check the local log of this request.') from error


def known_completion_tokens(directory):
    return {row['completion_token'] for row in journal_rows(directory)
            if row.get('event') == 'batch_staged'
            and type(row.get('completion_token')) is int
            and 0 < row['completion_token'] <= 0xFFFFFFFF}


def _matches_record(row,nonce,requests):
    if (row.get('event') != 'batch_staged' or row.get('nonce') != nonce
            or type(row.get('count')) is not int or row['count'] != len(requests)
            or type(row.get('path')) is not int or row['path'] < 0
            or spawncode.PATHS+row['path']*spawncode.PATH_STRIDE >= spawncode.MANAGER):
        return False
    progressions = row.get('progressions')
    if not isinstance(progressions,list) or len(progressions) != len(requests):
        return False
    try:
        items = row.get('items')
        if 'items' not in row:
            # Older journals describe a homogeneous batch and did not record
            # appearance. They may authorize only the original variant zero.
            items = [dict(model_id=row['model_id'],secondary_model_id=row.get('secondary_model_id'),
                          variant=0) for _ in requests]
            legacy = True
        else:
            if (not isinstance(items,list) or len(items) != len(requests)
                    or any(not isinstance(item,dict) for item in items)):
                return False
            legacy = False
            if (items[0].get('model_id') != row.get('model_id')
                    or items[0].get('secondary_model_id') != row.get('secondary_model_id')):
                return False
        for request,progression,item in zip(requests,progressions,items):
            primary = encode_identifier(item['model_id'])
            secondary_id = item.get('secondary_model_id')
            secondary = encode_identifier(secondary_id) if secondary_id is not None else 0
            variant = item.get('variant')
            if type(variant) is not int or not 0 <= variant <= 7:
                return False
            type_code = item.get('type_code',request['type_code']) if legacy else item.get('type_code')
            secondary_type = 11 if secondary_id is not None else 0
            if (type(type_code) is not int or type_code not in (1,2,3,4,5)
                    or (type_code == 4) != bool(secondary_type)
                    or type(item.get('secondary_type_code',secondary_type)) is not int
                    or item.get('secondary_type_code',secondary_type) != secondary_type):
                return False
            if (type(progression) not in (int,float)
                    or struct.pack('<f',progression) != struct.pack('<f',request['progression'])
                    or request['manager'] != spawncode.MANAGER
                    or request['model_hash'] != primary
                    or request['secondary_model_hash'] != secondary
                    or request['type_code'] != type_code
                    or request['secondary_type_code'] != secondary_type
                    or request['variant'] != variant
                    or request['path_descriptor'] != spawncode.PATHS+row['path']*spawncode.PATH_STRIDE):
                return False
    except (KeyError,TypeError,ValueError,OverflowError,struct.error):
        return False
    return True


def finalize_restored(editor):
    """Clean exact completed batch code without aligning or recording actors."""
    editor._paused()
    hook = editor.client.read_bytes(spawncode.HOOK,8)
    raw = editor.client.read_bytes(spawncode.CAVE,4096)
    clean = spawncode.clean_batch_scratch()
    if hook == spawncode.ORIGINAL and raw in (bytes(4096),clean):
        return {'pending':False,'core_paused':True,
                'message':'There is no pending temporary request.'}
    if hook != spawncode.ORIGINAL:
        raise EditorError('The routine has not returned control to the game yet. Resume and pause to finish; '
                          'if it came from another state, reload a clean reference.')
    nonce = raw[spawncode.NONCE_ADDRESS-spawncode.CAVE:spawncode.NONCE_ADDRESS-spawncode.CAVE+16]
    try:
        matched = spawncode.match_batch_scratch(raw,nonce)
    except ValueError as error:
        raise EditorError('The temporary memory does not match a recognized batch. '
                          'No code was removed; reload a clean reference.') from error
    if matched is None:
        raise EditorError('The temporary memory does not match a recognized batch. '
                          'No code was removed; reload a clean reference.')
    requests,payload = matched['requests'],matched['payload']
    if not any(_matches_record(row,nonce.hex(),requests) for row in journal_rows(editor.journal_dir)):
        raise EditorError("The batch does not match this editor's local log. "
                          'No code was removed; reload a clean reference.')
    master = struct.unpack_from('<I',raw,payload['completion_address']-spawncode.CAVE)[0]
    publications = [struct.unpack_from('<3I',raw,p['offset']) for p in payload['probes']]
    if master != payload['completion_token'] or any(p[0] != 2 for p in publications):
        raise EditorError('The old request has not finished yet. Resume and pause; '
                          'if the reference is not recognized, reload a clean state.')
    editor._identity()
    if (editor.client.status() is not Status.PAUSED
            or editor.client.read_bytes(spawncode.HOOK,8) != hook
            or editor.client.read_bytes(spawncode.CAVE,4096) != raw):
        raise EditorError('The state changed during the check. No cleanup was applied.')
    try:
        # The permanent landing remains executable if a saved PC is still there.
        editor.client.write_bytes(spawncode.CAVE,payload['clean_scratch'])
        if (editor.client.read_bytes(spawncode.CAVE,4096) != payload['clean_scratch']
                or editor.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                or editor.client.status() is not Status.PAUSED):
            raise EditorError('The finish could not be confirmed.')
    except Exception as error:
        editor.unsafe = True
        editor._journal('batch_recovery_unconfirmed',nonce=nonce.hex())
        raise EditorError('The finish could not be confirmed. Reload a clean reference.') from error
    editor.pending = None
    editor.replay_queue.clear()
    editor.completion_tokens.add(payload['completion_token'])
    editor._journal('batch_recovered_cancelled',nonce=nonce.hex(),format_version=matched['format_version'])
    return {'pending':False,'core_paused':True,'warning':True,
            'message':'Old request finished. The vehicles were kept; '
                      'the alignment and recipe of that request were not recovered.'}
