"""P3 contracts and pre-queue rejection; native physics is verified separately."""
import copy
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler

import test_simulation
from pylibstudy.physics import validate_request
from pylibstudy.capabilities import CONFIG_SCHEMA_VERSION, model_options
from pylibstudy.result_analysis import balance_summary


class ThermalContractTests(unittest.TestCase):
    def test_unselected_contact_component_does_not_report_a_false_balance_failure(self):
        p = dict(time_s=0, current_a=1, voltage_v=3.6, surface_ocv_v=3.8, reaction_overpotential_v=-.1,
                 electrolyte_ohmic_loss_v=-.02, concentration_overpotential_v=-.03, solid_ohmic_loss_v=-.04)
        check = balance_summary([p], include_contact=True)['balance_checks']['voltage']
        self.assertEqual(check['status'], 'unavailable');
        self.assertIsNone(check['passed'])
        p['contact_voltage_loss_v'] = -.01
        self.assertTrue(balance_summary([p], include_contact=True)['balance_checks']['voltage']['passed'])

    def test_legacy_versions_preserve_original_and_thermal_defaults(self):
        for version in [None, '1.0', '1.1', '1.2', '1.3']:
            data = dict(thermal='lumped', heat_transfer_w_m2_k=17)
            if version: data['config_schema_version'] = version
            before = copy.deepcopy(data)
            c = validate_request(data)
            self.assertEqual(data, before)
            self.assertEqual(c['config_schema_version'], CONFIG_SCHEMA_VERSION)
            self.assertEqual(c['thermal_settings']['capacity_mode'], 'literature')
            self.assertEqual(c['heat_transfer_w_m2_k'], 17)
            self.assertEqual(model_options(c)['contact resistance'], 'false')

    def test_invalid_thermal_properties_never_normalized_to_defaults(self):
        for t in [None, [], {'arbitrary_code': 'bad'}, {'capacity_mode': 'unknown'},
                  {'cell_heat_capacity_j_k': True}, {'contact_resistance_ohm': -1},
                  {'contact_resistance_ohm': float('nan')}, {'isothermal_heat_source': 'false'},
                  {'heat_of_mixing': 1}, {'source': []}, {'source': 'x' * 1001},
                  {'cooling_area_m2': 0}, {'cell_volume_m3': 0},
                  {'capacity_mode': 'user'}, {'capacity_mode': 'literature', 'cell_heat_capacity_j_k': 50},
                  {'surface_temperature': 'lumped'}, {'casing_heat_capacity_j_k': 5}]:
            with self.subTest(t=t), self.assertRaises(ValueError):
                validate_request(dict(thermal='lumped', thermal_settings=t))

    def test_explicit_properties_require_source_and_correct_thermal_mode(self):
        for t in [dict(capacity_mode='user', cell_heat_capacity_j_k=50),
                  dict(contact_resistance_ohm=.01), dict(cooling_area_m2=.005), dict(cell_volume_m3=.00002),
                  dict(surface_temperature='lumped', casing_heat_capacity_j_k=5, environment_thermal_resistance_k_w=2)]:
            with self.subTest(t=t), self.assertRaises(ValueError):
                validate_request(dict(thermal='lumped', thermal_settings=t))
            c = validate_request(dict(thermal='lumped', thermal_settings={**t, 'source': 'assumed; uncalibrated'}))
            self.assertEqual(c['thermal_settings']['source'], 'assumed; uncalibrated')
        for t in [dict(capacity_mode='user', cell_heat_capacity_j_k=50, source='fixture'),
                  dict(surface_temperature='lumped', casing_heat_capacity_j_k=5, environment_thermal_resistance_k_w=2,
                       source='fixture')]:
            with self.assertRaises(ValueError): validate_request(dict(thermal_settings=t))

    def test_composite_requires_explicit_capacity_and_rejects_mixing(self):
        base = dict(model='DFN', parameter_set='Chen2020_composite', thermal='lumped')
        with self.assertRaisesRegex(ValueError, 'セル熱容量'): validate_request(base)
        t = dict(capacity_mode='user', cell_heat_capacity_j_k=50, source='synthetic fixture')
        c = validate_request(dict(base, thermal_settings=t))
        self.assertEqual(model_options(c)['use lumped thermal capacity'], 'true')
        with self.assertRaisesRegex(ValueError, '混合熱'):
            validate_request(dict(base, thermal_settings=dict(t, heat_of_mixing=True)))

    def test_registered_options_match_top_level_thermal_settings(self):
        c = validate_request(dict(thermal='lumped', thermal_settings=dict(capacity_mode='user',
                                                                          cell_heat_capacity_j_k=50,
                                                                          contact_resistance_ohm=.01,
                                                                          heat_of_mixing=True, source='fixture')))
        expected = model_options(c)
        for key in ('use lumped thermal capacity', 'contact resistance', 'heat of mixing'):
            self.assertEqual(expected[key], 'true')
            bad = copy.deepcopy(c);
            bad['model_options'] = {key: 'false'}
            with self.assertRaises(ValueError): validate_request(bad)
        with self.assertRaises(ValueError):
            validate_request(dict(thermal_settings=dict(heat_of_mixing=True, isothermal_heat_source=False)))


class ThermalHttpTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_peer_disconnects_close_connection_and_other_errors_propagate(self):
        handler = object.__new__(self.server.RequestHandlerClass)
        for error in (ConnectionResetError(), BrokenPipeError()):
            with patch.object(BaseHTTPRequestHandler, 'handle', side_effect=error):
                handler.handle()
                self.assertTrue(handler.close_connection)
        with patch.object(BaseHTTPRequestHandler, 'handle', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError): handler.handle()

    def test_invalid_thermal_requests_rejected_without_jobs(self):
        invalid = [dict(thermal='lumped', model='DFN', parameter_set='Chen2020_composite'),
                   dict(thermal_settings=dict(contact_resistance_ohm=.01)),
                   dict(thermal_settings=dict(heat_of_mixing=True, isothermal_heat_source=False)),
                   dict(thermal_settings={'unregistered': 1})]
        for data in invalid:
            for path, payload in [('/api/jobs', dict(input=data)), ('/api/physics/validate', data)]:
                with self.subTest(path=path, data=data), self.assertRaises(HTTPError) as error:
                    self.request(path, payload)
                self.assertEqual(error.exception.code, 400);
                error.exception.close()
        with self.request('/api/jobs') as response:
            self.assertEqual(json.load(response), [])


if __name__ == '__main__': unittest.main()
