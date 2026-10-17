"""P3 thermal input contract; explicit properties never come from design ledgers."""
from copy import deepcopy

THERMAL_DEFAULTS = dict(capacity_mode='literature', cell_heat_capacity_j_k=None,
                        surface_temperature='ambient', casing_heat_capacity_j_k=None,
                        environment_thermal_resistance_k_w=None, contact_resistance_ohm=0.,
                        cooling_area_m2=None, cell_volume_m3=None,
                        heat_of_mixing=False, isothermal_heat_source=True, source='')


def validate_thermal(config, number):
    supplied = config['thermal_settings']
    if not isinstance(supplied, dict) or set(supplied) - set(THERMAL_DEFAULTS):
        raise ValueError('熱設定の項目を確認してください。')
    t = deepcopy(THERMAL_DEFAULTS)
    t.update(deepcopy(supplied))
    if t['capacity_mode'] not in ('literature', 'user') or t['surface_temperature'] not in ('ambient', 'lumped'):
        raise ValueError('熱容量・表面温度モデルは登録済みの選択肢を指定してください。')
    for key in ('heat_of_mixing', 'isothermal_heat_source'):
        if not isinstance(t[key], bool): raise ValueError(f'{key}は真偽値で指定してください。')
    number(t['contact_resistance_ohm'], '電気的な接触抵抗 (Ω)', 0, .1)
    for key, low, high in [('cell_heat_capacity_j_k', .1, 10000), ('casing_heat_capacity_j_k', .1, 10000),
                           ('environment_thermal_resistance_k_w', .001, 10000),
                           ('cooling_area_m2', 1e-6, 1), ('cell_volume_m3', 1e-7, .01)]:
        if t[key] is not None: number(t[key], key, low, high)
    if not isinstance(t['source'], str) or len(t['source']) > 1000:
        raise ValueError('熱物性の出典・仮定は1000文字以内で指定してください。')
    t['source'] = t['source'].strip()
    if t['capacity_mode'] == 'user' and t['cell_heat_capacity_j_k'] is None:
        raise ValueError('セル全体の熱容量 (J/K) を明示してください。')
    if t['capacity_mode'] == 'literature' and t['cell_heat_capacity_j_k'] is not None:
        raise ValueError('文献熱容量モードでは独自のセル熱容量を指定できません。')
    if t['surface_temperature'] == 'lumped':
        if config['thermal'] != 'lumped': raise ValueError('表面の集中熱はセル集中熱と組み合わせてください。')
        if any(t[k] is None for k in ('casing_heat_capacity_j_k', 'environment_thermal_resistance_k_w')):
            raise ValueError('表面集中熱には外側ノードの熱容量と環境熱抵抗が必要です。')
    elif any(t[k] is not None for k in ('casing_heat_capacity_j_k', 'environment_thermal_resistance_k_w')):
        raise ValueError('周囲温度境界では外側ノードの熱容量・環境熱抵抗を指定できません。')
    if config['thermal'] == 'isothermal' and t['capacity_mode'] != 'literature':
        raise ValueError('セル熱容量の指定は集中熱モデルで使用します。')
    if config['parameter_set'] == 'Chen2020_composite':
        if config['thermal'] == 'lumped' and t['capacity_mode'] != 'user':
            raise ValueError(
                '複合負極の層別熱物性は不足しています。集中熱には出典付きのセル熱容量 (J/K) を明示してください。')
        if t['heat_of_mixing']:
            raise ValueError('固定版の混合熱は複合負極の相別変数に未対応です。単相Chen2020を選んでください。')
    if config['thermal'] == 'isothermal' and t['heat_of_mixing'] and not t['isothermal_heat_source']:
        raise ValueError('等温で混合熱を使うには等温熱源の計算を有効にしてください。')
    if (t['capacity_mode'] == 'user' or t['surface_temperature'] == 'lumped' or t['contact_resistance_ohm'] > 0
        or t['cooling_area_m2'] is not None or t['cell_volume_m3'] is not None) and not t['source']:
        raise ValueError('独自の熱容量・境界・接触抵抗には出典または仮定を記録してください。')
    config['thermal_settings'] = t
    return t


def thermal_options(config):
    t = {**THERMAL_DEFAULTS, **config.get('thermal_settings', {})}
    # Composite thermal densities are absent; an explicit capacity is mandatory for lumped.
    # Isothermal also avoids evaluating irrelevant, missing layer thermal properties.
    explicit = t['capacity_mode'] == 'user' or config['parameter_set'] == 'Chen2020_composite'
    return {'calculate heat source for isothermal models': str(t['isothermal_heat_source']).lower(),
            'contact resistance': str(t['contact_resistance_ohm'] > 0).lower(),
            'heat of mixing': str(t['heat_of_mixing']).lower(),
            'surface temperature': t['surface_temperature'],
            'use lumped thermal capacity': str(explicit).lower() if config['thermal'] == 'lumped' else 'false'}
