"""Reviewable postprocessing and segment-explicit residuals (stdlib only)."""
import bisect
import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from uuid import uuid4


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def bound(value, label, low, high):
    if not finite(value) or not low <= value <= high: raise ValueError(
        f'{label}は{low}〜{high}の有限値で指定してください。')
    return value


def interpolate(points, time, key):
    """Only adjacent rows in an explicitly chosen segment. Missing rows remain gaps."""
    times = [p['time_s'] for p in points]
    index = bisect.bisect_left(times, time)
    if index < len(points) and times[index] == time:
        return points[index].get(key) if finite(points[index].get(key)) else None
    if not 0 < index < len(points): return None
    a, b = points[index - 1], points[index]
    if not finite(a.get(key)) or not finite(b.get(key)) or b['time_s'] <= a['time_s']: return None
    return a[key] + (b[key] - a[key]) * (time - a['time_s']) / (b['time_s'] - a['time_s'])


def balance_summary(points, initial_soc=None):
    totals = dict(discharge_ah=0., charge_ah=0., discharge_wh=0., charge_wh=0.)
    skipped = 0
    for a, b in zip(points, points[1:]):
        if a.get('segment_id') != b.get('segment_id'): continue
        if not all(finite(p.get(k)) for p in (a, b) for k in ('time_s', 'current_a', 'voltage_v')) or b['time_s'] <= a[
            'time_s']:
            skipped += 1;
            continue
        pieces = [(a, b)]
        if a['current_a'] * b['current_a'] < 0:
            f = -a['current_a'] / (b['current_a'] - a['current_a'])
            zero = dict(time_s=a['time_s'] + f * (b['time_s'] - a['time_s']), current_a=0,
                        voltage_v=a['voltage_v'] + f * (b['voltage_v'] - a['voltage_v']))
            pieces = [(a, zero), (zero, b)]
        for left, right in pieces:
            dt = right['time_s'] - left['time_s']
            charge = (left['current_a'] + right['current_a']) / 2 * dt / 3600
            energy = dt / 21600 * (2 * left['current_a'] * left['voltage_v'] + left['current_a'] * right['voltage_v'] +
                                   right['current_a'] * left['voltage_v'] + 2 * right['current_a'] * right['voltage_v'])
            prefix = 'discharge' if charge >= 0 else 'charge'
            totals[prefix + '_ah'] += abs(charge);
            totals[prefix + '_wh'] += abs(energy)
    final_soc = points[-1].get('soc') if points else None
    closed = finite(initial_soc) and finite(final_soc) and abs(final_soc - initial_soc) <= .005 and not skipped
    eligible = closed and totals['charge_ah'] > 1e-9 and totals['discharge_ah'] > 1e-9 and totals['charge_wh'] > 1e-9
    totals.update(coulombic_efficiency=totals['discharge_ah'] / totals['charge_ah'] if eligible else None,
                  energy_efficiency=totals['discharge_wh'] / totals['charge_wh'] if eligible else None,
                  efficiency_status='conditional_ledger_ratio' if eligible else 'unavailable',
                  skipped_intervals=skipped,
                  note='出力点間のI,V線形近似の区間積分。区間境界・欠損を跨がない。効率はSOC帳簿差≤0.005かつ充放電がある場合の区間比で、完全サイクルや実測精度を保証しません。')
    checks = {}
    for name, components, total, tolerance in [
        ('voltage',
         ['surface_ocv_v', 'reaction_overpotential_v', 'electrolyte_ohmic_loss_v', 'concentration_overpotential_v',
          'solid_ohmic_loss_v'], 'voltage_v', 1e-4),
        ('heat',
         ['ohmic_heating_w', 'reaction_heating_w', 'reversible_heating_w', 'hysteresis_heating_w', 'mixing_heating_w'],
         'total_heating_w', 1e-6)]:
        residuals = [p[total] - sum(p[k] for k in components) for p in points if
                     all(finite(p.get(k)) for k in components + [total])]
        checks[name] = dict(status='available' if len(residuals) == len(points) and points else 'unavailable',
                            max_absolute_residual=max(map(abs, residuals)) if residuals else None,
                            tolerance=tolerance, unit='V' if name == 'voltage' else 'W',
                            passed=max(map(abs, residuals)) <= tolerance if residuals and len(residuals) == len(
                                points) else None,
                            equation=total + ' = ' + ' + '.join(components))
    totals['balance_checks'] = checks
    return totals


def _record(kind, project, config, sources):
    return dict(id=str(uuid4()), project_id=project, created_at=datetime.now(timezone.utc).isoformat(),
                record_type=kind, schema_version='1.0', config=config, source_snapshots=sources,
                validation_status='analysis_only_not_cell_validation')


