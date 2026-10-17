"""Analytical P2 checks: derivatives, pulse/GITT indices, gaps and residuals."""
import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

import test_simulation
from pylibstudy.result_analysis import postprocess, compare, balance_summary
from pylibstudy.physics import validate_request
from pylibstudy.result_catalog import DEFAULT_OUTPUT
from pylibstudy.storage import RunRepository
from pylibstudy.service import export_csv
from pylibstudy.datasets import import_curve


def record(points, **extra):
    return dict(id='known', project_id='default', name='Analytical fixture', record_type='physics',
                source_type='simulation', points=points, **extra)


class AnalysisTests(unittest.TestCase):
    def test_linear_derivatives_and_full_window_smoothing(self):
        points = [dict(segment_id=0, time_s=i, capacity_ah=i * .01, voltage_v=4 - .002 * i, current_a=1) for i in
                  range(15)]
        for window in (1, 3, 5):
            r = postprocess(record(points), {'smoothing_window': window})
            self.assertEqual(len(r['derivatives']), 15 - window - 1)
            for p in r['derivatives']:
                self.assertAlmostEqual(p['dq_dv_ah_v'], -5, places=10)
                self.assertAlmostEqual(p['dv_dq_v_ah'], -.2, places=10)
        points[7]['voltage_v'] = None
        r = postprocess(record(points), {'smoothing_window': 1})
        self.assertEqual(len({p['group'] for p in r['derivatives']}), 2)
        self.assertFalse(any(p['time_s'] == 7 for p in r['derivatives']))
        for p in points: p['voltage_v'] = 4
        self.assertTrue(
            all(p['dq_dv_ah_v'] is None for p in postprocess(record(points), {'smoothing_window': 1})['derivatives']))

    def test_pulse_resistance_and_missing_window(self):
        points = [dict(time_s=t, voltage_v=4 if t <= 20 else 3.95, current_a=0 if t <= 20 else 1,
                       capacity_ah=max(0, t - 20) / 3600, segment_id=0 if t <= 20 else 1) for t in
                  (0, 10, 20, 20.00001, 30, 40, 50)]
        r = postprocess(record(points), {'pulse_delay_s': 10})
        self.assertAlmostEqual(r['pulses'][0]['resistance_ohm'], .05)
        points[4]['voltage_v'] = None
        self.assertIsNone(postprocess(record(points), {'pulse_delay_s': 10})['pulses'][0]['resistance_ohm'])

    def test_boundary_roundoff_and_partial_balance_are_explicit(self):
        points = []
        for segment, start, current in [(0, 0, 0), (1, 30.000000000000004, 1), (2, 90.00000000000001, 0)]:
            duration = 60 if current else 30
            for delta in range(0, duration + 1, 5):
                points.append(dict(time_s=start + delta, current_a=current, voltage_v=4 - .001 * delta - .05 * current,
                                   capacity_ah=delta / 3600, segment_id=segment))
        self.assertEqual(len(postprocess(record(points), {})['gitt']), 1)
        for p in points:
            p.update(surface_ocv_v=4, voltage_v=4, reaction_overpotential_v=0, electrolyte_ohmic_loss_v=0,
                     concentration_overpotential_v=0, solid_ohmic_loss_v=0)
        points[-1]['solid_ohmic_loss_v'] = None
        check = balance_summary(points)['balance_checks']['voltage']
        self.assertEqual(check['status'], 'unavailable');
        self.assertIsNone(check['passed'])

    def test_gitt_indices_are_not_diffusion_coefficients(self):
        points = []
        for t in range(0, 111, 10):
            if t <= 30:
                current, voltage, segment = 0, 4, 0
            elif t <= 70:
                current, voltage, segment = 1, 3.9 - .01 * math.sqrt(t - 40), 1
            else:
                current, voltage, segment = 0, 3.98 + (t - 80) / 30 * .01, 2
            points.append(dict(time_s=t, current_a=current, voltage_v=voltage, segment_id=segment,
                               capacity_ah=max(0, t - 30) / 3600))
        r = postprocess(record(points), {})
        self.assertEqual(len(r['gitt']), 1)
        self.assertAlmostEqual(r['gitt'][0]['sqrt_time_slope_v_sqrt_s'], -.01)
        self.assertNotIn('diffusivity', json.dumps(r))
        self.assertEqual(postprocess(record(points[2:]), {})['gitt'], [])

    def test_charge_energy_accounting_and_unavailable_efficiency(self):
        points = [dict(time_s=0, voltage_v=4, current_a=-1, segment_id=0, soc=.5),
                  dict(time_s=3600, voltage_v=4, current_a=-1, segment_id=0, soc=.7),
                  dict(time_s=3600.0001, voltage_v=4, current_a=1, segment_id=1, soc=.7),
                  dict(time_s=7200.0001, voltage_v=4, current_a=1, segment_id=1, soc=.5)]
        r = balance_summary(points, .5)
        for k in ('charge_ah', 'discharge_ah'): self.assertAlmostEqual(r[k], 1)
        for k in ('charge_wh', 'discharge_wh'): self.assertAlmostEqual(r[k], 4)
        self.assertAlmostEqual(r['energy_efficiency'], 1)
        self.assertIsNone(balance_summary(points[:2], .5)['energy_efficiency'])
        crossing = [dict(time_s=0, current_a=-1, voltage_v=4, segment_id=0),
                    dict(time_s=3600, current_a=1, voltage_v=4, segment_id=0)]
        r = balance_summary(crossing)
        self.assertAlmostEqual(r['charge_ah'], .25);
        self.assertAlmostEqual(r['discharge_wh'], 1)

    def test_known_residual_with_explicit_offset_and_no_extrapolation(self):
        a = record(
            [dict(time_s=i, voltage_v=4 - .01 * i, current_a=1, temperature_c=25, segment_id=0) for i in range(11)])
        b = record(
            [dict(time_s=i, voltage_v=4 - .01 * (i + 2) + .005, current_a=1, temperature_c=None, segment_id=0) for i in
             range(11)])
        b.update(id='measured', record_type='dataset', source_type='user_measured', original={'sha256': 'fixture'},
                 temperature_position='surface')
        before = copy.deepcopy(b)
        r = compare(a, b, {'time_offset_s': 2})
        self.assertEqual(b, before)
        self.assertEqual(r['metrics']['count'], 9);
        self.assertEqual(r['excluded']['outside_overlap'], 2)
        self.assertAlmostEqual(r['metrics']['rmse'], .005);
        self.assertAlmostEqual(r['metrics']['bias'], -.005)
        self.assertEqual(r['conditions']['temperature_c']['status'], 'unknown')
        self.assertEqual(r['conditions']['temperature_basis']['status'], 'review_required')
        b['points'][3]['time_s'] = 2
        with self.assertRaises(ValueError): compare(a, b, {})

    def test_comparison_never_bridges_missing_simulation_row(self):
        a = record([dict(time_s=0, voltage_v=4, segment_id=0), dict(time_s=1, voltage_v=None, segment_id=0),
                    dict(time_s=2, voltage_v=3.8, segment_id=0)])
        b = record([dict(time_s=0, voltage_v=4, segment_id=0), dict(time_s=.5, voltage_v=4, segment_id=0),
                    dict(time_s=2, voltage_v=3.8, segment_id=0)])
        b['record_type'] = 'dataset'
        r = compare(a, b, {})
        self.assertEqual(r['excluded']['missing'], 1);
        self.assertEqual(r['metrics']['count'], 2)
        self.assertNotEqual(r['rows'][0]['group'], r['rows'][1]['group'])

    def test_output_schema_and_invalid_analysis_conditions(self):
        for output in [[], {'variables': ['code']}, {'variables': ['bulk_ocv_v', 'bulk_ocv_v']}, {'frames': 1000},
                       {'max_nodes': True}]:
            with self.assertRaises(ValueError): validate_request({'output': output})
        for changes in [{'initial_ocv_v': True}, {'reference_electrode_fraction': 0}, {'initial_ocv_v': 4.5}]:
            with self.assertRaises(ValueError): validate_request(changes)
        self.assertEqual(validate_request({'config_schema_version': '1.1'})['config_schema_version'], '1.2')
        self.assertEqual(validate_request({})['output'], DEFAULT_OUTPUT)
        for settings in [{'smoothing_window': 2}, {'pulse_delay_s': float('nan')}, {'rest_min_s': 0}]:
            with self.assertRaises(ValueError): postprocess(record([]), settings)


class AnalysisHttpTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_persist_reload_export_and_project_isolation(self):
        run = json.loads(Path('docs/evidence/step03/spme_normal.json').read_text(encoding='utf-8'))
        repo = self.server.service.repository
        repo.save(run)
        with self.request('/api/analysis/postprocess',
                          {'run_id': run['id'], 'config': {'smoothing_window': 1}}) as response:
            r = json.load(response)
        self.assertEqual(RunRepository(repo.path).analysis(r['id'], 'default'), r)
        with self.request('/api/analyses/' + r['id'] + '.json') as response: self.assertEqual(json.load(response), r)
        with self.request('/api/analyses/' + r['id'] + '.csv') as response: self.assertIn(b'dq_dv_ah_v',
                                                                                          response.read())
        with self.request('/api/analyses') as response: self.assertEqual(len(json.load(response)), 1)
        project = repo.create_project('other')['id']
        for path, data in [('/api/analysis/postprocess', {'run_id': run['id'], 'project_id': project}),
                           ('/api/analyses/' + r['id'] + '?project_id=' + project, None)]:
            with self.assertRaises(HTTPError) as error: self.request(path, data)
            self.assertEqual(error.exception.code, 400);
            error.exception.close()
        # Legacy source remains immutable, including its missing P2 fields.
        self.assertEqual(repo.get(run['id']), run)

    def test_scalar_csv_roundtrip_and_result_catalog(self):
        run = json.loads(Path('docs/evidence/step03/spme_normal.json').read_text(encoding='utf-8'))
        text = export_csv(run).decode('utf-8-sig')
        header = next(i for i, line in enumerate(text.splitlines(), 1) if line.startswith('time_s,'))
        curve, _ = import_curve(
            dict(text=text, header_row=header, source_type='simulation_import', source='Exported run ' + run['id'],
                 name='Roundtrip', mapping={
                    'time_s': {'column': 'time_s', 'unit': 's'}, 'voltage_v': {'column': 'voltage_v', 'unit': 'V'},
                    'current_a': {'column': 'current_a', 'unit': 'A'},
                    'step': {'column': 'segment_id', 'unit': '—'}}))
        self.assertEqual(len(curve['points']), len(run['points']))
        self.assertAlmostEqual(curve['points'][-1]['voltage_v'], run['points'][-1]['voltage_v'])
        with self.request('/api/result-catalog') as response:
            catalog = json.load(response)
        self.assertEqual(len(catalog['core']), 7);
        self.assertTrue(catalog['distributions'])


if __name__ == '__main__': unittest.main()
