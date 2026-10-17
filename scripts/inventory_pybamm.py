"""Record public capability names from the installed, pinned PyBaMM (no solves)."""
import inspect
import json
import os
from pathlib import Path

os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
import pybamm


def inventory():
    families = {}
    for name in ('lithium_ion', 'lithium_metal', 'sodium_ion', 'lead_acid', 'equivalent_circuit'):
        module = getattr(pybamm, name, None)
        families[name] = [key for key, value in inspect.getmembers(module, inspect.isclass)
                          if issubclass(value, pybamm.BaseModel)] if module else []
    return {
        'pybamm_version': pybamm.__version__,
        'scope': 'Public exported model classes, BatteryModelOptions, parameter sets, solvers and step factories. Presence does not imply compatibility or a successful solve.',
        'models': families,
        'battery_options': pybamm.BatteryModelOptions({}).possible_options,
        'parameter_sets': sorted(pybamm.parameter_sets.keys()),
        'solvers': [name for name, obj in inspect.getmembers(pybamm, inspect.isclass)
                    if issubclass(obj, pybamm.BaseSolver)],
        'experiment_steps': [name for name, obj in inspect.getmembers(pybamm.step)
                             if not name.startswith('_') and (inspect.isclass(obj) or inspect.isfunction(obj))],
    }


if __name__ == '__main__':
    result = inventory()
    root = Path(__file__).resolve().parents[1] / 'docs' / 'evidence'
    root.mkdir(exist_ok=True)
    (root / 'pybamm_capabilities_26.10.1.0.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# PyBaMM固定環境の公開機能一覧（自動抽出）', '',
             f"版: `{result['pybamm_version']}`。取得日: 2026-10-16。計算実行・組合せ互換性の確認ではありません。",
             '', '再生成: `.\\.venv-research\\Scripts\\python.exe scripts/inventory_pybamm.py`', '']
    for family, names in result['models'].items():
        lines += [f'## {family}', '', ', '.join(f'`{n}`' for n in names), '']
    lines += ['## BatteryModelOptions 全項目', '', '|キー|候補値|', '|---|---|']
    for key, values in result['battery_options'].items():
        lines.append(f'|`{key}`|{", ".join(f"`{v}`" for v in values)}|')
    for key in ('parameter_sets', 'solvers', 'experiment_steps'):
        lines += ['', f'## {key}', '', ', '.join(f'`{n}`' for n in result[key]), '']
    (root / 'PyBaMM_固定版API全候補.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({key: len(value) for key, value in result.items()
                      if isinstance(value, (dict, list))}))
