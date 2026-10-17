"""Data-only material contract. No uploaded Python, imports or expression evaluation."""
import hashlib
import json
import math
import ast
from copy import deepcopy
from pathlib import Path

SETS = {
    'Chen2020': dict(label='NMC811 / 黒鉛', capacity=5., voltage=[2.5, 4.2]),
    'Chen2020_composite': dict(label='NMC811 / 黒鉛＋Si', capacity=5., voltage=[2.5, 4.2]),
    'Prada2013': dict(label='LFP / 黒鉛', capacity=2.3, voltage=[2., 3.6]),
    'NCA_Kim2011': dict(label='NCA / 黒鉛', capacity=.43, voltage=[2.7, 4.2]),
    'Xu2019': dict(label='LCO / Li金属（正極半セル）', capacity=.0024, voltage=[3.5, 4.2]),
    'BPX': dict(label='BPX独自物性（DFN・等温・単相）', capacity=None, voltage=[2.7, 4.2]),
}
MATERIAL_DEFAULTS = dict(particle='Fickian diffusion', transport='Bruggeman',
                         silicon_ocp='current sigmoid', diffusivity='single', exchange_current='single',
                         overrides={}, source='', bpx=None, bpx_original_text=None)
CHOICES = dict(particle=['Fickian diffusion', 'uniform profile', 'quadratic profile', 'quartic profile'],
               transport=['Bruggeman', 'tortuosity factor', 'ordered packing', 'hyperbola of revolution',
                          'overlapping spheres', 'random overlapping cylinders', 'heterogeneous catalyst',
                          'cation-exchange membrane'],
               silicon_ocp=['current sigmoid', 'one-state hysteresis', 'one-state differential capacity hysteresis'],
               diffusivity=['single', 'current sigmoid'], exchange_current=['single', 'current sigmoid'])


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def snapshot():
    return json.loads((Path(__file__).parent / 'data/material_parameters.v1.json').read_text(encoding='utf-8'))


def allowed_parameters(name):
    keys = set(snapshot()['sets']['Chen2020' if name == 'BPX' else name]['parameters'])
    for prefix in (['', 'Primary: ', 'Secondary: '] if name == 'Chen2020_composite' else ['']):
        for side in ('Negative', 'Positive'):
            keys.update(prefix + k for k in (
                f'{side} particle lithiation diffusivity [m2.s-1]',
                f'{side} particle delithiation diffusivity [m2.s-1]',
                f'{side} electrode lithiation exchange-current density [A.m-2]',
                f'{side} electrode delithiation exchange-current density [A.m-2]',
                f'{side} particle lithiation hysteresis decay rate',
                f'{side} particle delithiation hysteresis decay rate',
                f'{side} particle hysteresis decay rate', f'{side} particle hysteresis switching factor',
                f'Initial hysteresis state in {side.lower()} electrode'))
    for side in ('Negative', 'Positive', 'Separator'):
        keys.add(
            f'{side} electrode tortuosity factor (electrolyte)' if side != 'Separator' else 'Separator tortuosity factor (electrolyte)')
        if side != 'Separator': keys.add(f'{side} electrode tortuosity factor (electrode)')
    return keys - {'citations', 'chemistry', 'Current function [A]', 'Initial temperature [K]',
                   'Ambient temperature [K]', 'Lower voltage cut-off [V]', 'Upper voltage cut-off [V]',
                   'Contact resistance [Ohm]', 'Cell heat capacity [J.K-1.m-3]'}


