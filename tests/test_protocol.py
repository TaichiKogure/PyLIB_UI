"""P1 declarative contract and preview invariants, independent of PyBaMM."""
import copy
import json
import unittest
from urllib.error import HTTPError

import test_simulation
from pylibstudy.design import evaluate_design
from pylibstudy.physics import validate_request
from pylibstudy.protocol import preview_protocol, protocol_templates


class ProtocolTests(unittest.TestCase):
    def test_nested_repeat_expansion_and_per_step_output_budget(self):
        c = validate_request(dict(cycles=2, protocol=[dict(kind='repeat', count=2, steps=[
            dict(kind='c_rate', c_rate=.2, duration_s=10, period_s=2, temperature_c=30, tags=['pulse']),
            dict(kind='repeat', count=2, steps=[dict(kind='rest', duration_s=5)])])]))
        before = copy.deepcopy(c)
        preview = preview_protocol(c)
        self.assertEqual(c, before)
        self.assertEqual(preview['total_steps'], 12)
        self.assertEqual(preview['duration_upper_s'], 80)
        self.assertEqual(preview['steps'][0]['current_a'], 1)
        self.assertEqual(preview['steps'][0]['temperature_c'], 30)
        self.assertEqual(preview['steps'][6]['cycle'], 2)
        self.assertEqual(preview['output_points_upper'], sum(s['output_points_upper'] for s in preview['steps']))

    def test_c_rate_and_ampere_roundtrip_with_design_capacity(self):
        design = evaluate_design({})
        capacity = design['capacity']['c_rate_reference_ah']
        for rate in [-.2, .2]:
            c = validate_request(dict(protocol=[dict(kind='c_rate', c_rate=rate, duration_s=10)]))
            p = preview_protocol(c, design)
            self.assertAlmostEqual(p['steps'][0]['current_a'], rate * capacity)
            a = validate_request(dict(protocol=[dict(kind='cc', current_a=rate * capacity, duration_s=10)]))
            self.assertAlmostEqual(preview_protocol(a, design)['steps'][0]['c_rate'], rate)
        c = validate_request(dict(protocol=[dict(kind='cv', voltage_v=4, stop_c_rate=.05, duration_s=30)]))
        self.assertAlmostEqual(preview_protocol(c, design)['steps'][0]['stop_current_a'], .05 * capacity)
        with self.assertRaises(ValueError):
            preview_protocol(validate_request(dict(protocol=[dict(kind='c_rate', c_rate=100, duration_s=1)])))

    def test_templates_have_expected_signs_and_can_be_edited(self):
        templates = protocol_templates()
        self.assertEqual({t['id'] for t in templates}, {'cccv', 'hppc', 'gitt'})
        for template in templates:
            p = preview_protocol(validate_request(dict(protocol=template['protocol'])))
            self.assertGreater(p['total_steps'], 1)
        cccv = preview_protocol(validate_request(dict(protocol=templates[0]['protocol'])))
        self.assertLess(cccv['steps'][0]['current_a'], 0)
        self.assertEqual(cccv['steps'][0]['stop_voltage_v'], cccv['steps'][1]['voltage_v'])
        self.assertGreater(cccv['steps'][1]['stop_current_a'], 0)

    def test_invalid_trees_controls_and_nonfinite_values_rejected(self):
        for data in [dict(cycles=True), dict(cycles=21), dict(start_time='tomorrow'),
                     dict(protocol=[dict(kind='repeat', count=0, steps=[])]),
                     dict(protocol=[dict(kind='repeat', count=20, steps=[dict(kind='rest', duration_s=1)])], cycles=20),
                     dict(protocol=[dict(kind='rest', duration_s=60, period_s=.001)]),
                     dict(protocol=[dict(kind='rest', duration_s=60, tags='tag')]),
                     dict(protocol=[dict(kind='rest', duration_s=60, temperature_c=46)]),
                     dict(protocol=[dict(kind='rest', duration_s=60, skip_ok='true')]),
                     dict(protocol=[dict(kind='cp', power_w=float('nan'), duration_s=10)]),
                     dict(protocol=[dict(kind='cp', power_w=1000, duration_s=10)]),
                     dict(protocol=[dict(kind='cr', resistance_ohm=0, duration_s=10)]),
                     dict(protocol=[dict(kind='cp', power_w=4, control='python', duration_s=10)]),
                     dict(protocol=[dict(kind='cp', power_w=4, control_tau_s=2, duration_s=10)]),
                     dict(protocol=[dict(kind='cv', voltage_v=4, stop_c_rate=.1, stop_current_a=.1, duration_s=10)])]:
            with self.subTest(data=data), self.assertRaises(ValueError): validate_request(data)
        block = dict(kind='rest', duration_s=10)
        for _ in range(4): block = dict(kind='repeat', count=2, steps=[block])
        with self.assertRaises(ValueError):
            validate_request(dict(protocol=[block]))

    def test_v10_migration_and_waveform_in_mixed_protocol(self):
        c = validate_request(dict(config_schema_version='1.0', protocol=[
            dict(kind='profile', points=[[0, 1], [10, -1]]), dict(kind='rest', duration_s=10)]))
        self.assertEqual(c['config_schema_version'], '1.4')
        self.assertEqual(c['cycles'], 1)
        self.assertEqual(preview_protocol(c)['duration_upper_s'], 20)


class ProtocolHttpTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_preview_does_not_enqueue_and_checks_project_design(self):
        with self.request('/api/physics/preview', {'input': {'model': 'SPM'}}) as response:
            self.assertEqual(json.load(response)['c_rate_reference_ah'], 5)
        with self.request('/api/jobs') as response: self.assertEqual(json.load(response), [])
        for bad in [{'input': {'design_id': 'missing'}}, {'input': {}, 'project_id': 'missing'},
                    {'input': {'protocol': [dict(kind='c_rate', c_rate=100, duration_s=10)]}}]:
            with self.assertRaises(HTTPError) as error: self.request('/api/physics/preview', bad)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()


if __name__ == '__main__': unittest.main()
