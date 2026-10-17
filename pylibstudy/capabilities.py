"""Stdlib-only registry shared by HTTP validation, UI catalog and solver workers."""
import json
import platform
import re
from copy import deepcopy
from pathlib import Path

from .thermal import thermal_options
from .materials import SETS, material_options
PINNED_PYBAMM = '26.10.1.0'
CONFIG_SCHEMA_VERSION = '1.4'
CATALOG_VERSION = '1.4'
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
) + tuple(dict(model='DFN', parameter_set='Chen2020_composite', thermal=thermal, solver=SOLVER)
          for thermal in ('isothermal', 'lumped')) + tuple(
    dict(model=m, parameter_set=p, thermal=t, solver=SOLVER)
    for p in ('Prada2013', 'NCA_Kim2011') for m in ('SPM', 'SPMe', 'DFN') for t in ('isothermal',)
) + tuple(dict(model='DFN', parameter_set=p, thermal='isothermal', solver=SOLVER) for p in ('Xu2019', 'BPX'))
CONNECTED_OPTIONS = {
    'particle': '球形粒子のFickian・一様・二次・四次近似。',
    'particle shape': '球形粒子のみ。no particlesは対象外。',
    'transport efficiency': '8種の輸送近似。tortuosity factorでは明示物性が必要。',
    'working electrode': '全セルまたはXu2019正極半セル。',
    'diffusivity': 'singleまたは方向別current sigmoid。方向別の必須物性を事前検出。',
    'exchange-current density': 'singleまたは方向別current sigmoid。方向別の必須物性を事前検出。',
    'thermal': '等温/集中熱。複合負極の集中熱は出典付きのセル熱容量が必須。',
    'calculate discharge energy': 'エネルギー出力用にtrue固定。',
    'calculate heat source for isothermal models': '等温の熱源計算を明示選択。無効時は未計算と表示。',
    'contact resistance': '明示したセル電気抵抗。端子電圧とI²R発熱へ接続。設計の接触率・ASRは転用しない。',
    'heat of mixing': '熱物性のある単相のみ。LFP/Xu半セルと複合負極は未対応。',
    'surface temperature': '周囲温度または外側集中熱ノード。後者は熱容量と環境熱抵抗が必須。',
    'use lumped thermal capacity': '文献層別熱容量または出典付きのセル熱容量J/K。体積で換算して渡す。',
    'particle phases': '文献物性セットに連動。Chen2020は単相、compositeは負極2相。',
    'open-circuit potential': '複合Siはcurrent sigmoid・1状態・微分容量ヒステリシス。追加物性必須。',
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
                    reason='選択した物性・モデル・熱の組合せは未接続です。複合負極はDFN、半セル/BPXはDFN等温、LFP/NCAは等温を使用してください。')
    if config['parameter_set'] == 'Chen2020_composite' and config['thermal'] == 'lumped':
        return dict(compatible=True,
                    reason='条件付き経路: 複合負極の集中熱には出典付きのセル熱容量(J/K)が必須。対象セルは実測未検証。')
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
    options.update(thermal_options(config))
    options.update(material_options(config))
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
                parameter_sets=[dict(id=name, connected=name in SETS,
                                     reason='登録済み組合せのみ使用可能。' if name in SETS else
                                     '物性・モデル・熱の組合せ検証とUI接続が未完了。') for name in
                                inventory['parameter_sets']],
                solvers=[dict(id=name, connected=name == SOLVER,
                              reason='登録済み実行ソルバ。' if name == SOLVER else '補助クラスまたは未接続のソルバ。')
                         for name in inventory['solvers']],
                protocol=dict(kinds=['cc', 'c_rate', 'cv', 'cp', 'cr', 'rest', 'profile', 'repeat'],
                              max_expanded_steps=200, max_cycles=20, max_repeat_depth=3),
                next_increment='P5: SEI・析出・LAM等の単独機構',
                limitation='API候補の存在・短時間ソルバ実行・数値収束・実測適合は別の検証です。対象18650/21700セルは実測未検証。')
