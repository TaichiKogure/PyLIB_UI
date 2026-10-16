"""Live worker integration and numerical repeatability, isolated test database."""
import argparse
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylibstudy.physics import DEFAULTS
from pylibstudy.jobs import PhysicsJobs, TERMINAL
from pylibstudy.service import export_csv
from pylibstudy.storage import RunRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/step03'))
    args = parser.parse_args();
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'Live isolated PyBaMM workers; not measured-cell accuracy validation', 'cases': {}}
    with tempfile.TemporaryDirectory(prefix='step3-', dir=Path('.test_tmp').resolve()) as directory:
        repo = RunRepository(Path(directory) / 'runs.sqlite3');
        jobs = PhysicsJobs(repo)
        report['environment'] = jobs.availability
        if not jobs.availability['available']: raise RuntimeError(jobs.availability)
        results = {}

        def case(name, changes=None, design=None, expect='completed'):
            c = copy.deepcopy(DEFAULTS);
            c.update(changes or {});
            c['name'] = name
            if design: c['design_id'] = design['id']
            job = jobs.submit(c)
            end = time.monotonic() + 140
            while time.monotonic() < end:
                current = jobs.get(job['id'], 'default')
                if current['status'] in TERMINAL: break
                time.sleep(.1)
            else:
                raise AssertionError('integration wait limit')
            assert current['status'] == expect, (name, current)
            if expect in {'completed', 'partial'}:
                r = repo.get(job['result_id']);
                assert r
                assert b'time_s,voltage_v,current_a' in export_csv(r)
                results[name] = r
                report['cases'][name] = {'status': current['status'], 'summary': r['summary'],
                                         'steps': r['step_results'], 'numerical': r['numerical'],
                                         'design_id': r['design_snapshot']['id'] if r.get('design_snapshot') else None}
                (args.output / (name + '.json')).write_text(json.dumps(r, ensure_ascii=False, indent=2),
                                                            encoding='utf-8')
            else:
                assert repo.get(job['result_id']) is None
                report['cases'][name] = {'status': current['status'], 'error_code': current.get('error_code'),
                                         'error_type': current.get('error_type')}
            print(name + ': ' + current['status'], flush=True)

        try:
            for mesh in ['coarse', 'normal', 'fine']: case('spme_' + mesh, {'mesh': mesh})
            case('spme_repeat')
            case('spme_tight', {'rtol': 1e-7, 'atol': 1e-7})
            case('dfn_normal', {'model': 'DFN'})
            case('thermal', {'thermal': 'lumped', 'initial_temp_c': 30, 'ambient_temp_c': 25})
            case('composite', {'model': 'DFN', 'parameter_set': 'Chen2020_composite'})
            case('cv', {'protocol': [dict(kind='cv', voltage_v=3.8, duration_s=60, stop_current_a=.1)]})
            case('cccv', {'protocol': [dict(kind='cc', current_a=-1, duration_s=3600, stop_voltage_v=4),
                                       dict(kind='cv', voltage_v=4, duration_s=300, stop_current_a=.1)]})
            case('profile',
                 {'protocol': [dict(kind='profile', points=[[0, 1], [30, 1], [31, 0], [40, 0], [41, -1], [70, -1]])]})
            design = repo.save_design({'input': {}})
            case('designed_spme', {}, design)
            case('designed_dfn', {'model': 'DFN'}, design)
            composite = repo.save_design({'input': dict(negative_graphite=.86, negative_si=.1)})
            case('designed_composite', {'model': 'DFN', 'parameter_set': 'Chen2020_composite'}, composite)
            case('initially_infeasible',
                 {'protocol': [dict(kind='cc', current_a=1, duration_s=30, stop_voltage_v=4.1)]}, expect='failed')
            base = results['spme_normal']
            for name in ['spme_coarse', 'spme_fine', 'spme_tight', 'spme_repeat', 'dfn_normal']:
                a = results[name]['points'];
                b = base['points'];
                assert len(a) == len(b)
                delta = max(abs(x['voltage_v'] - y['voltage_v']) for x, y in zip(a, b))
                report['cases'][name]['max_voltage_difference_from_normal_v'] = delta
                report['cases'][name]['within_2mv_of_normal'] = delta < .002
                if name != 'spme_coarse':
                    assert delta < .002, (name, delta)
            assert report['cases']['spme_repeat']['max_voltage_difference_from_normal_v'] < 1e-10
            assert abs(base['summary']['capacity_ah'] - 1 / 60) < 1e-8
            assert abs(base['summary']['final_soc'] - .5) < 1e-8
            assert abs(results['cv']['summary']['final_voltage_v'] - 3.8) < 1e-5
            assert '[experiment]' in results['cccv']['step_results'][0]['termination']
            assert len(results['cccv']['step_results']) == 2
            assert results['thermal']['points'][-1]['temperature_c'] < 30
            # Signed analytical profile integral: 1 A*s net, 60 A*s absolute.
            assert abs(results['profile']['summary']['capacity_ah'] - 60 / 3600) < 1e-6
            assert abs(results['profile']['summary']['final_soc'] - (.5 - 1 / 18000)) < 1e-6
            assert results['designed_spme']['design_snapshot'] == results['designed_dfn']['design_snapshot']
            run_id = base['id'];
            saved_count = len(repo.list())
        finally:
            jobs.close()
        recovered = PhysicsJobs(RunRepository(repo.path))
        try:
            assert recovered.repository.get(run_id)['points'] == base['points']
            assert len(recovered.repository.list()) == saved_count
            report['restart_results_restored'] = True
        finally:
            recovered.close()
    report['passed'] = True
    (args.output / 'integration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('All live integration checks passed.', flush=True)


if __name__ == '__main__': main()
