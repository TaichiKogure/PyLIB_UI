"""Validated JSON contract for isolated electrochemical workers (stdlib only)."""
import math
from copy import deepcopy

from .capabilities import CONFIG_SCHEMA_VERSION, SOLVER, compatibility, validate_options
from .protocol import validate_protocol
from .result_catalog import DIAGNOSTICS, DEFAULT_OUTPUT, validate_output

from .thermal import THERMAL_DEFAULTS, validate_thermal
from .materials import MATERIAL_DEFAULTS, validate_material, SETS

PHYSICS_VERSION = '1.6.0'
DEFAULTS = dict(config_schema_version=CONFIG_SCHEMA_VERSION, solver=SOLVER, model_options={},
                name='SPMe · 基準プロトコル', model='SPMe', parameter_set='Chen2020',
                thermal='isothermal', material_settings=MATERIAL_DEFAULTS, thermal_settings=THERMAL_DEFAULTS,
                initial_soc=.5, initial_temp_c=25, ambient_temp_c=25,
                heat_transfer_w_m2_k=10, min_voltage_v=2.5, max_voltage_v=4.2,
                dt_s=5, mesh='normal', rtol=1e-6, atol=1e-6, timeout_s=120,
                design_id=None, cycles=1, start_time=None, initial_ocv_v=None, reference_electrode_fraction=.5,
                output=DEFAULT_OUTPUT, protocol=[dict(kind='cc', current_a=1, duration_s=30),
                                          dict(kind='rest', duration_s=10),
                                          dict(kind='cc', current_a=-1, duration_s=30)])
MESHES = {'coarse': (10, 10), 'normal': (20, 20), 'fine': (40, 40)}


def number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(
            value) or not low <= value <= high:
        raise ValueError(f'{label} は{low}〜{high}の有限値で指定してください。')
    return value


def migrate_request(data):
    """Missing version is the legacy contract; never rewrite a saved record."""
    if not isinstance(data, dict):
        raise ValueError('物理計算の入力はオブジェクトで指定してください。')
    version = data.get('config_schema_version', CONFIG_SCHEMA_VERSION)
    if not isinstance(version, str) or version not in {'1.0', '1.1', '1.2', '1.3', CONFIG_SCHEMA_VERSION}:
        raise ValueError('未対応の計算設定スキーマ版です。条件を対応版で確認してください。')
    migrated = deepcopy(data)
    parameter_set = migrated.get('parameter_set')
    if isinstance(parameter_set, str) and parameter_set in {'Prada2013', 'NCA_Kim2011', 'Xu2019', 'BPX'}:
        migrated.setdefault('min_voltage_v', SETS[parameter_set]['voltage'][0])
        migrated.setdefault('max_voltage_v', SETS[parameter_set]['voltage'][1])
    if isinstance(parameter_set, str) and parameter_set in {'Prada2013',
                                                            'Xu2019'} and 'thermal_settings' not in migrated:
        migrated['thermal_settings'] = dict(isothermal_heat_source=False)
    migrated['config_schema_version'] = CONFIG_SCHEMA_VERSION
    return migrated


def validate_request(data):
    data = migrate_request(data)
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('物理計算の入力項目を確認してください。')
    c = deepcopy(DEFAULTS);
    c.update(deepcopy(data))
    validate_thermal(c, number)
    if not isinstance(c['name'], str) or not c['name'].strip() or len(c['name']) > 100:
        raise ValueError('計算名は1〜100文字で指定してください。')
    verdict = compatibility(c)
    if not verdict['compatible']:
        raise ValueError(verdict['reason'])
    validate_material(c, number)
    if c['parameter_set'] in {'Prada2013', 'Xu2019'} and (
            c['thermal_settings']['isothermal_heat_source'] or c['thermal_settings']['heat_of_mixing']):
        raise ValueError('Prada2013/Xu2019は熱物性が不足しています。等温熱源・混合熱を無効にしてください。')
    validate_options(c)
    if not isinstance(c['mesh'], str) or c['mesh'] not in MESHES:
        raise ValueError('meshは検証済みの選択肢を指定してください。')
    for key, bounds in dict(initial_soc=(0, 1), initial_temp_c=(0, 45), ambient_temp_c=(0, 45),
                            heat_transfer_w_m2_k=(0, 10000), min_voltage_v=(1.5, 4), max_voltage_v=(2.5, 4.3),
                            dt_s=(.1, 60), rtol=(1e-8, 1e-3), atol=(1e-8, 1e-3), timeout_s=(5, 300)).items():
        number(c[key], key, *bounds)
    if c['min_voltage_v'] >= c['max_voltage_v']:
        raise ValueError('下限電圧は上限電圧より小さくしてください。')
    if c['design_id'] is not None and (not isinstance(c['design_id'], str) or len(c['design_id']) > 100):
        raise ValueError('保存済み設計IDを指定してください。')
    if c['initial_ocv_v'] is not None:
        number(c['initial_ocv_v'], '初期OCV', c['min_voltage_v'], c['max_voltage_v'])
    if c['reference_electrode_fraction'] is not None:
        number(c['reference_electrode_fraction'], '参照電極のセパレータ内相対位置', .05, .95)
    c['output'] = validate_output(c['output'])
    validate_protocol(c, number)
    return c

def validate_design(c, design):
    if design is None:
        return
    if c['parameter_set'] not in {'Chen2020', 'Chen2020_composite'} or c['material_settings']['overrides'] or \
            c['material_settings']['bpx'] is not None:
        raise ValueError(
            '独自物性・LFP/NCA・半セルには文献基準形状を使用してください。円筒設計写像はChen系の基準物性のみ対応です。')
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
