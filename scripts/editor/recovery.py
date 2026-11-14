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
            raise EditorError('O registro local excedeu o limite de recuperação desta versão.')
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
        raise EditorError('Não foi possível conferir o registro local desta solicitação.') from error


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
        primary = encode_identifier(row['model_id'])
        secondary_id = row.get('secondary_model_id')
        secondary = encode_identifier(secondary_id) if secondary_id is not None else 0
        for request,progression in zip(requests,progressions):
            if (type(progression) not in (int,float)
                    or struct.pack('<f',progression) != struct.pack('<f',request['progression'])
                    or request['manager'] != spawncode.MANAGER
                    or request['model_hash'] != primary
                    or request['secondary_model_hash'] != secondary
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
                'message':'Não há solicitação temporária pendente.'}
    if hook != spawncode.ORIGINAL:
        raise EditorError('A rotina ainda não devolveu o controle ao jogo. Retome e pause para concluir; '
                          'se veio de outro estado, recarregue uma referência limpa.')
    nonce = raw[spawncode.NONCE_ADDRESS-spawncode.CAVE:spawncode.NONCE_ADDRESS-spawncode.CAVE+16]
    try:
        matched = spawncode.match_batch_scratch(raw,nonce)
    except ValueError as error:
        raise EditorError('A memória temporária não corresponde a um lote reconhecido. '
                          'Nenhum código foi removido; recarregue uma referência limpa.') from error
    if matched is None:
        raise EditorError('A memória temporária não corresponde a um lote reconhecido. '
                          'Nenhum código foi removido; recarregue uma referência limpa.')
    requests,payload = matched['requests'],matched['payload']
    if not any(_matches_record(row,nonce.hex(),requests) for row in journal_rows(editor.journal_dir)):
        raise EditorError('O lote não corresponde ao registro local deste editor. '
                          'Nenhum código foi removido; recarregue uma referência limpa.')
    master = struct.unpack_from('<I',raw,payload['completion_address']-spawncode.CAVE)[0]
    publications = [struct.unpack_from('<3I',raw,p['offset']) for p in payload['probes']]
    if master != payload['completion_token'] or any(p[0] != 2 for p in publications):
        raise EditorError('A solicitação antiga ainda não terminou. Retome e pause; '
                          'se a referência não for reconhecida, recarregue um estado limpo.')
    editor._identity()
    if (editor.client.status() is not Status.PAUSED
            or editor.client.read_bytes(spawncode.HOOK,8) != hook
            or editor.client.read_bytes(spawncode.CAVE,4096) != raw):
        raise EditorError('O estado mudou durante a conferência. Nenhuma limpeza foi aplicada.')
    try:
        # The permanent landing remains executable if a saved PC is still there.
        editor.client.write_bytes(spawncode.CAVE,payload['clean_scratch'])
        if (editor.client.read_bytes(spawncode.CAVE,4096) != payload['clean_scratch']
                or editor.client.read_bytes(spawncode.HOOK,8) != spawncode.ORIGINAL
                or editor.client.status() is not Status.PAUSED):
            raise EditorError('A finalização não pôde ser confirmada.')
    except Exception as error:
        editor.unsafe = True
        editor._journal('batch_recovery_unconfirmed',nonce=nonce.hex())
        raise EditorError('A finalização não pôde ser confirmada. Recarregue uma referência limpa.') from error
    editor.pending = None
    editor.replay_queue.clear()
    editor.completion_tokens.add(payload['completion_token'])
    editor._journal('batch_recovered_cancelled',nonce=nonce.hex(),format_version=matched['format_version'])
    return {'pending':False,'core_paused':True,'warning':True,
            'message':'Solicitação antiga finalizada. Os veículos foram preservados; '
                      'o alinhamento e a receita daquela solicitação não foram recuperados.'}
