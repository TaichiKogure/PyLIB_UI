import copy, json, unittest
from urllib.error import HTTPError
import test_simulation
from pathlib import Path
from pylibstudy.physics import validate_request
from pylibstudy.materials import catalog, expression_tree
from pylibstudy.protocol import preview_protocol


class MaterialTests(unittest.TestCase):
    def test_inventory_and_curated_routes(self):
        c = catalog();
        self.assertEqual(len(c['inventory']['sets']), 19)
        for name in ['Prada2013', 'NCA_Kim2011']:
            self.assertEqual(validate_request(dict(parameter_set=name))['parameter_set'], name)
        self.assertFalse(
            validate_request(dict(parameter_set='Prada2013'))['thermal_settings']['isothermal_heat_source'])

    def test_old_versions_and_nonmutation(self):
        for version in ['1.0', '1.1', '1.2', '1.3', '1.4']:
            source = {'config_schema_version': version};
            original = copy.deepcopy(source)
            self.assertEqual(validate_request(source)['config_schema_version'], '1.4');
            self.assertEqual(source, original)

    def test_missing_dependencies_and_wrong_material_options(self):
        for settings in [dict(transport='tortuosity factor'), dict(diffusivity='current sigmoid'),
                         dict(exchange_current='current sigmoid')]:
            with self.assertRaisesRegex(ValueError, '必須物性'): validate_request(dict(material_settings=settings))
        with self.assertRaises(ValueError): validate_request(
            dict(material_settings={'silicon_ocp': 'one-state hysteresis'}))

    def test_override_validation(self):
        invalid = [{'Nominal cell capacity [A.h]': -1}, {'Negative electrode porosity': 1.2},
                   {'Negative electrode porosity': .5}, {'Negative electrode conductivity [S.m-1]': -1}, {'bad': 1},
                   {'Nominal cell capacity [A.h]': True}, {'Positive electrode OCP [V]': '__import__("os")'},
                   {'Positive electrode OCP [V]': {'kind': 'ocp_table', 'points': [[0, 4], [0, 3], [1, 2]]}}]
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError): validate_request(
                dict(material_settings=dict(source='test', overrides=overrides)))
        with self.assertRaises(ValueError): validate_request(
            dict(material_settings=dict(overrides={'Nominal cell capacity [A.h]': 4})))

    def test_capacity_preview_uses_explicit_capacity(self):
        c = validate_request(
            dict(material_settings=dict(source='assumption', overrides={'Nominal cell capacity [A.h]': 4}),
                 protocol=[dict(kind='c_rate', c_rate=.5, duration_s=10)]))
        self.assertEqual(preview_protocol(c)['steps'][0]['current_a'], 2)

    def test_half_cell_gate_and_reference(self):
        with self.assertRaises(ValueError): validate_request(dict(parameter_set='Xu2019', model='DFN'))
        c = validate_request(dict(parameter_set='Xu2019', model='DFN', reference_electrode_fraction=None))
        self.assertEqual(c['material_settings']['overrides'], {})

    def test_bpx_data_and_expressions(self):
        obj = json.loads(Path('pylibstudy/data/bpx_reference.json').read_text(encoding='utf-8'));
        before = copy.deepcopy(obj)
        c = validate_request(
            dict(parameter_set='BPX', model='DFN', material_settings=dict(bpx=obj, source='official fixture')))
        self.assertEqual(obj, before);
        self.assertEqual(preview_protocol(c)['c_rate_reference_ah'], 12.5)
        for expression in ['__import__("os")', 'x.__class__', '[x for x in []]', 'exp(x);print(1)', 'exp(x, x)',
                           '1e999']:
            with self.subTest(expression=expression), self.assertRaises(ValueError): expression_tree(expression)
        expression_tree('1 + 2*x**2 - exp(-x)')
        broken = copy.deepcopy(obj);
        broken['Parameterisation']['Negative electrode']['OCP [V]'] = 'x.__class__'
        with self.assertRaises(ValueError): validate_request(
            dict(parameter_set='BPX', model='DFN', material_settings=dict(bpx=broken, source='bad')))


class MaterialHTTPTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_catalog_and_rejection_before_queue(self):
        with self.request('/api/materials') as response:
            data = json.load(response)
        self.assertEqual(len(data['inventory']['sets']), 19)
        for input in [dict(material_settings=dict(transport='tortuosity factor')),
                      dict(material_settings=dict(source='bad', overrides={'Positive electrode OCP [V]': 'print(1)'})),
                      dict(parameter_set='BPX', model='DFN')]:
            with self.assertRaises(HTTPError) as caught: self.request('/api/jobs', {'input': input})
            self.assertEqual(caught.exception.code, 400);
            caught.exception.close()
        with self.request('/api/jobs') as response: self.assertEqual(json.load(response), [])

    def test_material_restore_and_capacity_preview(self):
        input = dict(config_schema_version='1.3', material_settings=dict(source='HTTP synthetic fixture',
                                                                         overrides={'Nominal cell capacity [A.h]': 4}),
                     protocol=[dict(kind='c_rate', c_rate=.5, duration_s=5)])
        with self.request('/api/physics/validate', input) as response: restored = json.load(response)['input']
        self.assertEqual(restored['config_schema_version'], '1.4')
        with self.request('/api/physics/preview', {'input': restored}) as response: preview = json.load(response)
        self.assertEqual(preview['c_rate_reference_ah'], 4)
        self.assertEqual(preview['steps'][0]['current_a'], 2)


if __name__ == '__main__': unittest.main()