def validate_material(c, number):
    raw = c['material_settings']
    if not isinstance(raw, dict) or set(raw) - set(MATERIAL_DEFAULTS): raise ValueError(
        '材料設定の項目を確認してください。')
    s = deepcopy(MATERIAL_DEFAULTS);
    s.update(deepcopy(raw));
    c['material_settings'] = s
    for key, choices in CHOICES.items():
        if not isinstance(s[key], str) or s[key] not in choices: raise ValueError(f'{key}: 未対応の材料設定です。')
    if c['parameter_set'] != 'Chen2020_composite' and s['silicon_ocp'] != 'current sigmoid':
        raise ValueError('Siヒステリシス設定はChen2020_composite専用です。')
    if not isinstance(s['source'], str) or len(s['source']) > 2000: raise ValueError('材料の出典は2000文字以内です。')
    overrides = s['overrides']
    if not isinstance(overrides, dict) or len(overrides) > 100: raise ValueError(
        '物性差分は100項目以内のオブジェクトです。')
    if (overrides or s['bpx'] is not None) and not s['source'].strip(): raise ValueError(
        '独自物性・BPXには出典・仮定を記入してください。')
    allowed = allowed_parameters(c['parameter_set'])
    for key, value in overrides.items():
        if key not in allowed: raise ValueError(f'{key}: 編集対象外の物性です。')
        if isinstance(value, dict):
            if set(value) != {'kind', 'points'} or value['kind'] != 'ocp_table' or 'OCP [V]' not in key:
                raise ValueError('補間曲線はOCPのkind=ocp_table, points=[[sto,V],...]で指定してください。')
            points = value['points']
            if not isinstance(points, list) or not 3 <= len(points) <= 1000: raise ValueError('OCP曲線は3〜1000点です。')
            previous = -1
            for row in points:
                if not isinstance(row, list) or len(row) != 2: raise ValueError('OCP曲線はsto,Vの2列です。')
                number(row[0], 'OCP化学量論', 0, 1);
                number(row[1], 'OCP電位', -1, 6)
                if row[0] <= previous: raise ValueError('OCPの化学量論は厳密な昇順です。')
                previous = row[0]
            if points[0][0] != 0 or points[-1][0] != 1: raise ValueError(
                'OCP曲線は0〜1全域が必要です。範囲外は外挿しません。')
        else:
            number(value, key, -1e9, 1e9)
            if 'hysteresis state' in key:
                number(value, key, -1, 1)
            elif 'OCP' in key or 'entropic' in key:
                pass
            elif 'porosity' in key or 'volume fraction' in key:
                number(value, key, .000001, .999999)
            elif 'concentration' in key or 'capacity' in key or 'thickness' in key or 'diffusivity' in key or 'radius' in key or 'tortuosity' in key:
                if value <= 0: raise ValueError(f'{key}: 正の値が必要です。')
            elif any(token in key for token in
                     ('conductivity', 'density', 'specific heat', 'decay rate', 'switching factor', 'Volume [',
                      'volume [', 'area [', 'width [', 'height [')):
                if value <= 0: raise ValueError(f'{key}: 正の値が必要です。')
    base = snapshot()['sets'].get(c['parameter_set'], {}).get('parameters', {})

    def effective(key):
        return overrides.get(key, base.get(key, {}).get('value'))

    for side in ('Negative', 'Positive'):
        porosity = effective(f'{side} electrode porosity')
        phases = ['Primary: ', 'Secondary: '] if c[
                                                     'parameter_set'] == 'Chen2020_composite' and side == 'Negative' else [
            '']
        active = [effective(prefix + side + ' electrode active material volume fraction') for prefix in phases]
        if isinstance(porosity, (int, float)) and all(isinstance(v, (int, float)) for v in active):
            if porosity + sum(active) > 1 + 1e-9: raise ValueError(
                f'{side}: 空隙率と活物質体積分率の合計が1を超えています。')
    if s['bpx'] is not None:
        # The optional native parser is called only inside the isolated worker.
        if not isinstance(s['bpx'], dict) or len(json.dumps(s['bpx'], allow_nan=False)) > 500000:
            raise ValueError('BPXは500KB以内のJSONオブジェクトです。')
        if c['parameter_set'] != 'BPX': raise ValueError(
            'BPX入力時は物性セットをBPXにしてください。文献セットへ無言で混合しません。')
        if not (Path(__file__).parents[1] / 'vendor/bpx/bpx').is_dir(): raise ValueError(
            'BPX追加依存がありません。setup-bpx.ps1で独立依存を準備してください。')
        validate_bpx(s['bpx'], number)
        if s['bpx_original_text'] is not None:
            text = s['bpx_original_text']
            if not isinstance(text, str) or len(text.encode('utf-8')) > 500000: raise ValueError(
                'BPX原本は500KB以内のUTF-8 JSONです。')
            try:
                original = json.loads(text)
            except ValueError:
                raise ValueError('BPX原本のJSONを確認してください。') from None
            if original != s['bpx']: raise ValueError('BPX原本と解析データが一致しません。')
    elif c['parameter_set'] == 'BPX':
        raise ValueError('BPXファイルを読み込んでください。')
    elif s['bpx_original_text'] is not None:
        raise ValueError('BPX原本にはBPXデータが必要です。')
    if c['parameter_set'] == 'BPX' and (
            c['model'] != 'DFN' or c['thermal'] != 'isothermal' or c['design_id']): raise ValueError(
        'BPXはDFN・等温・文献基準形状のみ対応です。')
    if c['parameter_set'] == 'Xu2019':
        if c['model'] != 'DFN' or c['thermal'] != 'isothermal': raise ValueError(
            '半セルはXu2019・DFN・等温のみ対応です。')
        if c['reference_electrode_fraction'] is not None: raise ValueError(
            '半セルでは参照電極位置を空欄にしてください。')
        if c['design_id']: raise ValueError('半セルと円筒全セル設計は接続しません。')
    available = set(snapshot()['sets'].get(c['parameter_set'], {}).get('parameters', {})) | set(overrides)
    required = set()
    if s['transport'] == 'tortuosity factor':
        required.add('Separator tortuosity factor (electrolyte)')
        for side in (['Positive'] if c['parameter_set'] == 'Xu2019' else ['Negative', 'Positive']):
            for phase in ('electrolyte', 'electrode'): required.add(f'{side} electrode tortuosity factor ({phase})')
    for setting, descriptor in [('diffusivity', 'particle {}diffusivity [m2.s-1]'),
                                ('exchange_current', 'electrode {}exchange-current density [A.m-2]')]:
        if s[setting] != 'current sigmoid': continue
        for side in (['Positive'] if c['parameter_set'] == 'Xu2019' else ['Negative', 'Positive']):
            for prefix in (
            ['Primary: ', 'Secondary: '] if side == 'Negative' and c['parameter_set'] == 'Chen2020_composite' else [
                '']):
                for direction in ('lithiation ', 'delithiation '): required.add(
                    prefix + side + ' ' + descriptor.format(direction))
    if c['parameter_set'] == 'Chen2020_composite' and s['silicon_ocp'] != 'current sigmoid':
        required.add('Secondary: Initial hysteresis state in negative electrode')
        if s['silicon_ocp'] == 'one-state hysteresis':
            for direction in ('lithiation ', 'delithiation '): required.add(
                'Secondary: Negative particle ' + direction + 'hysteresis decay rate')
        else:
            required.update(['Secondary: Negative particle hysteresis decay rate',
                             'Secondary: Negative particle hysteresis switching factor'])
    missing = required - available
    if missing: raise ValueError('選択した材料モデルの必須物性が不足しています: ' + ', '.join(sorted(missing)))


