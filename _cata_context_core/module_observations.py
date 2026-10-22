"""Optional native module records, distinct from current party facts and AI history."""
import copy
import math
from .reader import SnapshotError, obj, integer, text, guid, boolean


def number(value, label, nullable=False):
    if value is None and nullable:
        return
    if type(value) not in (int, float) or not math.isfinite(value):
        raise SnapshotError('Invalid ' + label)


def point(value):
    obj(value, 'pilot position')
    for key in ('x', 'y', 'z'):
        number(value.get(key), key, nullable=True)


def record(value, identity, historical, last_sequence):
    obj(value, 'pilot record')
    if guid(value.get('guid')) != identity:
        raise SnapshotError('Pilot subject mismatch')
    for key in ('module_boot', 'source_identity', 'binding_status'):
        text(value.get(key), key, 256)
    if not value['module_boot'] or not value['source_identity']:
        raise SnapshotError('Pilot lacks producer identity')
    for key in ('realm_id', 'map_id', 'instance_id'):
        integer(value.get(key), key, maximum=2**32 - 1)
    integer(value.get('run_token'), 'pilot token', 1, 2147483647)
    integer(value.get('sequence'), 'pilot sequence', 1 if historical else 0, last_sequence if historical else 0)
    if value.get('historical') is not historical or value.get('status') != ('terminal' if historical else 'active'):
        raise SnapshotError('Pilot history/status mismatch')
    if historical:
        text(value.get('end_reason'), 'pilot reason', 128)
        if not value['end_reason']:
            raise SnapshotError('Terminal pilot lacks exact reason')
    elif value.get('end_reason') is not None:
        raise SnapshotError('Active pilot has terminal reason')
    generation = integer(value.get('observer_generation'), 'pilot binding generation')
    if value['binding_status'] == 'bound':
        text(value.get('observer_boot'), 'pilot observer boot')
        if not value['observer_boot'] or not generation:
            raise SnapshotError('Incomplete pilot binding')
    elif value['binding_status'] not in ('unbound', 'unavailable', 'unsupported', 'mismatch') or generation or value.get('observer_boot') is not None:
        raise SnapshotError('Invalid unbound pilot identity')
    for key in ('started_module_ms', 'sampled_module_ms', 'started_at_ms', 'sampled_at_ms', 'elapsed_ms',
                'segments', 'ground_reconciliations'):
        integer(value.get(key), key)
    if value['sampled_module_ms'] < value['started_module_ms'] or value['elapsed_ms'] != value['sampled_module_ms'] - value['started_module_ms']:
        raise SnapshotError('Invalid independent pilot clock')
    boolean(value.get('player_available'), 'pilot player availability')
    state = value.get('pre_cleanup')
    if not value['player_available']:
        if state is not None:
            raise SnapshotError('Unavailable pilot player has native state')
    else:
        obj(state, 'pilot decision state')
        point(state.get('position'))
        for key in ('flags_raw', 'spline_id', 'owned_spline_id'):
            integer(state.get(key), key, maximum=2**32 - 1)
        for key in ('reported_falling', 'freely_controlled', 'self_mover', 'casting', 'forced_movement',
                    'forced_forward', 'spline_initialized', 'spline_falling', 'spline_finalized'):
            boolean(state.get(key), key)
        for key in ('run_rate', 'owned_run_rate'):
            number(state.get(key), key, nullable=True)
    ground = value.get('ground')
    if ground is not None:
        obj(ground, 'pilot ground observation')
        integer(ground.get('sampled_module_ms'), 'ground sample', value['started_module_ms'], value['sampled_module_ms'])
        integer(ground.get('sampled_at_ms'), 'ground wall anchor')
        point(ground.get('position'))
        for key in ('height', 'contact_offset'):
            number(ground.get(key), key, nullable=True)
        boolean(ground.get('reconciliation_applied'), 'ground reconciliation')
        if ground.get('normal') is not None:
            raise SnapshotError('Unsupported ground normal')
    model = obj(value.get('model'), 'pilot model')
    for key in ('velocity_x', 'velocity_y', 'heading', 'yaw_rate'):
        number(model.get(key), key, nullable=True)
    inputs = obj(value.get('input'), 'pilot transport input')
    boolean(inputs.get('accepted'), 'input accepted')
    sequence = integer(inputs.get('sequence'), 'input sequence', maximum=1000000)
    if inputs['accepted']:
        integer(inputs.get('age_ms'), 'input receipt age')
        if not sequence:
            raise SnapshotError('Accepted input lacks sequence')
    elif sequence or inputs.get('age_ms') is not None:
        raise SnapshotError('Unaccepted input contains receipt')
    for key, bounds in (('push', (0, 1)), ('brake', (0, 1)), ('steer', (-1, 1))):
        number(inputs.get(key), key)
        if not bounds[0] <= inputs[key] <= bounds[1]:
            raise SnapshotError('Invalid input range')
    cleanup = obj(value.get('cleanup'), 'pilot cleanup')
    options = {'spline': ('not_requested', 'player_unavailable', 'foreign_preserved', 'released_or_finalized', 'release_unconfirmed'),
               'presentation': ('not_requested', 'player-unavailable', 'external-mount-preserved-or-clear', 'native-dismount'),
               'speed': ('not_requested', 'player_unavailable', 'restored_or_normal', 'foreign_preserved')}
    for key, allowed in options.items():
        if cleanup.get(key) not in allowed or (not historical and cleanup[key] != 'not_requested'):
            raise SnapshotError('Invalid pilot cleanup result')
    number(cleanup.get('run_rate_after'), 'cleanup rate', nullable=True)


