"""Validated JSON contract for isolated electrochemical workers (stdlib only)."""
import math
from copy import deepcopy

from .capabilities import CONFIG_SCHEMA_VERSION, SOLVER, compatibility, validate_options
from .protocol import validate_protocol

PHYSICS_VERSION = '1.3.0'
DIAGNOSTICS = {
    'surface_ocv_v': ('Surface open-circuit voltage [V]', '表面濃度に基づくOCV', 'V'),
    'reaction_overpotential_v': ('X-averaged reaction overpotential [V]', '反応過電圧（符号付き）', 'V'),
    'electrolyte_ohmic_loss_v': ('X-averaged electrolyte ohmic losses [V]', '電解液オーム損失（符号付き）', 'V'),
    'concentration_overpotential_v': ('X-averaged concentration overpotential [V]', '電解液濃度過電圧（符号付き）', 'V'),
    'solid_ohmic_loss_v': ('X-averaged solid phase ohmic losses [V]', '固相オーム損失（符号付き）', 'V'),
    'ohmic_heating_w': ('Ohmic heating [W]', 'オーム発熱', 'W'),
    'reaction_heating_w': ('Irreversible electrochemical heating [W]', '不可逆反応発熱', 'W'),
    'reversible_heating_w': ('Reversible heating [W]', '可逆反応熱', 'W'),
    'hysteresis_heating_w': ('Hysteresis electrochemical heating [W]', 'ヒステリシス発熱', 'W'),
    'mixing_heating_w': ('Heat of mixing [W]', '混合熱（現設定は無効）', 'W'),
    'total_heating_w': ('Total heating [W]', '全発熱', 'W'),
}
DEFAULTS = dict(config_schema_version=CONFIG_SCHEMA_VERSION, solver=SOLVER, model_options={},
                name='SPMe · 基準プロトコル', model='SPMe', parameter_set='Chen2020',
                thermal='isothermal', initial_soc=.5, initial_temp_c=25, ambient_temp_c=25,
                heat_transfer_w_m2_k=10, min_voltage_v=2.5, max_voltage_v=4.2,
                dt_s=5, mesh='normal', rtol=1e-6, atol=1e-6, timeout_s=120,
                design_id=None, cycles=1, start_time=None, protocol=[dict(kind='cc', current_a=1, duration_s=30),
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
    if not isinstance(version, str) or version not in {'1.0', CONFIG_SCHEMA_VERSION}:
        raise ValueError('未対応の計算設定スキーマ版です。条件を対応版で確認してください。')
    migrated = deepcopy(data)
    migrated['config_schema_version'] = CONFIG_SCHEMA_VERSION
    return migrated


def validate_request(data):
    data = migrate_request(data)
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('物理計算の入力項目を確認してください。')
    c = deepcopy(DEFAULTS);
    c.update(deepcopy(data))
    if not isinstance(c['name'], str) or not c['name'].strip() or len(c['name']) > 100:
        raise ValueError('計算名は1〜100文字で指定してください。')
    verdict = compatibility(c)
    if not verdict['compatible']:
        raise ValueError(verdict['reason'])
    validate_options(c)
    if not isinstance(c['mesh'], str) or c['mesh'] not in MESHES:
        raise ValueError('meshは検証済みの選択肢を指定してください。')
    for key, bounds in dict(initial_soc=(0, 1), initial_temp_c=(0, 45), ambient_temp_c=(0, 45),
                            heat_transfer_w_m2_k=(0, 100), min_voltage_v=(2, 4), max_voltage_v=(2.5, 4.3),
                            dt_s=(.1, 60), rtol=(1e-8, 1e-3), atol=(1e-8, 1e-3), timeout_s=(5, 300)).items():
        number(c[key], key, *bounds)
    if c['min_voltage_v'] >= c['max_voltage_v']:
        raise ValueError('下限電圧は上限電圧より小さくしてください。')
    if c['design_id'] is not None and (not isinstance(c['design_id'], str) or len(c['design_id']) > 100):
        raise ValueError('保存済み設計IDを指定してください。')
    validate_protocol(c, number)
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