def material_options(c):
    s = c.get('material_settings') or MATERIAL_DEFAULTS
    result = {'particle': s.get('particle', 'Fickian diffusion'), 'particle shape': 'spherical',
              'transport efficiency': s.get('transport', 'Bruggeman'),
              'diffusivity': s.get('diffusivity', 'single'),
              'exchange-current density': s.get('exchange_current', 'single'),
              'working electrode': 'positive' if c['parameter_set'] == 'Xu2019' else 'both'}
    if c['parameter_set'] == 'Chen2020_composite':
        result['open-circuit potential'] = (('single', s.get('silicon_ocp', 'current sigmoid')), 'single')
    return result


def catalog():
    bpx_available = (Path(__file__).parents[1] / 'vendor/bpx/bpx').is_dir()
    return dict(sets=deepcopy(SETS), defaults=deepcopy(MATERIAL_DEFAULTS), choices=CHOICES,
                inventory=snapshot(), bpx=dict(available=bpx_available,
                                               reason='独立固定依存のBPX 1.1.1。DFN・単相・等温。数式は制限付き算術式として解釈します。' if bpx_available else 'BPX依存がありません。setup-bpx.ps1を実行してください。'),
                note='文献セット・独自差分は対象セルに未校正。関数は同梱の信頼済み物性を使用し、任意コードは実行しません。')