def validate_modules(value, row, server, supported):
    obj(value, 'module observations')
    integer(value.get('captured_ms'), 'module capture', maximum=server['uptime_ms'])
    integer(value.get('captured_at_ms'), 'module capture wall')
    if supported != ['skate_pilot_v1']:
        raise SnapshotError('Module payload lacks capability')
    pilot = value.get('skate_pilot')
    if pilot is None:
        return
    obj(pilot, 'skate observations')
    if pilot.get('kind') != 'skate_pilot_v1' or pilot.get('source') != 'mod_skate_native' or pilot.get('capacity') != 16 or pilot.get('retention_scope') != 'realm':
        raise SnapshotError('Unsupported pilot source/bounds')
    for key in ('module_boot', 'source_identity'):
        text(pilot.get(key), key, 256)
        if not pilot[key]:
            raise SnapshotError('Missing pilot provider identity')
    sequence = integer(pilot.get('last_sequence'), 'last pilot sequence')
    overwritten = integer(pilot.get('overwritten'), 'pilot eviction count')
    if overwritten != max(0, sequence - 16):
        raise SnapshotError('Inconsistent pilot eviction count')
    terminal = pilot.get('terminal')
    if not isinstance(terminal, list) or len(terminal) > 16:
        raise SnapshotError('Invalid pilot ring')
    previous = 0
    tokens, boots = set(), set()
    for item in terminal:
        record(item, row['guid'], True, sequence)
        if not previous < item['sequence'] or item['sequence'] <= overwritten:
            raise SnapshotError('Invalid pilot sequence order')
        previous = item['sequence']
        identity = (item['module_boot'], item['run_token'])
        if identity in tokens:
            raise SnapshotError('Duplicate pilot token')
        tokens.add(identity)
        boots.add(item['module_boot'])
        if item['source_identity'] != pilot['source_identity']:
            raise SnapshotError('Mixed pilot source identities')
    active = pilot.get('active')
    if active is not None:
        record(active, row['guid'], False, sequence)
        if (active['module_boot'], active['run_token']) in tokens:
            raise SnapshotError('Terminal pilot is still active')
        boots.add(active['module_boot'])
        if active['source_identity'] != pilot['source_identity']:
            raise SnapshotError('Mixed active source identity')
    if boots - {pilot['module_boot']}:
        raise SnapshotError('Mixed module boots in native ring')


def query_modules(row, server, now, status, source, max_age):
    wrapper = row.get('module_observations')
    if not wrapper or wrapper['skate_pilot'] is None:
        return None
    result = copy.deepcopy(wrapper['skate_pilot'])
    capture_age = max(0, now - wrapper['captured_at_ms'], server['uptime_ms'] - wrapper['captured_ms'])
    result['capture_age_ms'] = capture_age
    result['captured_ms'] = wrapper['captured_ms']
    result['captured_at_ms'] = wrapper['captured_at_ms']

    def bound(record):
        return (record['binding_status'] == 'bound' and record['observer_boot'] == server['boot_id']
                and record['observer_generation'] == row['session_generation']
                and record['realm_id'] == server['realm_id'])

    def age(record):
        # Module steady time has a different epoch; correlate only wall/elapsed anchors.
        elapsed_wall = record['sampled_at_ms'] - record['started_at_ms']
        if record['sampled_at_ms'] > now + 2000 or abs(elapsed_wall - record['elapsed_ms']) > 2000:
            return None
        return max(0, now - record['sampled_at_ms'],
                   capture_age + wrapper['captured_at_ms'] - record['sampled_at_ms'])

    for item in result['terminal']:
        item['sample_age_ms'] = age(item)
        item['binding_matches_current'] = bound(item)
    active = result['active']
    reason = 'none'
    if active is not None:
        reason = status if status != 'ok' else 'non_native_source' if source != 'server' else row['state']
        sample_age = age(active)
        if reason == 'online':
            if not bound(active):
                reason = 'binding_mismatch'
            elif not active['player_available'] or not row.get('player'):
                reason = 'unobserved'
            elif (active['map_id'], active['instance_id']) != (row['player']['map_id'], row['player']['instance_id']):
                reason = 'location_mismatch'
            elif row['sampled_at_ms'] > now + 2000:
                reason = 'clock_mismatch'
            elif max(now - row['sampled_at_ms'], server['uptime_ms'] - row['sampled_ms']) > max_age:
                reason = 'stale'
            elif sample_age is None:
                reason = 'clock_mismatch'
            elif max(sample_age, capture_age) > max_age:
                reason = 'stale'
            else:
                reason = 'current'
        if reason != 'current':
            result['active'] = None
        else:
            active['sample_age_ms'] = sample_age
            if active['input']['age_ms'] is not None:
                active['input']['age_ms'] += sample_age
    result['active_availability'] = reason
    result['note'] = 'Terminal records are historical native decisions. Model velocity and received controls do not prove client motion or physical keys. Eviction is realm-wide; missing records are not absence evidence.'
    return result
