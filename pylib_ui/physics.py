"""Validated JSON contract for isolated electrochemical workers (stdlib only)."""
import math
from copy import deepcopy

PHYSICS_VERSION = '1.0.0'
PINNED_PYBAMM = '26.10.1.0'
DEFAULTS = dict(name='SPMe · 基準プロトコル', model='SPMe', parameter_set='Chen2020',
                thermal='isothermal', initial_soc=.5, initial_temp_c=25, ambient_temp_c=25,
                heat_transfer_w_m2_k=10, min_voltage_v=2.5, max_voltage_v=4.2,
                dt_s=5, mesh='normal', rtol=1e-6, atol=1e-6, timeout_s=120,
                design_id=None, protocol=[dict(kind='cc', current_a=1, duration_s=30),
                                          dict(kind='rest', duration_s=10),
                                          dict(kind='cc', current_a=-1, duration_s=30)])
MESHES = {'coarse': (10, 10), 'normal': (20, 20), 'fine': (40, 40)}


def number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(
            value) or not low <= value <= high:
        raise ValueError(f'{label} は{low}〜{high}の有限値で指定してください。')
    return value


def validate_request(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('物理計算の入力項目を確認してください。')
    c = deepcopy(DEFAULTS);
    c.update(deepcopy(data))
    if not isinstance(c['name'], str) or not c['name'].strip() or len(c['name']) > 100:
        raise ValueError('計算名は1〜100文字で指定してください。')
    for key, choices in dict(model=['SPMe', 'DFN'], parameter_set=['Chen2020', 'Chen2020_composite'],
                             thermal=['isothermal', 'lumped'], mesh=list(MESHES)).items():
        if not isinstance(c[key], str) or c[key] not in choices:
            raise ValueError(f'{key} は検証済みの選択肢を指定してください。')
    if c['parameter_set'] == 'Chen2020_composite' and (c['model'] != 'DFN' or c['thermal'] != 'isothermal'):
        raise ValueError('複合負極はDFN・等温のみ対応しています。')
    for key, bounds in dict(initial_soc=(0, 1), initial_temp_c=(0, 45), ambient_temp_c=(0, 45),
                            heat_transfer_w_m2_k=(0, 100), min_voltage_v=(2, 4), max_voltage_v=(2.5, 4.3),
                            dt_s=(.1, 60), rtol=(1e-8, 1e-3), atol=(1e-8, 1e-3), timeout_s=(5, 300)).items():
        number(c[key], key, *bounds)
    if c['min_voltage_v'] >= c['max_voltage_v']:
        raise ValueError('下限電圧は上限電圧より小さくしてください。')
    if c['design_id'] is not None and (not isinstance(c['design_id'], str) or len(c['design_id']) > 100):
        raise ValueError('保存済み設計IDを指定してください。')
    protocol = c['protocol']
    if not isinstance(protocol, list) or not 1 <= len(protocol) <= 20:
        raise ValueError('プロトコルは1〜20ステップです。')
    total = 0
    for step in protocol:
        if not isinstance(step, dict) or not isinstance(step.get('kind'), str):
            raise ValueError('ステップの種類を指定してください。')
        kind = step['kind']
        allowed = {'cc': {'kind', 'current_a', 'duration_s', 'stop_voltage_v'},
                   'cv': {'kind', 'voltage_v', 'duration_s', 'stop_current_a'},
                   'rest': {'kind', 'duration_s'}, 'profile': {'kind', 'points'}}
        if kind not in allowed or set(step) - allowed[kind]:
            raise ValueError('ステップの入力項目が未対応です。')
        if kind == 'profile':
            points = step.get('points')
            if not isinstance(points, list) or not 2 <= len(points) <= 2000:
                raise ValueError('電流プロファイルは2〜2000点で指定してください。')
            previous = -1
            for pair in points:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError('プロファイルは[秒, A]の組で指定してください。')
                t = number(pair[0], 'プロファイル時間', 0, 21600)
                number(pair[1], 'プロファイル電流', -25, 25)
                if t <= previous:
                    raise ValueError('プロファイル時間は重複なしの昇順です。')
                previous = t
            if points[0][0] != 0:
                raise ValueError('プロファイル時間は0秒から始めてください。')
            total += points[-1][0]
        else:
            total += number(step.get('duration_s'), 'ステップ時間', .1, 21600)
            if kind == 'cc':
                number(step.get('current_a'), 'CC電流', -25, 25)
                if step.get('stop_voltage_v') is not None:
                    number(step['stop_voltage_v'], 'CC終止電圧', c['min_voltage_v'], c['max_voltage_v'])
                    if step['current_a'] == 0:
                        raise ValueError('電流0には休止ステップを使用してください。')
            if kind == 'cv':
                number(step.get('voltage_v'), 'CV電圧', c['min_voltage_v'], c['max_voltage_v'])
                number(step.get('stop_current_a'), 'CV終止電流の絶対値', .001, 25)
    if any(step['kind'] == 'profile' for step in protocol) and len(protocol) != 1:
        raise ValueError('電流プロファイルは単独の試験として指定してください。')
    if total > 21600 or math.ceil(total / c['dt_s']) + 2 * len(protocol) > 12000:
        raise ValueError('合計6時間・出力約12000点以内になるよう時間と出力間隔を調整してください。')
    return c


def validate_design(c, design):
    if design is None:
        return
    d = design['input']
    if d['positive_material'] != 'NMC811_demo' or d['electrolyte_fill'] != 1:
        raise ValueError('現在の物理アダプタはNMC811・孔隙充填率1の設計のみ対応しています。LFP/NCAは物性接続未検証です。')
    if c['parameter_set'] == 'Chen2020':
        if d['negative_si'] != 0 or d['negative_graphite'] <= 0:
            raise ValueError('Chen2020には黒鉛単相の設計を指定してください。')
    elif d['negative_si'] <= 0 or d['negative_graphite'] <= 0 or d['negative_additive'] != 'Si_demo':
        raise ValueError('Chen2020_compositeには黒鉛＋Siの設計を指定してください。SiOxは未検証です。')
    number(design['capacity']['c_rate_reference_ah'], '設計のCレート基準容量', .1, 100)
    for key in ['positive_porosity', 'negative_porosity', 'separator_porosity']:
        number(d[key], key, .05, .8)
    for key in ['positive_thickness_um', 'negative_thickness_um']:
        number(d[key], key, 5, 300)
    for key in ['positive', 'negative']:
        active = sum(p['solid_volume_fraction'] for p in design[key]['components'] if
                     p['id'] not in {'binder_demo', 'carbon_demo'})
        if not 0 < active <= 1:
            raise ValueError('電極活物質の体積分率を確認してください。')