def snapshot(run):
    return dict(id=run['id'], name=run.get('name'), source_type=run.get('source_type'), engine=run.get('engine'),
                original=run.get('original'), source=run.get('source'), specimen_id=run.get('specimen_id'),
                temperature_position=run.get('temperature_position'), transform=run.get('transform'),
                mode=run.get('mode'), license=run.get('license'), notes=run.get('notes'),
                input_sha256=run.get('input_sha256'), input=run.get('input'),
                points_sha256=hashlib.sha256(
                    json.dumps(run['points'], sort_keys=True, allow_nan=False).encode()).hexdigest())


def postprocess(run, config):
    defaults = dict(smoothing_window=5, min_delta_v=1e-5, min_delta_q=1e-7, pulse_delay_s=10.,
                    current_step_a=.05, rest_min_s=30.)
    if not isinstance(config, dict) or set(config) - set(defaults): raise ValueError('後処理設定を確認してください。')
    c = {**defaults, **config}
    w = c['smoothing_window']
    if isinstance(w, bool) or not isinstance(w, int) or w not in range(1, 32, 2): raise ValueError(
        '平滑化窓は1〜31の奇数です。')
    for key, low, high in [('min_delta_v', 1e-8, .1), ('min_delta_q', 1e-10, 1), ('pulse_delay_s', .1, 600),
                           ('current_step_a', .001, 25), ('rest_min_s', 1, 3600)]: bound(c[key], key, low, high)
    points = run['points']
    groups = [];
    group = [];
    previous = None
    for p in points:
        valid = finite(p.get('voltage_v')) and finite(p.get('capacity_ah'))
        current = p.get('current_a')
        sign = 1 if finite(current) and current > 1e-8 else -1 if finite(current) and current < -1e-8 else 0
        if current is None: sign = -1 if run.get('mode') == 'charge' else 1 if run.get('mode') == 'discharge' else 0
        if not valid or sign == 0 or (previous is not None and (p.get('segment_id') != previous.get('segment_id') or
                                                                p['capacity_ah'] <= previous['capacity_ah'] or sign !=
                                                                previous['_sign'])):
            if group: groups.append(group)
            group = []
        if valid and sign:
            previous = dict(p, _sign=sign);
            group.append(previous)
        else:
            previous = None
    if group: groups.append(group)
    derivative = []
    for index, group in enumerate(groups):
        smoothed = []
        for i in range(w // 2, len(group) - w // 2):
            window = group[i - w // 2:i + w // 2 + 1]
            smoothed.append(dict(q=sum(p['capacity_ah'] for p in window) / w, v=sum(p['voltage_v'] for p in window) / w,
                                 time_s=group[i].get('time_s'), segment_id=group[i].get('segment_id')))
        for i in range(1, len(smoothed) - 1):
            a, b = smoothed[i - 1], smoothed[i + 1]
            dq, dv = b['q'] - a['q'], b['v'] - a['v']
            derivative.append(dict(group=index, segment_id=smoothed[i]['segment_id'], time_s=smoothed[i]['time_s'],
                                   capacity_ah=smoothed[i]['q'], voltage_v=smoothed[i]['v'],
                                   dq_dv_ah_v=dq / dv if abs(dv) >= c['min_delta_v'] and dq >= c[
                                       'min_delta_q'] else None,
                                   dv_dq_v_ah=dv / dq if dq >= c['min_delta_q'] else None))
    pulses = []
    for i in range(1, len(points)):
        before, after = points[i - 1], points[i]
        if not all(finite(p.get(k)) for p in (before, after) for k in ('time_s', 'current_a', 'voltage_v')) or after[
            'time_s'] < before['time_s']: continue
        delta = after['current_a'] - before['current_a']
        if abs(delta) < c['current_step_a']: continue
        plateau = [after]
        for p in points[i + 1:]:
            if not all(finite(p.get(k)) for k in ('time_s', 'current_a', 'voltage_v')) or p.get(
                'segment_id') != after.get('segment_id') or p['time_s'] <= plateau[-1]['time_s'] or abs(
                p['current_a'] - after['current_a']) > c['current_step_a'] / 2: break
            plateau.append(p)
            if p['time_s'] >= after['time_s'] + c['pulse_delay_s']: break
        voltage = interpolate(plateau, after['time_s'] + c['pulse_delay_s'], 'voltage_v')
        if after['time_s'] - before['time_s'] > c['pulse_delay_s']: voltage = None
        pulses.append(dict(time_s=after['time_s'], delta_current_a=delta, baseline_time_s=before['time_s'],
                           delay_s=c['pulse_delay_s'],
                           resistance_ohm=-(voltage - before['voltage_v']) / delta if voltage is not None else None,
                           status='available' if voltage is not None else 'insufficient_constant_current_window'))
    # GITT indices only for a constant-current pulse bracketed by measured rests.
    blocks = [];
    block = []
    for p in points:
        if not all(finite(p.get(k)) for k in ('time_s', 'current_a', 'voltage_v')):
            if block: blocks.append(block)
            blocks.append([]);
            block = [];
            continue
        if block and (p['time_s'] < block[-1]['time_s'] or p.get('segment_id') != block[-1].get('segment_id') or
                      abs(p['current_a'] - block[0]['current_a']) >= c['current_step_a']):
            blocks.append(block);
            block = []
        block.append(p)
    if block: blocks.append(block)
    gitt = []
    for i in range(1, len(blocks) - 1):
        prior, pulse, rest = blocks[i - 1:i + 2]
        if not prior or len(pulse) < 3 or not rest: continue
        if pulse[0]['time_s'] < prior[-1]['time_s'] or rest[0]['time_s'] < pulse[-1]['time_s']: continue
        if abs(pulse[0]['current_a']) < c['current_step_a'] or any(
            abs(p['current_a']) >= c['current_step_a'] for p in prior + rest): continue
        duration = pulse[-1]['time_s'] - pulse[0]['time_s']
        # Experiment boundaries may differ by one floating-point ULP.
        if duration <= 0 or prior[-1]['time_s'] - prior[0]['time_s'] + 1e-8 < c['rest_min_s'] or rest[-1]['time_s'] - \
                rest[0]['time_s'] + 1e-8 < c['rest_min_s']: continue
        et = pulse[-1]['voltage_v'] - pulse[0]['voltage_v']
        es = rest[-1]['voltage_v'] - prior[-1]['voltage_v']
        xs = [math.sqrt(max(0, p['time_s'] - pulse[0]['time_s'])) for p in pulse]
        ys = [p['voltage_v'] for p in pulse]
        xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
        slope = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / sum((x - xm) ** 2 for x in xs)
        gitt.append(dict(pulse_start_s=pulse[0]['time_s'], pulse_duration_s=duration,
                         rest_duration_s=rest[-1]['time_s'] - rest[0]['time_s'],
                         delta_pulse_v=et, delta_rest_v=es, sqrt_time_slope_v_sqrt_s=slope,
                         relaxation_index_per_s=(es / et) ** 2 / duration if abs(et) >= c['min_delta_v'] else None))
    record = _record('postprocess', run.get('project_id', 'default'), c, [snapshot(run)])
    record.update(derivatives=derivative, pulses=pulses, gitt=gitt,
                  units=dict(dq_dv_ah_v='Ah/V', dv_dq_v_ah='V/Ah', resistance_ohm='ohm', relaxation_index_per_s='1/s',
                             sqrt_time_slope_v_sqrt_s='V/sqrt(s)'),
                  method='Centered moving mean of Q and V in full odd windows, then centered secant. No crossing segments/rests/current direction changes or gaps.',
                  limitations=['dQ/dVは絶対通過容量と符号付き電圧変化の微分。閾値未満は取得不可。平滑化の窓と閾値を記録。',
                               'パルス抵抗=-ΔV/ΔI、指定遅延での定電流窓内だけを使用。負値も保持。規格DCIRではありません。',
                               'GITT型のΔE・sqrt(t)傾き・緩和指標のみ。前後休止を要し、平衡到達は保証しない。幾何・活物質量のない拡散係数Dは算出しません。'])
    return record


def compare(simulation, measured, config):
    defaults = dict(simulation_segment=0, measurement_segment=0, time_offset_s=0., variable='voltage_v',
                    current_tolerance_a=.05, temperature_tolerance_c=2.)
    if not isinstance(config, dict) or set(config) - set(defaults): raise ValueError('実測比較設定を確認してください。')
    c = {**defaults, **config}
    if simulation.get('record_type') != 'physics' or measured.get('record_type') != 'dataset': raise ValueError(
        '物理計算結果と取込データを指定してください。')
    if c['variable'] not in ('voltage_v', 'current_a', 'temperature_c'): raise ValueError('比較変数を確認してください。')
    for key in ('simulation_segment', 'measurement_segment'):
        if isinstance(c[key], bool) or not isinstance(c[key], int) or c[key] < 0: raise ValueError(
            '比較区間は非負整数で指定してください。')
    for key, low, high in [('time_offset_s', -86400, 86400), ('current_tolerance_a', 0, 25),
                           ('temperature_tolerance_c', 0, 100)]: bound(c[key], key, low, high)
    a = [p for p in simulation['points'] if
         p.get('segment_id', 0) == c['simulation_segment'] and finite(p.get('time_s'))]
    b = [p for p in measured['points'] if
         p.get('segment_id', 0) == c['measurement_segment'] and finite(p.get('time_s'))]
    if not a or not b: raise ValueError('時間系列のある区間を明示してください。')
    if any(y['time_s'] <= x['time_s'] for rows in (a, b) for x, y in zip(rows, rows[1:])):
        raise ValueError('選択区間に重複・非昇順時刻があります。原本を保持したまま区間を分けてください。')
    rows = [];
    excluded = dict(outside_overlap=0, missing=0)
    previous_row = -2;
    group = -1
    for source_index, p in enumerate(b):
        t = p['time_s'] + c['time_offset_s']
        if t < a[0]['time_s'] or t > a[-1]['time_s']: excluded['outside_overlap'] += 1; continue
        value = interpolate(a, t, c['variable'])
        if value is None or not finite(p.get(c['variable'])): excluded['missing'] += 1; continue
        if source_index != previous_row + 1: group += 1
        previous_row = source_index
        row = dict(time_s=t, measurement_time_s=p['time_s'], measurement_index=source_index, group=group,
                   predicted=value, observed=p[c['variable']], residual=value - p[c['variable']])
        for key in ('current_a', 'temperature_c'):
            predicted = interpolate(a, t, key)
            row[key + '_difference'] = predicted - p[key] if predicted is not None and finite(p.get(key)) else None
        rows.append(row)
    if not rows: raise ValueError('欠損のない比較点が重なる時間範囲にありません。外挿しません。')
    conditions = {}
    for key, tolerance in [('current_a', c['current_tolerance_a']), ('temperature_c', c['temperature_tolerance_c'])]:
        diffs = [abs(p[key + '_difference']) for p in rows if finite(p[key + '_difference'])]
        conditions[key] = dict(
            status='unknown' if len(diffs) != len(rows) else 'matched' if max(diffs) <= tolerance else 'mismatch',
            max_absolute_difference=max(diffs) if diffs else None, tolerance=tolerance)
    conditions['initial_state_and_materials'] = dict(status='review_required',
                                                     requested_initial_state=simulation.get('initial_state'),
                                                     specimen_id=measured.get('specimen_id'),
                                                     note='初期SOC/OCV、容量基準、材料・設計と対象セルの同一性は手動確認が必要です。')
    conditions['temperature_basis'] = dict(simulation='volume_average',
                                           measured=measured.get('temperature_position', 'unknown'),
                                           status='review_required')
    residuals = [r['residual'] for r in rows]
    record = _record('residual_analysis', simulation.get('project_id', 'default'), c,
                     [snapshot(simulation), snapshot(measured)])
    record.update(rows=rows, excluded=excluded, conditions=conditions,
                  units='V' if c['variable'] == 'voltage_v' else 'A' if c['variable'] == 'current_a' else 'degC',
                  metrics=dict(count=len(rows), rmse=math.sqrt(sum(v * v for v in residuals) / len(rows)),
                               mae=sum(map(abs, residuals)) / len(rows),
                               bias=sum(residuals) / len(rows), max_absolute=max(map(abs, residuals))),
                  alignment='simulation_time = measurement_time + time_offset_s; adjacent-row linear interpolation within chosen simulation segment only',
                  limitations=[
                      '電流・温度・初期状態・測定位置・材料/設計の同一性は別途確認が必要です。条件差があっても残差は表示し、校正済みとは扱いません。',
                      '時刻リセット・欠損・区間境界を跨ぐ補間、外挿、自動時刻合わせを行いません。非実測データの場合は数式の比較であり実測検証ではありません。'])
    return record


def analysis_csv(record):
    stream = io.StringIO(newline='')
    for key in ('id', 'record_type', 'config', 'source_snapshots', 'validation_status', 'limitations',
                'units', 'method', 'metrics', 'conditions', 'excluded', 'alignment'):
        if key in record: stream.write('# ' + key + ': ' + json.dumps(record[key], ensure_ascii=False) + '\n')
    if record['record_type'] == 'residual_analysis':
        rows = [dict(section='residual', **row) for row in record['rows']]
    else:
        rows = [dict(section=section, **row) for section in ('derivatives', 'pulses', 'gitt') for row in
                record[section]]
    columns = list(dict.fromkeys(key for row in rows for key in row)) or ['section']
    writer = csv.DictWriter(stream, fieldnames=columns);
    writer.writeheader();
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')
