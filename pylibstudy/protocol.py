"""Bounded, declarative P1 protocols; no solver imports or executable user code."""
import math
from copy import deepcopy
from datetime import datetime

from .materials import SETS

REFERENCE_CAPACITIES = {k: v['capacity'] for k, v in SETS.items()}
MAX_STEPS = 200
COMMON = {'duration_s', 'period_s', 'temperature_c', 'tags', 'skip_ok'}
FIELDS = {
    'cc': {'current_a', 'stop_voltage_v'}, 'c_rate': {'c_rate', 'stop_voltage_v'},
    'cv': {'voltage_v', 'stop_current_a', 'stop_c_rate'}, 'rest': set(),
    'cp': {'power_w', 'stop_voltage_v', 'control', 'control_tau_s'},
    'cr': {'resistance_ohm', 'stop_voltage_v', 'control', 'control_tau_s'},
    'profile': {'points'},
}


def integer(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{label}は{low}〜{high}の整数で指定してください。')
    return value


def validate_protocol(c, number):
    integer(c['cycles'], 'サイクル数', 1, 20)
    if c['start_time'] is not None:
        try:
            if not isinstance(c['start_time'], str) or len(c['start_time']) > 40 or 'T' not in c['start_time']:
                raise ValueError()
            datetime.fromisoformat(c['start_time'])
        except (ValueError, TypeError):
            raise ValueError('開始日時はISO形式（例: 2026-10-17T09:00:00+09:00）で指定してください。') from None

    def walk(nodes, depth=0):
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 20:
            raise ValueError('各試験ブロックは1〜20項目です。')
        for s in nodes:
            if not isinstance(s, dict) or not isinstance(s.get('kind'), str):
                raise ValueError('ステップの種類を指定してください。')
            kind = s['kind']
            if kind == 'repeat':
                if depth >= 3 or set(s) - {'kind', 'count', 'steps'}:
                    raise ValueError('繰返しは3階層までで、kind・count・stepsのみ指定できます。')
                integer(s.get('count'), 'ブロック繰返し数', 1, 20)
                walk(s.get('steps'), depth + 1)
                continue
            if kind not in FIELDS or set(s) - ({'kind'} | COMMON | FIELDS[kind]):
                raise ValueError('ステップの入力項目が未対応です。')
            if 'skip_ok' in s and not isinstance(s['skip_ok'], bool):
                raise ValueError('skip_okは真偽値で指定してください。')
            tags = s.get('tags', [])
            if not isinstance(tags, list) or len(tags) > 8 or any(
                    not isinstance(t, str) or not t.strip() or len(t) > 40 for t in tags):
                raise ValueError('タグは1〜40文字の文字列で8件以内です。')
            number(s.get('period_s', c['dt_s']), 'ステップ出力周期', .1, 60)
            number(s.get('temperature_c', c['ambient_temp_c']), 'ステップ周囲温度', 0, 45)
            if kind == 'profile':
                if 'duration_s' in s:
                    raise ValueError('波形の時間は最終点から決定します。duration_sは指定しません。')
                points = s.get('points')
                if not isinstance(points, list) or not 2 <= len(points) <= 2000:
                    raise ValueError('電流プロファイルは2〜2000点で指定してください。')
                previous = -1
                for pair in points:
                    if not isinstance(pair, list) or len(pair) != 2:
                        raise ValueError('プロファイルは[秒, A]の組で指定してください。')
                    t = number(pair[0], '波形時間', 0, 21600)
                    number(pair[1], '波形電流', -25, 25)
                    if t <= previous:
                        raise ValueError('波形時間は重複なしの昇順です。')
                    previous = t
                if points[0][0] != 0:
                    raise ValueError('波形時間は0秒から始めてください。')
            else:
                number(s.get('duration_s'), 'ステップ時間', .1, 21600)
            if kind == 'cc': number(s.get('current_a'), 'CC電流', -25, 25)
            if kind == 'c_rate': number(s.get('c_rate'), 'C-rate', -100, 100)
            if kind in {'cp', 'cr'}:
                if s.get('control', 'implicit') not in ('implicit', 'explicit', 'differential'):
                    raise ValueError('CP/CR制御はimplicit・explicit・differentialから指定してください。')
                if 'control_tau_s' in s and s.get('control', 'implicit') != 'differential':
                    raise ValueError('制御時定数は微分制御でのみ指定します。')
                number(s.get('control_tau_s', 1), '制御時定数', .1, 60)
                if kind == 'cp':
                    power = number(s.get('power_w'), '電力', -25 * c['min_voltage_v'], 25 * c['min_voltage_v'])
                    if power == 0: raise ValueError('0 Wには休止ステップを使用してください。')
                else:
                    resistance = number(s.get('resistance_ohm'), '抵抗', -10000, 10000)
                    if abs(resistance) < c['max_voltage_v'] / 25:
                        raise ValueError('抵抗の絶対値は上限電圧/25 A以上にしてください。')
            if s.get('stop_voltage_v') is not None:
                number(s['stop_voltage_v'], '終止電圧', c['min_voltage_v'], c['max_voltage_v'])
                if s.get('current_a', s.get('c_rate', 1)) == 0:
                    raise ValueError('電流0には休止ステップを使用してください。')
            if kind == 'cv':
                number(s.get('voltage_v'), 'CV電圧', c['min_voltage_v'], c['max_voltage_v'])
                if ('stop_current_a' in s) == ('stop_c_rate' in s):
                    raise ValueError('CV終止電流はAまたはC-rateの一方だけ指定してください。')
                key = 'stop_current_a' if 'stop_current_a' in s else 'stop_c_rate'
                number(s[key], 'CV終止電流の絶対値', .001, 25 if key == 'stop_current_a' else 100)

    walk(c['protocol'])
    plan = expand_protocol(c)
    total = sum(x['duration_s'] for cycle in plan for x in cycle)
    points = sum(math.ceil(x['duration_s'] / x['period_s']) + 2 for cycle in plan for x in cycle)
    if total > 21600 or points > 12000:
        raise ValueError('繰返し展開後で合計6時間・出力約12000点以内に調整してください。')


def expand_protocol(c):
    """Return bounded cycles with source paths; input remains immutable."""
    expanded = []

    def walk(nodes, path=()):
        for i, s in enumerate(nodes):
            if s['kind'] == 'repeat':
                for repetition in range(s['count']): walk(s['steps'], path + (i, repetition))
            else:
                if len(expanded) * c['cycles'] >= MAX_STEPS:
                    raise ValueError(f'繰返し展開後は{MAX_STEPS}ステップまでです。')
                expanded.append(dict(step=deepcopy(s), source_path=list(path + (i,)),
                                     duration_s=s['points'][-1][0] if s['kind'] == 'profile' else s['duration_s'],
                                     period_s=s.get('period_s', c['dt_s'])))

    walk(c['protocol'])
    return [deepcopy(expanded) for _ in range(c['cycles'])]


def capacity_reference(c, design=None):
    if c['parameter_set'] == 'BPX': return c['material_settings']['overrides'].get('Nominal cell capacity [A.h]',
                                                                                   c['material_settings']['bpx'][
                                                                                       'Parameterisation']['Cell'][
                                                                                       'Nominal cell capacity [A.h]'])
    return (design['capacity']['c_rate_reference_ah'] if design else c.get('material_settings', {}).get('overrides',
                                                                                                        {}).get(
        'Nominal cell capacity [A.h]', REFERENCE_CAPACITIES[c['parameter_set']]))


def preview_protocol(c, design=None):
    capacity = capacity_reference(c, design)
    rows = []
    elapsed = 0
    for cycle_i, cycle in enumerate(expand_protocol(c), 1):
        for step_i, item in enumerate(cycle, 1):
            s = item['step']
            current = s.get('current_a') if s['kind'] == 'cc' else s.get('c_rate', 0) * capacity if s[
                                                                                                        'kind'] == 'c_rate' else 0 if \
            s['kind'] == 'rest' else None
            cutoff = s.get('stop_current_a', s.get('stop_c_rate', 0) * capacity) if s['kind'] == 'cv' else None
            if (current is not None and abs(current) > 25) or (cutoff is not None and not .001 <= cutoff <= 25):
                raise ValueError('C-rate換算後の電流は±25 A以内、CV終止電流は0.001〜25 Aにしてください。')
            rows.append(dict(index=len(rows), cycle=cycle_i, step_number=step_i, source_path=item['source_path'],
                             kind=s['kind'], start_upper_s=elapsed, duration_s=item['duration_s'],
                             end_upper_s=elapsed + item['duration_s'], period_s=item['period_s'],
                             temperature_c=s.get('temperature_c', c['ambient_temp_c']),
                             current_a=current, c_rate=current / capacity if current is not None else None,
                             stop_current_a=cutoff, power_w=s.get('power_w'), resistance_ohm=s.get('resistance_ohm'),
                             stop_voltage_v=s.get('stop_voltage_v'), voltage_v=s.get('voltage_v'),
                             control=s.get('control', 'implicit') if s['kind'] in {'cp', 'cr'} else None,
                             skip_ok=s.get('skip_ok', False), tags=s.get('tags', []),
                             output_points_upper=math.ceil(item['duration_s'] / item['period_s']) + 2))
            elapsed += item['duration_s']
    return dict(c_rate_reference_ah=capacity,
                capacity_source='保存設計の基準容量' if design else c['parameter_set'] + 'のNominal cell capacity',
                cycles=c['cycles'], total_steps=len(rows), duration_upper_s=elapsed,
                output_points_upper=sum(r['output_points_upper'] for r in rows), steps=rows,
                start_time=c['start_time'],
                note='時間は各ステップ上限の累計。終止・スキップで短縮します。日時は試験の時刻ラベルであり実行予約ではありません。CP/CR/CVの電流は解で決まります。')


def protocol_templates():
    return [dict(id='cccv', label='CCCV充電＋休止', protocol=[
        dict(kind='c_rate', c_rate=-.2, duration_s=7200, stop_voltage_v=4.0, tags=['CC充電']),
        dict(kind='cv', voltage_v=4.0, duration_s=1800, stop_c_rate=.05, tags=['CV充電']),
        dict(kind='rest', duration_s=60)]),
            dict(id='hppc', label='HPPC型パルス（例示条件）', protocol=[dict(kind='repeat', count=2, steps=[
                dict(kind='c_rate', c_rate=.2, duration_s=10, tags=['放電パルス']),
                dict(kind='rest', duration_s=40), dict(kind='c_rate', c_rate=-.2, duration_s=10, tags=['充電パルス']),
                dict(kind='rest', duration_s=40)])]),
            dict(id='gitt', label='GITT型パルス＋緩和（例示条件）', protocol=[dict(kind='repeat', count=3, steps=[
                dict(kind='c_rate', c_rate=.1, duration_s=60, tags=['微小放電']),
                dict(kind='rest', duration_s=600, tags=['緩和'])])])]