def expression_tree(expression):
    if len(expression) > 5000: raise ValueError('BPX数式が長すぎます。')
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError):
        raise ValueError('BPX数式の構文を確認してください。') from None
    nodes = list(ast.walk(tree))
    if len(nodes) > 1000: raise ValueError('BPX数式が複雑すぎます。')
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd,
               ast.Name, ast.Load, ast.Constant, ast.Call)
    for node in nodes:
        if not isinstance(node, allowed): raise ValueError('BPX数式はxと数値、四則・累乗・exp/tanh/coshに限定します。')
        if isinstance(node, ast.Name) and node.id not in {'x', 'exp', 'tanh', 'cosh'}: raise ValueError(
            'BPX数式に未対応の識別子があります。')
        if isinstance(node, ast.Constant) and (
                type(node.value) not in (int, float) or not math.isfinite(node.value) or abs(
            node.value) > 1e20): raise ValueError('BPX数式の定数を確認してください。')
        if isinstance(node, ast.Call) and (
                not isinstance(node.func, ast.Name) or node.func.id not in {'exp', 'tanh', 'cosh'} or len(
            node.args) != 1 or node.keywords): raise ValueError('BPX数式の関数呼出しを確認してください。')
    return tree


def validate_bpx(obj, number):
    if not isinstance(obj.get('Header'), dict) or obj['Header'].get('Model') != 'DFN': raise ValueError(
        'BPXはHeader.Model=DFNの完全物性を指定してください。')
    body = obj.get('Parameterisation')
    if not isinstance(body, dict) or not {'Cell', 'Electrolyte', 'Positive electrode', 'Negative electrode',
                                          'Separator'} <= set(body): raise ValueError(
        'BPXのセル・電極・電解液・セパレータ物性が不足しています。')
    if any(not isinstance(body[key], dict) for key in
           ('Cell', 'Electrolyte', 'Positive electrode', 'Negative electrode', 'Separator')): raise ValueError(
        'BPXの各材料セクションはオブジェクトです。')
    if any('Particle' in body[side] for side in ('Negative electrode', 'Positive electrode')): raise ValueError(
        'BPX複合相は未検証です。単相の完全物性を使用してください。')
    number(body['Cell'].get('Nominal cell capacity [A.h]'), 'BPX定格容量', .00001, 1000)

    def walk(value, depth=0):
        if depth > 12: raise ValueError('BPXの階層が深すぎます。')
        if isinstance(value, str):
            expression_tree(value)
        elif isinstance(value, dict):
            if set(value) == {'x', 'y'}:
                x, y = value['x'], value['y']
                if not isinstance(x, list) or not isinstance(y, list) or len(x) != len(y) or not 3 <= len(
                    x) <= 1000: raise ValueError('BPX補間表の長さを確認してください。')
                for a, b in zip(x, y): number(a, 'BPX x', -1e9, 1e9);number(b, 'BPX y', -1e9, 1e9)
                if any(a >= b for a, b in zip(x, x[1:])): raise ValueError('BPX補間表は厳密な昇順です。')
            else:
                for child in value.values(): walk(child, depth + 1)
        elif isinstance(value, list):
            if len(value) > 1000: raise ValueError('BPX配列が長すぎます。')
            for child in value: walk(child, depth + 1)
        elif value is not None:
            number(value, 'BPX数値', -1e20, 1e20)

    walk(body)
    if 'State' in obj: walk(obj['State'])
