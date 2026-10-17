"""Stdlib-only registry shared by HTTP validation, UI catalog and solver workers."""
import json
import platform
import re
from copy import deepcopy
from pathlib import Path

PINNED_PYBAMM = '26.10.1.0'
CONFIG_SCHEMA_VERSION = '1.2'
CATALOG_VERSION = '1.2'
SOLVER = 'IDAKLUSolver'
SUPPORTED_OS = ('Windows',)
PHASE_DEPENDENCIES = {
    'P0': ['既存の設計・保存・ワーカー基盤'], 'P1': ['P0'], 'P2': ['P1'], 'P3': ['P2'],
    'P4': ['P3'], 'P5': ['P4'], 'P6': ['P4', 'P5の保存契約'], 'P7': ['P5', 'P6'],
    'P8': ['P3', 'P7'], 'P9': ['P7', '別物性スキーマ'], 'P10': ['P8', 'P9'],
}
COMBINATIONS = tuple(
    dict(model=model, parameter_set='Chen2020', thermal=thermal, solver=SOLVER)
    for model in ('SPM', 'SPMe', 'DFN') for thermal in ('isothermal', 'lumped')
) + (dict(model='DFN', parameter_set='Chen2020_composite', thermal='isothermal', solver=SOLVER),)
CONNECTED_OPTIONS = {
    'thermal': '温度モデルで選択。複合負極は等温のみ。',
    'calculate discharge energy': 'エネルギー出力用にtrue固定。',
    'calculate heat source for isothermal models': '熱源出力用にtrue固定。',
    'particle phases': '文献物性セットに連動。Chen2020は単相、compositeは負極2相。',
    'open-circuit potential': '文献物性セットに連動。compositeのSi相はcurrent sigmoid。',
    'operating mode': 'ExperimentステップでCC/C-rate/CV/CP/CRを構築。CP/CRは定義済みの代数・明示・微分制御。',
    'voltage as a state': '明示CP/CRを含む場合だけtrueに連動し、電圧と電流の循環参照を避けます。単独選択は未接続。',
}


def compatibility(config, os_name=None):
    """Pure, non-coercing check. Never repair a user's incompatible selection."""
    os_name = platform.system() if os_name is None else os_name
    if os_name not in SUPPORTED_OS:
        return dict(compatible=False, reason=f'{os_name}: このアダプタの実行確認対象はWindowsです。')
    for key in ('model', 'parameter_set', 'thermal', 'solver'):
        if not isinstance(config.get(key), str) or config[key] not in {c[key] for c in COMBINATIONS}:
            return dict(compatible=False, reason=f'{key}: 未接続の選択肢です。機能カタログを確認してください。')
    if not any(all(config[k] == c[k] for k in c) for c in COMBINATIONS):
        return dict(compatible=False,
                    reason='Chen2020_compositeはDFN・等温のみ対応。複合負極の集中熱用物性は未接続です。')
    return dict(compatible=True, reason='登録済みの計算経路です。対象セルの実測検証は未実施。')


def model_options(config):
    verdict = compatibility(config)
    if not verdict['compatible']:
        raise ValueError(verdict['reason'])
    options = {'thermal': config['thermal'], 'calculate discharge energy': 'true',
               'calculate heat source for isothermal models': 'true',
               'particle phases': '1', 'open-circuit potential': 'single',
               'operating mode': 'current', 'voltage as a state': 'false'}
    if config['parameter_set'] == 'Chen2020_composite':
        options.update({'particle phases': ('2', '1'),
                        'open-circuit potential': (('single', 'current sigmoid'), 'single')})

    def explicit_steps(nodes, depth=0):
        if not isinstance(nodes, list) or depth > 3: return False
        return any(isinstance(s, dict) and ((s.get('kind') in ('cp', 'cr') and s.get('control') == 'explicit') or
                                            (s.get('kind') == 'repeat' and explicit_steps(s.get('steps'), depth + 1)))
                   for s in nodes)

    if explicit_steps(config.get('protocol')):
        options['voltage as a state'] = 'true'
    return options


