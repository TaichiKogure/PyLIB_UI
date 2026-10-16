"""Data integrity and independent conservation/cutoff checks for source curves."""
import csv
import json
import math
import tempfile
import unittest
from http.client import HTTPConnection
from io import StringIO
from pathlib import Path
from threading import Thread

from pylibstudy.cathodes import catalog, interpolate, simulate, validate
from pylibstudy.server import create_server
from pylibstudy.service import SimulationService, export_csv
from pylibstudy.storage import RunRepository

ROOT = Path(__file__).resolve().parents[1]


class CathodeDataTests(unittest.TestCase):
    def test_catalog_identities_kinds_and_domain(self):
        data = catalog()
        self.assertEqual(len(data['curves']), 8)
        self.assertEqual({x['chemistry'] for x in data['curves']},
                         {'NMC111', 'NMC523', 'NMC622', 'NMC811', 'LCO', 'LFP', 'LMFP'})
        for curve in data['curves']:
            with self.subTest(curve=curve['id']):
                self.assertTrue(curve['citation']['url'].startswith('https://'))
                self.assertTrue(curve['license'])
                for src in curve['sources']:
                    self.assertEqual(len(src['sha256']), 64)
                for b in curve['branches'].values():
                    self.assertEqual((b['points'][0][0], b['points'][-1][0]), (0, 1))
                    self.assertTrue(all(a[0] < z[0] for a, z in zip(b['points'], b['points'][1:])))
                    self.assertLessEqual(b['processing']['linear_simplification_max_error_v'], .0005)
                    self.assertTrue(all(math.isfinite(v) and 1.5 < v < 4.7 for x, v in b['points']))
        lmfp = next(c for c in data['curves'] if c['chemistry'] == 'LMFP')
        self.assertEqual(lmfp['composition'], 'LiMn0.6Fe0.4PO4')
        self.assertEqual((lmfp['temperature_c'], lmfp['specific_current_ma_g']), (70, 70))
        self.assertEqual(lmfp['kind'], 'vector_digitized')
        self.assertFalse(lmfp['branches']['charge']['processing']['instrument_raw'])

    def test_catalog_isolation(self):
        data = catalog()
        data['curves'][0]['branches']['charge']['points'][0][1] = 0
        self.assertGreater(catalog()['curves'][0]['branches']['charge']['points'][0][1], 2)

    def test_interpolation_rejects_extrapolation(self):
        points = [[0, 2], [1, 4]]
        self.assertEqual(interpolate(points, .25), 2.5)
        for x in [-.00001, 1.00001]:
            with self.assertRaises(ValueError):
                interpolate(points, x)

    def test_recorded_capacities_and_source_branches_retained(self):
        c = next(c for c in catalog()['curves'] if c['id'] == 'lco2018_bare_cycle3')
        self.assertEqual(c['branches']['charge']['specific_capacity_mah_g'], 212.636)
        self.assertEqual(c['branches']['discharge']['specific_capacity_mah_g'], 208.12849)
        self.assertNotEqual(c['branches']['charge']['specific_capacity_mah_g'],
                            c['branches']['discharge']['specific_capacity_mah_g'])

    def test_every_curve_both_directions_and_voltage_bases(self):
        for c in catalog()['curves']:
            for mode in ('charge', 'discharge'):
                for basis in ('vs_li', 'full_cell'):
                    with self.subTest(curve=c['id'], mode=mode, basis=basis):
                        r = simulate(dict(curve_id=c['id'], mode=mode, voltage_basis=basis,
                                          initial_soc=.05 if mode == 'charge' else .95,
                                          negative_initial_fraction=.1 if mode == 'charge' else .9,
                                          positive_max_v=c['requested_max_v'], cell_max_v=c['requested_max_v']))
                        self.assertGreater(r['summary']['capacity_ah'], .1)
                        self.assertTrue(r['points'])
                        self.assertEqual(r['validation_status'], 'source_bounded_unvalidated')
                        self.assertIn(r['termination'],
                                      {'positive_source_end', 'positive_upper_voltage', 'cell_upper_voltage'})
                        json.dumps(r, allow_nan=False)

    def test_upper_cutoffs_exact_and_interval_independent(self):
        for curve, upper in [('nmc811_2023_cycle4', 4.4), ('lco2018_bare_cycle3', 4.55), ('lfp_2022_fmc_cycle3', 3.7)]:
            results = [simulate(dict(curve_id=curve, mode='charge', initial_soc=0,
                                     positive_max_v=upper, dt_s=dt)) for dt in (2, 120)]
            for r in results:
                self.assertEqual(r['termination'], 'positive_upper_voltage')
                self.assertAlmostEqual(r['summary']['final_positive_v'], upper, places=10)
            self.assertAlmostEqual(results[0]['summary']['duration_s'], results[1]['summary']['duration_s'], places=8)
            self.assertAlmostEqual(results[0]['summary']['energy_wh'], results[1]['summary']['energy_wh'], places=9)

    def test_separate_positive_and_terminal_cutoffs(self):
        base = dict(mode='charge', initial_soc=.05, voltage_basis='full_cell', negative_initial_fraction=.1,
                    positive_max_v=4.55, cell_max_v=4.2)
        r = simulate(base)
        self.assertEqual(r['termination'], 'cell_upper_voltage')
        self.assertAlmostEqual(r['summary']['final_terminal_v'], 4.2, places=10)
        self.assertLess(r['summary']['final_positive_v'], 4.55)
        r2 = simulate({**base, 'cell_max_v': 4.8, 'positive_max_v': 4.4})
        self.assertEqual(r2['termination'], 'positive_upper_voltage')
        self.assertAlmostEqual(r2['summary']['final_positive_v'], 4.4, places=10)
        self.assertLess(r2['summary']['final_terminal_v'], 4.4)

    def test_lower_voltage_event(self):
        r = simulate(dict(positive_min_v=3.6))
        self.assertEqual(r['termination'], 'positive_lower_voltage')
        self.assertAlmostEqual(r['summary']['final_positive_v'], 3.6, places=10)

    def test_low_voltage_unrecorded_stops_at_source_not_requested_cutoff(self):
        r = simulate(dict(positive_min_v=1.5))
        self.assertEqual(r['termination'], 'positive_source_end')
        self.assertAlmostEqual(r['summary']['final_positive_v'], 3, places=10)
        self.assertTrue(any('未収録' in x for x in r['limitations']))
        self.assertAlmostEqual(r['summary']['final_soc'], 0, places=10)

    def test_ocp_capacity_is_user_assumption_and_no_second_measured_branch(self):
        r = simulate(dict(curve_id='nmc622_wan2026', mode='charge', initial_soc=0, positive_max_v=4.4,
                          ocp_capacity_mah_g=180, positive_mass_g=5))
        self.assertEqual(r['mapping']['capacity_basis'], 'user_assumed_ocp_scale')
        self.assertFalse(r['mapping']['independent_charge_discharge'])
        self.assertAlmostEqual(r['summary']['capacity_ah'], .9)
        self.assertEqual(r['termination'], 'positive_source_end')
        self.assertAlmostEqual(r['summary']['final_positive_v'], 4.30014324)

    def test_charge_balance_and_voltage_equation(self):
        for mode in ('charge', 'discharge'):
            c = dict(mode=mode, voltage_basis='full_cell', additional_r_mohm=25,
                     initial_soc=.05 if mode == 'charge' else .95,
                     negative_initial_fraction=.1 if mode == 'charge' else .9)
            r = simulate(c)
            for p in r['points']:
                self.assertAlmostEqual(p['negative_fraction'],
                                       c['negative_initial_fraction'] - p['current_a'] * p['time_s'] / (3 * 3600),
                                       places=12)
                self.assertAlmostEqual(p['voltage_v'],
                                       p['positive_reference_v'] - p['negative_reference_v'] - p['current_a'] * .025,
                                       places=12)
                self.assertAlmostEqual(p['capacity_ah'], abs(p['current_a']) * p['time_s'] / 3600, places=12)
            self.assertEqual(r['summary']['energy_wh'] > 0, mode == 'discharge')

    def test_additional_resistance_energy_accounting(self):
        base = dict(duration_min=20, voltage_basis='full_cell', additional_r_mohm=0)
        a = simulate(base)
        b = simulate({**base, 'additional_r_mohm': 100})
        self.assertEqual(a['termination'], 'duration')
        self.assertEqual(b['termination'], 'duration')
        self.assertAlmostEqual(a['summary']['energy_wh'] - b['summary']['energy_wh'], .5 ** 2 * .1 / 3, places=10)
        self.assertAlmostEqual(b['summary']['additional_heat_w'], .025)

    def test_negative_source_domain_and_initial_window(self):
        r = simulate(dict(voltage_basis='full_cell', negative_capacity_ah=.1, cell_min_v=1.5))
        self.assertEqual(r['termination'], 'negative_source_end')
        self.assertAlmostEqual(r['points'][-1]['negative_fraction'], catalog()['negative_reference']['points'][0][0],
                               places=10)
        r2 = simulate(dict(positive_max_v=3.5))
        self.assertEqual(r2['termination'], 'positive_upper_voltage')
        self.assertEqual(r2['summary']['capacity_ah'], 0)

    def test_mass_capacity_scaling(self):
        a = simulate(dict(positive_mass_g=10, current_a=.5, duration_min=1000, dt_s=120))
        b = simulate(dict(positive_mass_g=20, current_a=1, duration_min=1000, dt_s=120))
        self.assertAlmostEqual(a['summary']['duration_s'], b['summary']['duration_s'])
        self.assertAlmostEqual(2 * a['summary']['capacity_ah'], b['summary']['capacity_ah'])
        self.assertAlmostEqual(2 * a['summary']['energy_wh'], b['summary']['energy_wh'])

    def test_invalid_inputs(self):
        for data in [[], {'unknown': 1}, {'curve_id': '../x'}, {'current_a': True}, {'initial_soc': float('nan')},
                     {'positive_min_v': 4.4}, {'voltage_basis': 'full_cell', 'negative_initial_fraction': 0},
                     {'current_a': -1}, {'duration_min': 1440, 'dt_s': .1}, {'mode': 'rest'}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate(data)


class ReferencePersistenceTests(unittest.TestCase):
    def test_service_save_roundtrip_project_and_csv_provenance(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.test_tmp') as d:
            repo = RunRepository(Path(d) / 'runs.sqlite3')
            service = SimulationService(repo)
            project = repo.create_project('公開正極の検証')
            run = service.run_reference({'name': 'LCO reference', 'curve_id': 'lco2018_bare_cycle3'}, project['id'])
            service.save(run['id'])
            saved = repo.get(run['id'])
            self.assertEqual(saved, run)
            self.assertEqual(len(repo.list(project['id'])), 1)
            self.assertEqual(len(repo.list('default')), 0)
            text = export_csv(saved).decode('utf-8-sig')
            self.assertIn('# source_snapshot:', text)
            self.assertIn('publisher_source_data_xlsx', text)
            rows = list(csv.DictReader(StringIO('\n'.join(x for x in text.splitlines() if not x.startswith('#')))))
            self.assertEqual(len(rows), run['summary']['point_count'])
            self.assertAlmostEqual(float(rows[-1]['positive_reference_v']), run['summary']['final_positive_v'])
            repo.save_comparison(dict(project_id=project['id'], dataset_ids=[run['id']], x_axis='capacity_ah',
                                      variable='positive_reference_v'))
            with self.assertRaises(ValueError):
                service.run_reference({}, 'missing-project')

    def test_large_http_snapshots_reuse_connection_and_errors_close(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.test_tmp') as d:
            server = create_server(0, d)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                socket = None
                for path, body in [('/api/cathodes', None), ('/api/cathodes/simulate', {}),
                                   ('/api/cathodes/simulate', {'curve_id': 'lmfp_2022_fmc_cycle3'})]:
                    connection.request('GET' if body is None else 'POST', path,
                                       None if body is None else json.dumps(body), {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    raw = response.read()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(len(raw), int(response.getheader('Content-Length')))
                    self.assertIsNotNone(connection.sock)
                    if socket is not None:
                        self.assertIs(socket, connection.sock)
                    socket = connection.sock
                    data = json.loads(raw)
                    self.assertTrue(data.get('catalog') or data.get('source_snapshot'))
                connection.request('POST', '/api/cathodes/simulate', '{}', {'Content-Type': 'text/plain'})
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                self.assertIsNone(connection.sock)
            finally:
                connection.close()
                server.shutdown()
                thread.join(5)
                server.server_close()


if __name__ == '__main__':
    unittest.main()
