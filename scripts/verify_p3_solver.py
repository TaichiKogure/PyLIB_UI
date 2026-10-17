"""P3 native worker, thermal limits, provenance and conservation checks."""
import argparse
import copy
import json
import math
import tempfile
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pylibstudy.capabilities import COMBINATIONS as ALL_COMBINATIONS

COMBINATIONS = tuple(c for c in ALL_COMBINATIONS if c['parameter_set'] in {'Chen2020', 'Chen2020_composite'})
from pylibstudy.design import evaluate_design
from pylibstudy.jobs import PhysicsJobs, TERMINAL
from pylibstudy.service import export_csv
from pylibstudy.storage import RunRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/p3'))
    args = parser.parse_args();
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(
        scope='Pinned native worker and numerical thermal checks; synthetic assumptions, no target-cell measured validation',
        cases={})
    with tempfile.TemporaryDirectory(prefix='p3-', dir=Path('.test_tmp').resolve()) as folder:
        repo = RunRepository(Path(folder) / 'runs.sqlite3');
        jobs = PhysicsJobs(repo)

        def run(name, changes):
            config = dict(name=name, thermal='lumped', dt_s=1, protocol=[dict(kind='cc', current_a=3, duration_s=120)])
            config.update(copy.deepcopy(changes))
            job = jobs.submit(config);
            end = time.monotonic() + 160
            while time.monotonic() < end:
                current = jobs.get(job['id'], 'default')
                if current['status'] in TERMINAL: break
                time.sleep(.05)
            assert current['status'] == 'completed', (name, current)
            r = repo.get(job['result_id']);
            assert r
            assert abs(r['lithium_balance']['relative_change']) < 1e-5
            if r['input']['thermal'] == 'lumped': assert r['thermal_balance']['passed'], (name, r['thermal_balance'])
            for check in r['performance']['balance_checks'].values():
                if check['status'] == 'available': assert check['passed'], (name, check)
            report['cases'][name] = dict(input=r['input'], summary=r['summary'],
                                         thermal_provenance=r['thermal_provenance'],
                                         thermal_balance=r['thermal_balance'],
                                         balances=r['performance']['balance_checks'])
            (args.output / 'solver-integration.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            assert json.loads(json.dumps(r, allow_nan=False)) == r
            assert RunRepository(repo.path).get(r['id']) == r
            print(name + ': completed', flush=True)
            return r

        try:
            assert jobs.availability['available'], jobs.availability
            report['environment'] = jobs.availability
            explicit = dict(capacity_mode='user', cell_heat_capacity_j_k=50,
                            source='synthetic thermal verification; not measured')
            for combo in COMBINATIONS:
                changes = dict(combo, protocol=[dict(kind='cc', current_a=1, duration_s=20)])
                if combo['thermal'] == 'lumped' and combo['parameter_set'] == 'Chen2020_composite': changes[
                    'thermal_settings'] = explicit
                run('_'.join([combo[k] for k in ('model', 'parameter_set', 'thermal')]), changes)
            base = run('adiabatic_50', dict(heat_transfer_w_m2_k=0, thermal_settings=explicit))
            double = run('adiabatic_100',
                         dict(heat_transfer_w_m2_k=0, thermal_settings=dict(explicit, cell_heat_capacity_j_k=100)))
            assert base['summary']['max_temperature_c'] > double['summary']['max_temperature_c'] > 25
            for r in (base, double):
                b = r['thermal_balance'];
                cap = r['thermal_provenance']['cell_heat_capacity_initial_j_k']
                assert abs(cap * (r['points'][-1]['temperature_c'] - r['points'][0]['temperature_c']) - b[
                    'electrochemical_heat_j']) < b['tolerance_j']
            cooled = run('cooled', dict(heat_transfer_w_m2_k=100, thermal_settings=explicit))
            assert cooled['summary']['max_temperature_c'] < base['summary']['max_temperature_c']
            contact = run('contact',
                          dict(heat_transfer_w_m2_k=0, thermal_settings=dict(explicit, contact_resistance_ohm=.01)))
            assert abs(contact['thermal_balance']['contact_heat_j'] - 3 ** 2 * .01 * 120) < 1e-5
            for p in contact['points']:
                assert abs(p['contact_heating_w'] - p['current_a'] ** 2 * .01) < 1e-9
                assert abs(p['contact_voltage_loss_v'] + p['current_a'] * .01) < 1e-9
                assert abs(
                    p['positive_3e_v'] - p['negative_3e_v'] + p['contact_voltage_loss_v'] - p['voltage_v']) < 1e-5
            assert contact['summary']['max_temperature_c'] > base['summary']['max_temperature_c']
            charge = run('contact_charge', dict(thermal_settings=dict(explicit, contact_resistance_ohm=.01),
                                                protocol=[dict(kind='cc', current_a=-2, duration_s=30)]))
            assert abs(charge['thermal_balance']['contact_heat_j'] - 1.2) < 1e-5
            assert all(
                abs(p['contact_voltage_loss_v'] - .02) < 1e-8 and abs(p['contact_heating_w'] - .04) < 1e-8 for p in
                charge['points'])
            rest = run('analytic_cooling',
                       dict(initial_temp_c=35, heat_transfer_w_m2_k=30, rtol=1e-8, atol=1e-8, thermal_settings=explicit,
                            protocol=[dict(kind='rest', duration_s=120)]))
            area = rest['thermal_provenance']['cooling_area_m2']
            expected = 25 + 10 * math.exp(-30 * area * 120 / 50)
            assert abs(rest['points'][-1]['temperature_c'] - expected) < .002, (expected, rest['summary'])
            assert abs(rest['initial_state']['actual_temperature_c'] - 35) < 1e-8
            first = run('first_step_ambient', dict(initial_temp_c=35, heat_transfer_w_m2_k=30, rtol=1e-8, atol=1e-8,
                                                   thermal_settings=explicit,
                                                   protocol=[dict(kind='rest', duration_s=60, temperature_c=20)]))
            expected = 20 + 15 * math.exp(-30 * area * 60 / 50)
            assert abs(first['points'][-1]['temperature_c'] - expected) < .002
            two = run('two_node', dict(
                thermal_settings=dict(explicit, surface_temperature='lumped', casing_heat_capacity_j_k=5,
                                      environment_thermal_resistance_k_w=2)))
            assert two['points'][-1]['temperature_c'] > two['points'][-1]['surface_temperature_c'] > 25
            limit = run('isothermal_limit', dict(heat_transfer_w_m2_k=10000, thermal_settings=explicit,
                                                 protocol=[dict(kind='cc', current_a=1, duration_s=30)]))
            iso = run('isothermal_reference',
                      dict(thermal='isothermal', protocol=[dict(kind='cc', current_a=1, duration_s=30)]))
            assert abs(limit['points'][-1]['temperature_c'] - 25) < .01
            assert abs(limit['points'][-1]['voltage_v'] - iso['points'][-1]['voltage_v']) < .0002
            for model in ('SPM', 'SPMe', 'DFN'):
                r = run(model + '_mixing', dict(model=model, thermal_settings=dict(heat_of_mixing=True),
                                                protocol=[dict(kind='cc', current_a=3, duration_s=30)]))
                assert r['model_options']['heat of mixing'] == 'true'
                assert any(abs(p['mixing_heating_w']) > 1e-10 for p in r['points'])
            off = run('isothermal_heat_off',
                      dict(thermal='isothermal', thermal_settings=dict(isothermal_heat_source=False)))
            assert all(p['total_heating_w'] is None for p in off['points'])
            assert off['result_variables']['total_heating_w']['status'] == 'unavailable'
            for kind in ('cp', 'cr'):
                step = dict(kind=kind, control='explicit', duration_s=20,
                            **({'power_w': 3} if kind == 'cp' else {'resistance_ohm': 4}))
                run('contact_' + kind,
                    dict(thermal_settings=dict(explicit, contact_resistance_ohm=.01), protocol=[step]))
            step = run('ambient_step', dict(thermal_settings=explicit,
                                            protocol=[dict(kind='rest', duration_s=20, temperature_c=20),
                                                      dict(kind='rest', duration_s=20, temperature_c=30)]))
            assert abs(step['points'][0]['surface_temperature_c'] - 20) < 1e-8
            assert abs(step['points'][-1]['surface_temperature_c'] - 30) < 1e-8
            for composite in (False, True):
                design = evaluate_design(dict(negative_graphite=.86, negative_si=.1) if composite else {})
                saved = repo.save_design(dict(input=design['input']))
                r = run('saved_design_' + str(composite), dict(model='DFN' if composite else 'SPMe',
                                                               parameter_set='Chen2020_composite' if composite else 'Chen2020',
                                                               design_id=saved['id'], thermal_settings=explicit))
                assert r['thermal_provenance']['cell_heat_capacity_initial_j_k'] == 50
                assert r['thermal_provenance']['geometry_basis']['volume'] == 'saved_design_dimensions'
                assert 'density' not in ' '.join(r['thermal_provenance']['parameter_overrides']).lower()
            override = run('explicit_geometry',
                           dict(thermal_settings=dict(explicit, cooling_area_m2=.005, cell_volume_m3=.00002)))
            assert override['parameter_provenance']['overrides']['Cell heat capacity [J.K-1.m-3]'] == 2500000
            assert 'contact_heating_w' in export_csv(contact).decode('utf-8-sig')
            comparison = repo.save_comparison(
                dict(dataset_ids=[base['id'], contact['id']], variable='total_heat_with_contact_w', x_axis='time_s'))
            assert comparison['variable'] == 'total_heat_with_contact_w'
            (args.output / 'browser-native-run.json').write_text(json.dumps(two, ensure_ascii=False, indent=2),
                                                                 encoding='utf-8')
            report['passed'] = True
        finally:
            jobs.close()
    (args.output / 'solver-integration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                                         encoding='utf-8')


if __name__ == '__main__': main()
