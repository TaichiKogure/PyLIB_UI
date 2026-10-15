"""Live pinned PyBaMM diagnostics and design changes, isolated persistence."""
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pylib_ui.design import evaluate_design
from pylib_ui.jobs import PhysicsJobs, TERMINAL
from pylib_ui.physics import DEFAULTS, DIAGNOSTICS
from pylib_ui.service import export_csv
from pylib_ui.storage import RunRepository


def main():
    output = ROOT / 'docs' / 'evidence' / 'design-analysis'
    output.mkdir(parents=True, exist_ok=True)
    report = dict(scope='Live PyBaMM functional diagnostics and design response; no measured-cell accuracy claim',
                  cases={})
    results = {}
    with tempfile.TemporaryDirectory(prefix='design-physics-', dir=ROOT / '.test_tmp') as directory:
        repo = RunRepository(Path(directory) / 'runs.sqlite3')
        jobs = PhysicsJobs(repo)
        report['environment'] = jobs.availability
        if not jobs.availability['available']:
            raise RuntimeError(jobs.availability)
        try:
            cases = [
                ('literature-spme', {}, None),
                ('literature-dfn', dict(model='DFN'), None),
                ('literature-dfn-lumped', dict(model='DFN', thermal='lumped'), None),
                ('literature-composite-dfn', dict(model='DFN', parameter_set='Chen2020_composite'), None),
                ('design-spme', {}, {}),
                ('design-dfn', dict(model='DFN'), {}),
                ('design-thicker-positive', {}, dict(positive_thickness_um=80)),
                ('design-higher-porosity', {}, dict(positive_porosity=.4)),
            ]
            for name, changes, design_input in cases:
                config = copy.deepcopy(DEFAULTS)
                config.update(changes)
                config.update(name=name, protocol=[dict(kind='cc', current_a=5, duration_s=10),
                                                   dict(kind='rest', duration_s=5),
                                                   dict(kind='cc', current_a=-5, duration_s=10)], dt_s=1)
                if design_input is not None:
                    saved = repo.save_design(dict(input=design_input))
                    config['design_id'] = saved['id']
                job = jobs.submit(config)
                end = time.monotonic() + 140
                while time.monotonic() < end:
                    state = jobs.get(job['id'], 'default')
                    if state['status'] in TERMINAL:
                        break
                    time.sleep(.1)
                if state['status'] != 'completed':
                    raise AssertionError((name, state))
                run = repo.get(job['result_id'])
                assert run['adapter_version'] == '1.1.0'
                assert run['model_options']['calculate heat source for isothermal models'] == 'true'
                assert set(run['diagnostic_summary']) == set(DIAGNOSTICS)
                for point in run['points']:
                    heat_sum = sum(
                        point[key] for key in ['ohmic_heating_w', 'reaction_heating_w', 'reversible_heating_w',
                                               'hysteresis_heating_w', 'mixing_heating_w'])
                    assert abs(heat_sum - point['total_heating_w']) < 1e-8
                    if config['thermal'] == 'isothermal':
                        assert abs(point['temperature_c'] - 25) < 1e-8
                assert max(point['ohmic_heating_w'] + point['reaction_heating_w'] for point in run['points']) > 0
                csv = export_csv(run)
                assert b'total_heating_w' in csv and b'reaction_overpotential_v' in csv
                report['cases'][name] = dict(status=state['status'], summary=run['summary'],
                                             diagnostics=run['diagnostic_summary'],
                                             overrides=run['parameter_provenance']['overrides'])
                (output / (name + '.json')).write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')
                results[name] = run
                print(name + ': completed', flush=True)
            assert abs(
                results['design-spme']['points'][0]['voltage_v'] - results['design-thicker-positive']['points'][0][
                    'voltage_v']) > 1e-6
            assert abs(
                results['design-spme']['points'][0]['voltage_v'] - results['design-higher-porosity']['points'][0][
                    'voltage_v']) > 1e-6
            # Store analytical examples separately, never as solver observations.
            analytical = {name: evaluate_design(changes) for name, changes in [
                ('21700', {}), ('18650', {'diameter_mm': 18, 'height_mm': 65, 'winding_width_mm': 59,
                                          'positive_width_mm': 55, 'negative_width_mm': 57}),
                ('si10-ice90', {'negative_graphite': .86, 'negative_si': .1, 'negative_first_cycle_efficiency': .9})]}
            (output / 'analytical-examples.json').write_text(json.dumps(analytical, ensure_ascii=False, indent=2),
                                                             encoding='utf-8')
            (output / 'physics-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                        encoding='utf-8')
            print('All 8 live cases passed; heat balance and design response verified.', flush=True)
        finally:
            jobs.close()


if __name__ == '__main__':
    main()
