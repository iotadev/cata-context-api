"""Bounded value receipts for rechecking observations after a queue/restart.

Receipts are trusted local data, not signatures, event bindings or permissions.
The owning consumer must bind them to its exact work item and output. Restoring
a receipt never restores a prompt or selects a producer path.
"""
import json

from .consumer import PreparedCompanionPrompt, _encode
from .reader import MAX_CHARACTERS, guid, integer

MAX_RECEIPT_BYTES = 32768


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f'Invalid {label} fields')


def _restore(record):
    _keys(record, ('version', 'character', 'facts', 'sampled_ms', 'sampled_at_ms',
                   'export_sequence', 'audience', 'expected'), 'companion receipt')
    try:
        size = len(_encode(record).encode('utf-8'))
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError('Invalid companion receipt JSON') from error
    if size > MAX_RECEIPT_BYTES:
        raise ValueError('Companion receipt exceeds 32 KiB')
    if type(record['version']) is not int or record['version'] != 1:
        raise ValueError('Unsupported companion receipt version')
    character = guid(record['character'])
    facts = record['facts']
    if facts is not None:
        if not isinstance(facts, str) or len(facts.encode('utf-8')) > 8192:
            raise ValueError('Invalid companion receipt facts budget')
        try:
            parsed = json.loads(facts)
            _keys(parsed, ('available', 'reason', 'source', 'server', 'binding',
                           'player', 'bot'), 'companion receipt facts')
            if (parsed['available'] is not True or parsed['reason'] != 'current'
                    or parsed['source'] != 'server' or _encode(parsed) != facts
                    or not isinstance(parsed['binding'], dict)
                    or parsed['binding'].get('guid') != character):
                raise ValueError('Inconsistent companion receipt facts')
        except (TypeError, ValueError, RecursionError) as error:
            raise ValueError('Invalid companion receipt facts') from error
    sampled_ms = integer(record['sampled_ms'], 'receipt sample time')
    sampled_at_ms = integer(record['sampled_at_ms'], 'receipt wall sample time')
    sequence = integer(record['export_sequence'], 'receipt export sequence')
    expected = record['expected']
    _keys(expected, ('group_guid', 'map_id', 'realm_id'), 'receipt expectations')
    group = expected['group_guid']
    if group is not None:
        guid(group, 'receipt expected group GUID')
    map_id = expected['map_id']
    if map_id is not None:
        integer(map_id, 'receipt expected map ID', maximum=2**32 - 1)
    realm_id = expected['realm_id']
    if realm_id is not None:
        integer(realm_id, 'receipt expected realm ID', minimum=1, maximum=2**32 - 1)
    audience = record['audience']
    if type(audience) is not list or len(audience) >= MAX_CHARACTERS:
        raise ValueError('Invalid companion receipt audience')
    members = []
    for row in audience:
        _keys(row, ('guid', 'session_generation', 'sampled_ms', 'sampled_at_ms'), 'receipt speaker')
        members.append((guid(row['guid']),
                        integer(row['session_generation'], 'receipt speaker generation', minimum=1),
                        integer(row['sampled_ms'], 'receipt speaker sample time'),
                        integer(row['sampled_at_ms'], 'receipt speaker wall sample time')))
    identities = [row[0] for row in members]
    if identities != sorted(set(identities)) or character in identities or (members and group is None):
        raise ValueError('Inconsistent companion receipt audience')
    if facts is None and (sampled_ms or sampled_at_ms or sequence or members):
        raise ValueError('Unavailable receipt cannot retain observation counters or audience')
    # This object is used only to run the existing recheck. No prompt is restored.
    return PreparedCompanionPrompt('', character, facts, sampled_ms, sampled_at_ms,
                                   sequence, tuple(members), group, map_id, realm_id)


def export_companion_receipt(prepared):
    record = dict(
        version=1, character=prepared.character, facts=prepared._facts_json,
        sampled_ms=prepared._sampled_ms, sampled_at_ms=prepared._sampled_at_ms,
        export_sequence=prepared._sequence,
        audience=[dict(guid=row[0], session_generation=row[1], sampled_ms=row[2], sampled_at_ms=row[3])
                  for row in prepared._audience],
        expected=dict(group_guid=prepared._expected_group, map_id=prepared._expected_map_id,
                      realm_id=prepared._expected_realm_id),
    )
    _restore(record)  # Keep writer/reader bounds and version validation identical.
    return record


def recheck_companion_receipt(queries, record):
    """Validate a saved receipt, then reread now through the caller's Queries.

    Malformed/unsupported records raise ValueError; they must never release
    output. False includes receipts that originally used no native facts.
    True is an instantaneous fact check, not authority to deliver or act.
    """
    return _restore(record).recheck(queries)