def validate_options(config):
    supplied = config['model_options']
    if not isinstance(supplied, dict):
        raise ValueError('model_optionsはオブジェクトで指定してください。')
    expected = json.loads(json.dumps(model_options(config)))
    for key, value in supplied.items():
        if key not in expected:
            raise ValueError(f'{key}: このモデル設定は未接続または対象外です。')
        if value != expected[key]:
            raise ValueError(f'{key}: 選択したモデル・物性・温度の登録値と一致しません。')


def build_model(pybamm, config):
    # Both entrypoints validate, even when called independently of HTTP.
    validate_options(config)
    constructors = {'SPM': pybamm.lithium_ion.SPM, 'SPMe': pybamm.lithium_ion.SPMe, 'DFN': pybamm.lithium_ion.DFN}
    return constructors[config['model']](options=model_options(config))


def build_solver(pybamm, config):
    verdict = compatibility(config)
    if not verdict['compatible']:
        raise ValueError(verdict['reason'])
    return pybamm.IDAKLUSolver(rtol=config['rtol'], atol=config['atol'], options={'num_threads': 1})


def catalog(environment):
    inventory = json.loads((Path(__file__).parent / 'data/pybamm_catalog.v1.json').read_text(encoding='utf-8'))
    options = []
    for key, values in inventory['battery_options'].items():
        status = 'executable' if key in CONNECTED_OPTIONS else 'out_of_scope' if key in {'convection',
                                                                                         'hydrolysis'} else 'unconnected'
        options.append(dict(key=key, candidates=values, status=status, phase=inventory['option_phases'][key],
                            reason=CONNECTED_OPTIONS.get(key,
                                                         '鉛蓄電池専用。現在のLIBアダプタ対象外。' if status == 'out_of_scope' else
                                                         'PyBaMM内の既定挙動は使用しますが、この設定の変更はUI/APIに未接続です。')))
    return dict(catalog_version=CATALOG_VERSION, config_schema_version=CONFIG_SCHEMA_VERSION,
                pybamm_version=PINNED_PYBAMM, environment=deepcopy(environment),
                os=dict(current=platform.system(), supported=list(SUPPORTED_OS)),
                combinations=[dict(c, **compatibility(c)) for c in COMBINATIONS],
                options=options, features=[dict(f, planned_dependencies=sorted({
            dependency for phase in re.findall(r'P\d+', f['phase'])
            for dependency in PHASE_DEPENDENCIES[phase]})) for f in inventory['features']],
                models=[
                    dict(family=family, id=name, connected=family == 'lithium_ion' and name in {'SPM', 'SPMe', 'DFN'})
                    for family, names in inventory['models'].items() for name in names],
                parameter_sets=[dict(id=name, connected=name in {'Chen2020', 'Chen2020_composite'},
                                     reason='登録済み組合せのみ使用可能。' if name in {'Chen2020',
                                                                                      'Chen2020_composite'} else
                                     '物性・モデル・熱の組合せ検証とUI接続が未完了。') for name in
                                inventory['parameter_sets']],
                solvers=[dict(id=name, connected=name == SOLVER,
                              reason='登録済み実行ソルバ。' if name == SOLVER else '補助クラスまたは未接続のソルバ。')
                         for name in inventory['solvers']],
                protocol=dict(kinds=['cc', 'c_rate', 'cv', 'cp', 'cr', 'rest', 'profile', 'repeat'],
                              max_expanded_steps=200, max_cycles=20, max_repeat_depth=3),
                next_increment='P3: 集中熱・冷却/熱容量/接触抵抗・発熱比較',
                limitation='API候補の存在・短時間ソルバ実行・数値収束・実測適合は別の検証です。対象18650/21700セルは実測未検証。')
