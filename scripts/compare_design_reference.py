"""Optional source-method PoC, isolated from runtime; requires research NumPy.

Pass a local source folder obtained from the pinned official repository. This
executes only explicitly named numerical methods, not the package or its imports.
No upstream implementation is bundled with PyLIB. See docs/07 for limitations.
"""
import ast
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
import warnings

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylib_ui.design import evaluate_design, templates

COMMIT = '53178ecab1b9dc539bdc37e69ca7e86527142081'
EXPECTED = {
    'Electrodes.py': '17b85416295004258bea7ae82a880ae2df0f9d61080830e3c9d304bea1d6f568',
    'Formulations.py': '481cf4e7af36d79ef36f51293f11a9d596c2b448543c1c2caa1b5ee3d8e5427b',
    'SpiralUtils.py': '917baa0f5961c084defa20bec269b29f151afc0a94e44c7f542ae3c81f8ff968',
}


def method(folder, file, name):
    raw = (folder / file).read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED[file]:
        raise ValueError('Reference hash mismatch: ' + file)
    tree = ast.parse(raw)
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise ValueError('Reference method is not unique: ' + name)
    node = matches[0]
    node.decorator_list = []
    mod = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node],
                     type_ignores=[])
    ast.fix_missing_locations(mod)
    scope = dict(np=np, TWO_PI=2 * math.pi, G_TO_KG=.001, CM_TO_M=.01, UM_TO_M=1e-6,
                 warnings=warnings)
    exec(compile(mod, str(folder / file), 'exec'), scope)
    return scope[name]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true',
                        help='Fetch the three pinned official source files into source-dir')
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/step02/opencell-poc.json'))
    args = parser.parse_args()
    if args.fetch:
        from urllib.request import urlopen
        args.source_dir.mkdir(parents=True, exist_ok=True)
        root = 'https://raw.githubusercontent.com/stanford-developers/steer-opencell-design/' + COMMIT + '/'
        for file, path in [('Electrodes.py', 'Components/'), ('Formulations.py', 'Materials/'),
                           ('SpiralUtils.py', 'Constructions/ElectrodeAssemblies/')]:
            with urlopen(root + 'steer_opencell_design/' + path + file, timeout=30) as response:
                raw = response.read(2 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != EXPECTED[file]:
                raise ValueError('Downloaded source hash mismatch: ' + file)
            (args.source_dir / file).write_bytes(raw)
    density = method(args.source_dir, 'Formulations.py', '_calculate_density')
    capacity = method(args.source_dir, 'Formulations.py', '_calculate_capacity_curve')
    loading = method(args.source_dir, 'Electrodes.py', '_calculate_mass_loading')
    thickness = method(args.source_dir, 'Electrodes.py', '_calculate_thickness_properties')
    spiral = method(args.source_dir, 'SpiralUtils.py', 'calculate_simple_spiral')
    cases = []
    for label, template in templates().items():
        r = evaluate_design(template)
        errors = {}
        for side in ['positive', 'negative']:
            e = r[side]
            constituents = [(NS(_density=r['materials'][p['id']]['density_g_cm3'] * 1000), p['mass_fraction']) for p in
                            e['components']]
            formulation = NS(_iter_all_materials=lambda: iter(constituents))
            rho, _ = density(formulation)
            obj = NS()
            porosity = template[side + '_porosity']
            loading(obj, rho / 1000 * (1 - porosity), template[side + '_thickness_um'])
            errors[side + '_loading_mg_cm2_abs'] = abs(obj._mass_loading * 100 - e['mass_loading_mg_cm2'])
            obj._coating_thickness = template[side + '_thickness_um'] * 1e-6
            obj._current_collector = NS(_coated_area=e['area_cm2'] / 10000,
                                        _thickness=template[side + '_foil_um'] * 1e-6)
            obj._porosity = porosity
            obj._calender_density = rho * (1 - porosity)
            obj._mass_loading = obj._calender_density * obj._coating_thickness
            obj._formulation = NS(_density=rho)
            obj._insulation_thickness = 0
            thickness(obj)
            errors[side + '_volume_cm3_abs'] = abs(obj._coating_volume * 1e6 - e['coating_volume_cm3'])
            errors[side + '_total_thickness_um_abs'] = abs(
                obj._thickness * 1e6 - (2 * template[side + '_thickness_um'] + template[side + '_foil_um']))
            obj._formulation._specific_capacity_curve = np.array([[0, 0, 1], [e['specific_capacity_mah_g'], 1, 1]])
            obj._formulation._mass = e['dry_mass_g'] / 1000  # OpenCell internal kg, mAh/g == Ah/kg
            reference_capacity = capacity(obj._formulation)[-1, 0]
            errors[side + '_capacity_ah_abs'] = abs(reference_capacity - e['capacity_ah'])
        g = r['geometry']
        # Compare a centre-line spiral over the same radius interval. Our annular
        # model neglects the radial component of arc length, so small drift is expected.
        curve = spiral(n_turns=g['turns'], start_radius=g['inner_radius_mm'] / 1000,
                       thickness=g['pitch_mm'] / 1000, points_per_turn=1000)
        relative_length_difference = float(curve[-1, 1] * 1000 / g['length_mm'] - 1)
        cases.append(dict(template=label, scalar_absolute_errors=errors,
                          annular_length_mm=g['length_mm'], spiral_length_mm=float(curve[-1, 1] * 1000),
                          spiral_length_relative_difference=relative_length_difference,
                          scalar_pass=max(errors.values()) < 1e-9,
                          geometry_within_0_1_percent=abs(relative_length_difference) < .001))
    report = dict(commit=COMMIT, checked_at=datetime.now(timezone.utc).isoformat(),
                  method='AST-extracted numerical methods with minimal input objects; not full OpenCell package integration',
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                 args.source_dir.glob('*.py')},
                  upstream_license='AGPL-3.0-or-later source notices; independent runtime implementation retained',
                  cases=cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not all(c['scalar_pass'] and c['geometry_within_0_1_percent'] for c in cases):
        raise SystemExit('Comparison outside tolerance; inspect evidence')
    print(json.dumps(cases, indent=2))


if __name__ == '__main__':
    main()
