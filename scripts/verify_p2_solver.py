"""P2 native solver/extraction, accounting and CSV roundtrip evidence."""
import copy
import csv
import io
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylibstudy.capabilities import COMBINATIONS
from pylibstudy.datasets import import_curve
from pylibstudy.jobs import PhysicsJobs, TERMINAL
from pylibstudy.result_catalog import DISTRIBUTIONS
from pylibstudy.result_analysis import compare, postprocess
from pylibstudy.service import export_csv, export_spatial_csv
from pylibstudy.storage import RunRepository


def main():
    output = Path('docs/evidence/p2');
    output.mkdir(parents=True, exist_ok=True)
    report = dict(scope='Pinned native solvers and result contracts; no target-cell measured validation', cases={})
    with tempfile.TemporaryDirectory(prefix='p2-', dir=Path('.test_tmp').resolve()) as tmp:
        repo = RunRepository(Path(tmp) / 'runs.sqlite3');
        jobs = PhysicsJobs(repo)

        def run(name, config, full=True):
            job = jobs.submit(dict(name=name, **config));
            end = time.monotonic() + 140
            while time.monotonic() < end:
                current = jobs.get(job['id'], 'default')
                if current['status'] in TERMINAL: break
                time.sleep(.05)
            assert current['status'] == 'completed', (name, current)
            r = repo.get(job['result_id']);
            assert r
            assert r['electrode_soh']['status'] == 'available', (name, r['electrode_soh'])
            assert abs(r['electrode_soh']['electrode_capacity_mismatch_ah']) < 1e-4
            assert abs(r['lithium_balance']['relative_change']) < 1e-5
            if full:
                assert r['performance']['balance_checks']['voltage']['passed'], (name, r['performance'])
                assert r['performance']['balance_checks']['heat']['passed'], (name, r['performance'])
            assert r['citation_export']['status'] == 'available' and '@' in r['citation_export']['bibtex']
            assert max(abs(p['positive_3e_v'] - p['negative_3e_v'] - p['voltage_v']) for p in r['points']) < 1e-5
            for key, v in r['distributions']['variables'].items():
                if v['status'] != 'available': continue
                assert v['coordinate_unit'] == 'm' and v['dimensions'] == 1
                assert len(v['coordinates']) <= r['input']['output']['max_nodes']
                assert len(v['frames']) <= r['input']['output']['frames']
                assert all(b > a for a, b in zip(v['coordinates'], v['coordinates'][1:]))
                for f in v['frames']:
                    assert len(f['values']) == len(v['coordinates'])
                    assert r['points'][f['point_index']]['time_s'] == f['time_s']
            text = export_csv(r).decode('utf-8-sig')
            header = next(i for i, line in enumerate(text.splitlines(), 1) if line.startswith('time_s,'))
            imported, raw = import_curve(dict(text=text, header_row=header, source_type='simulation_import',
                                              source='Generated from solver ' + r['id'], mapping={
                    'time_s': {'column': 'time_s', 'unit': 's'}, 'voltage_v': {'column': 'voltage_v', 'unit': 'V'},
                    'current_a': {'column': 'current_a', 'unit': 'A'},
                    'step': {'column': 'segment_id', 'unit': '—'}}))
            assert len(imported['points']) == len(r['points'])
            assert imported['points'][-1]['voltage_v'] == r['points'][-1]['voltage_v']
            spatial = export_spatial_csv(r).decode('utf-8-sig')
            spatial_rows = list(csv.DictReader(
                io.StringIO('\n'.join(line for line in spatial.splitlines() if not line.startswith('#')))))
            assert all(float(p['coordinate_value']) >= 0 and p['coordinate_unit'] == 'm' for p in spatial_rows)
            report['cases'][name] = dict(status=current['status'], electrode_soh=r['electrode_soh'],
                                         performance=r['performance'],
                                         spatial_shapes={k: v.get('shape') for k, v in
                                                         r['distributions']['variables'].items() if
                                                         v['status'] == 'available'},
                                         unavailable={k: v['reason'] for k, v in r['result_variables'].items() if
                                                      v['status'] == 'unavailable'},
                                         citation_keys=r['citation_export']['keys'], csv_rows=len(imported['points']),
                                         spatial_csv_rows=len(spatial_rows))
            Path('.test_tmp/p2-results').mkdir(parents=True, exist_ok=True)
            Path('.test_tmp/p2-results', name + '.json').write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
            print(name + ': completed', flush=True)
            return r

        try:
            assert jobs.availability['available'];
            report['environment'] = jobs.availability
            for combo in COMBINATIONS:
                r = run('_'.join([combo['model'], combo['parameter_set'], combo['thermal']]),
                        dict(combo, protocol=[dict(kind='cc', current_a=1, duration_s=30)],
                             output={'distributions': list(DISTRIBUTIONS), 'frames': 7, 'max_nodes': 12}))
                native = [v for v in r['distributions']['variables'].values() if v['status'] == 'available']
                assert len(native) >= 7
            for model, params in [('SPM', 'Chen2020'), ('SPMe', 'Chen2020'), ('DFN', 'Chen2020_composite')]:
                r = run(model + '_ocv_' + params, dict(model=model, parameter_set=params, initial_ocv_v=3.8,
                                                       protocol=[dict(kind='rest', duration_s=5)]))
                assert abs(r['points'][0]['bulk_ocv_v'] - 3.8) < 1e-4
                assert abs(r['initial_state']['ledger_initial_soc'] - .5) > .001
            r = run('nested_pulses', dict(model='SPMe', protocol=[dict(kind='rest', duration_s=30),
                                                                  dict(kind='repeat', count=2, steps=[
                                                                      dict(kind='cc', current_a=1, duration_s=60),
                                                                      dict(kind='rest', duration_s=30)])]))
            analysis = postprocess(r, {'smoothing_window': 3, 'pulse_delay_s': 10})
            assert analysis['derivatives'] and any(p['resistance_ohm'] is not None for p in analysis['pulses']) and \
                   analysis['gitt']
            sparse = run('sparse_output', dict(model='SPM', output={
                'variables': ['surface_ocv_v', 'positive_3e_v', 'negative_3e_v', 'reference_potential_v'],
                'distributions': []}), full=False)
            assert sparse['result_variables']['total_heating_w']['status'] == 'not_selected'
            assert all('total_heating_w' not in p for p in sparse['points'])
            # Explicit missing/unselected check on an actual model.
            base = json.loads(Path('.test_tmp/p2-results/SPM_Chen2020_isothermal.json').read_text(encoding='utf-8'))
            assert base['result_variables']['negative_secondary_stoichiometry']['status'] == 'unavailable'
            assert all(p['negative_secondary_stoichiometry'] is None for p in base['points'])
            measured = copy.deepcopy(base);
            measured.update(id='derived-fixture', record_type='dataset', source_type='synthetic_demo',
                            source='Solver plus constant 0.01 V, generated verification fixture')
            for p in measured['points']: p['voltage_v'] += .01
            residual = compare(base, measured, {})
            assert abs(residual['metrics']['rmse'] - .01) < 1e-10
            report['known_residual'] = residual['metrics'];
            report['postprocess_counts'] = {k: len(analysis[k]) for k in ['derivatives', 'pulses', 'gitt']}
        finally:
            jobs.close()
        loaded = RunRepository(repo.path)
        assert loaded.get(base['id'])['distributions'] == base['distributions']
    report['passed'] = True
    (output / 'solver-integration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                                    encoding='utf-8')
    print('All P2 solver checks passed.', flush=True)


if __name__ == '__main__': main()
