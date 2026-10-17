"""P1 live solver, protocol and callback checks with isolated persistent jobs."""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylibstudy.capabilities import COMBINATIONS, CONFIG_SCHEMA_VERSION
from pylibstudy.jobs import PhysicsJobs, TERMINAL
from pylibstudy.protocol import protocol_templates
from pylibstudy.storage import RunRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/p1'))
    parser.add_argument('--section', choices=['all', 'protocols', 'composite', 'terminations'], default='all')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(scope='Live fixed PyBaMM P1 integration; no measured-cell validation', cases={})
    with tempfile.TemporaryDirectory(prefix='p1-', dir=Path('.test_tmp').resolve()) as directory:
        repo = RunRepository(Path(directory) / 'runs.sqlite3')
        jobs = PhysicsJobs(repo)

        def run(name, config, expected='completed'):
            job = jobs.submit(dict(name=name, **config))
            deadline = time.monotonic() + config.get('timeout_s', 120) + 15
            while time.monotonic() < deadline:
                current = jobs.get(job['id'], 'default')
                if current['status'] in TERMINAL: break
                time.sleep(.05)
            assert current['status'] == expected, (name, current,
                                                   Path(directory) / 'physics-jobs' / job['id'] / 'worker.log')
            print(name + ': ' + current['status'], flush=True)
            r = repo.get(job['result_id'])
            report['cases'][name] = dict(status=current['status'], progress=current.get('progress'))
            if r:
                diagnostic = Path('.test_tmp/p1-solver-results')
                diagnostic.mkdir(parents=True, exist_ok=True)
                (diagnostic / (name + '.json')).write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
                report['cases'][name].update(summary=r['summary'], step_results=r['step_results'],
                                             lithium_balance=r['lithium_balance'], model_options=r['model_options'])
                assert r['input']['config_schema_version'] == CONFIG_SCHEMA_VERSION
                assert r['progress_events'][-1]['event'] == 'postprocess'
                assert current['progress']['completed_steps'] == len(
                    [s for s in r['step_results'] if s['status'] != 'not_run'])
            else:
                assert expected in {'failed', 'timeout', 'cancelled'}
            return r

        try:
            assert jobs.availability['available'], jobs.availability
            report['environment'] = jobs.availability
            for combo in COMBINATIONS if args.section == 'all' else []:
                name = '_'.join([combo['model'], combo['parameter_set'], combo['thermal']])
                r = run(name, dict(combo, protocol=[dict(kind='c_rate', c_rate=.2, duration_s=20)]))
                assert all(abs(p['current_a'] - 1) < 1e-5 for p in r['points'])
                assert abs(r['summary']['capacity_ah'] - 20 / 3600) < 1e-6

            controls = [(m, 'Chen2020') for m in ['SPM', 'SPMe', 'DFN']] + [('DFN', 'Chen2020_composite')]
            if args.section in ('protocols', 'terminations'): controls = []
            for mode in ['implicit', 'explicit', 'differential'] if args.section in ('all', 'terminations') else []:
                for kind, value in [('cp', dict(power_w=3.7)), ('cr', dict(resistance_ohm=4))]:
                    r = run(kind + '_' + mode + '_voltage_stop', dict(model='SPM', protocol=[
                        dict(kind=kind, control=mode, duration_s=600, stop_voltage_v=3.7, **value)]))
                    assert '[experiment]' in r['step_results'][0]['termination']
                    assert abs(r['points'][-1]['voltage_v'] - 3.7) < 1e-4

            if args.section == 'composite': controls = [('DFN', 'Chen2020_composite')]
            for model, parameter_set in controls:
                steps = [dict(kind='cc', current_a=-1, duration_s=10), dict(kind='c_rate', c_rate=.2, duration_s=10)]
                for mode in ['implicit', 'explicit', 'differential']:
                    for kind, value in [('cp', dict(power_w=3.7)), ('cr', dict(resistance_ohm=4))]:
                        steps.append(dict(kind=kind, duration_s=20, control=mode, period_s=2, **value))
                steps += [dict(kind='cp', power_w=-3.7, duration_s=10),
                          dict(kind='cr', resistance_ohm=-4, duration_s=10),
                          dict(kind='cv', voltage_v=3.8, stop_c_rate=.001, duration_s=5),
                          dict(kind='profile', points=[[0, 1], [5, -1], [10, 0]]), dict(kind='rest', duration_s=5)]
                r = run(model + ('_composite' if parameter_set.endswith('_composite') else '') + '_controls',
                        dict(model=model, parameter_set=parameter_set, protocol=steps, dt_s=2))
                for index, step in enumerate(steps):
                    values = [p for p in r['points'] if p['segment_id'] == index]
                    last = values[-1]
                    if step['kind'] == 'cp': assert abs(
                        last['voltage_v'] * last['current_a'] - step['power_w']) < .005, (model, index, step, last)
                    if step['kind'] == 'cr': assert abs(
                        last['voltage_v'] / last['current_a'] - step['resistance_ohm']) < .005, (model, index, step,
                                                                                                 last)
                    if step['kind'] == 'cv': assert abs(last['voltage_v'] - 3.8) < 1e-4
                    if step['kind'] == 'cc': assert last['current_a'] < 0
                assert r['model_options']['voltage as a state'] == 'true'

            if args.section in ('composite', 'terminations'):
                report['passed'] = True
                destination = args.output / 'solver-integration.json'
                if destination.exists():
                    previous = json.loads(destination.read_text(encoding='utf-8'))
                    previous['cases'].update(report['cases'])
                    report = previous
                destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                return

            for template in protocol_templates():
                r = run('template_' + template['id'], dict(model='SPM', protocol=template['protocol']))
                if template['id'] == 'cccv':
                    assert '[experiment]' in r['step_results'][0]['termination']
                    assert '[experiment]' in r['step_results'][1]['termination']
                    assert abs(r['points'][-1]['current_a']) < 1e-6

            nested = [dict(kind='repeat', count=2, steps=[dict(kind='repeat', count=2, steps=[
                dict(kind='c_rate', c_rate=.2, duration_s=2, period_s=1, tags=['pulse'], temperature_c=30),
                dict(kind='rest', duration_s=2, temperature_c=30)])])]
            r = run('nested_metadata',
                    dict(model='SPM', cycles=2, protocol=nested, start_time='2026-10-17T09:00:00+09:00'))
            assert len(r['step_results']) == 16
            assert len([e for e in r['progress_events'] if e['event'] == 'cycle_end']) == 2
            assert all(abs(p['temperature_c'] - 30) < 1e-5 for p in r['points'])
            assert abs(r['summary']['duration_s'] - 32) < 1e-5
            assert r['experiment_metadata']['initial_start_time'] == '2026-10-17T09:00:00+09:00'
            assert r['experiment_metadata']['periods_s'][0] == 1
            assert r['experiment_metadata']['tags'][0] == ['pulse']
            r = run('allowed_skip',
                    dict(protocol=[dict(kind='cc', current_a=1, duration_s=10, stop_voltage_v=4.1, skip_ok=True),
                                   dict(kind='rest', duration_s=5)]))
            assert r['step_results'][0]['status'] == 'skipped'
            assert r['step_results'][1]['status'] == 'completed'
            run('forbidden_skip', dict(protocol=[dict(kind='cc', current_a=1, duration_s=10, stop_voltage_v=4.1),
                                                 dict(kind='rest', duration_s=5)]), expected='failed')
            run('all_skipped',
                dict(protocol=[dict(kind='cc', current_a=1, duration_s=10, stop_voltage_v=4.1, skip_ok=True)]),
                expected='failed')
            r = run('design_rate', dict(model='SPM', design_id=repo.save_design({'input': {}})['id'],
                                        protocol=[dict(kind='c_rate', c_rate=.2, duration_s=10)]))
            assert abs(r['points'][0]['current_a'] - .2 * r['summary']['c_rate_reference_ah']) < 1e-6
            assert r['protocol_preview']['c_rate_reference_ah'] == r['summary']['c_rate_reference_ah']
        finally:
            jobs.close()
        loaded = RunRepository(repo.path)
        assert loaded.get(r['id'])['input'] == r['input']
    report['passed'] = True
    destination = args.output / 'solver-integration.json'
    if args.section != 'all' and destination.exists():
        previous = json.loads(destination.read_text(encoding='utf-8'))
        previous['cases'].update(report['cases'])
        report = previous
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('All P1 real solver checks passed.', flush=True)


if __name__ == '__main__': main()
