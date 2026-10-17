"""P0 registry, legacy roundtrips and rejection at the public API boundary."""
import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import test_simulation
from pylibstudy.capabilities import catalog, compatibility, COMBINATIONS, model_options
from pylibstudy.physics import CONFIG_SCHEMA_VERSION, DEFAULTS, validate_request
from pylibstudy.storage import RunRepository
from pylibstudy.service import SimulationService


class CatalogTests(unittest.TestCase):
    def test_inventory_coverage_and_current_solver(self):
        data = catalog({'available': False, 'message': 'test'})
        inventory = json.loads(Path('docs/evidence/pybamm_capabilities_26.10.1.0.json').read_text(encoding='utf-8'))
        self.assertEqual({o['key'] for o in data['options']}, set(inventory['battery_options']))
        self.assertEqual(len(data['options']), 39)
        self.assertEqual(len({f['id'] for f in data['features']}), 83)
        self.assertEqual({o['status'] for o in data['options']}, {'executable', 'unconnected', 'out_of_scope'})
        self.assertEqual([s['id'] for s in data['solvers'] if s['connected']], ['IDAKLUSolver'])

    def test_all_cartesian_combinations_use_one_gate(self):
        for model, params, thermal, solver in itertools.product(
                ['SPMe', 'DFN', 'SPM'], ['Chen2020', 'Chen2020_composite', 'Prada2013'],
                ['isothermal', 'lumped', 'x-full'], ['IDAKLUSolver', 'CasadiSolver']):
            c = dict(model=model, parameter_set=params, thermal=thermal, solver=solver)
            expected = c in COMBINATIONS
            if params == 'Chen2020_composite' and thermal == 'lumped':
                c['thermal_settings'] = dict(capacity_mode='user', cell_heat_capacity_j_k=50,
                                             source='synthetic fixture')
            with self.subTest(c=c):
                self.assertEqual(compatibility(c)['compatible'], expected)
                if expected:
                    self.assertEqual(validate_request(c)['model'], model)
                else:
                    with self.assertRaises(ValueError):
                        validate_request(c)
        self.assertFalse(compatibility(DEFAULTS, os_name='Linux')['compatible'])

    def test_schema_migration_is_nonmutating_and_future_versions_rejected(self):
        old = {k: copy.deepcopy(v) for k, v in DEFAULTS.items() if
               k not in {'config_schema_version', 'solver', 'model_options'}}
        before = copy.deepcopy(old)
        migrated = validate_request(old)
        self.assertEqual(old, before)
        self.assertEqual(migrated['config_schema_version'], CONFIG_SCHEMA_VERSION)
        self.assertEqual(migrated['solver'], 'IDAKLUSolver')
        self.assertEqual(validate_request(migrated), migrated)
        for version in [None, True, 1, '2.0', '0.0']:
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_request({'config_schema_version': version})

    def test_unsupported_and_contradictory_options_rejected(self):
        for options in [[], {'thermal': 'lumped'}, {'SEI': 'none'}, {'SEI': 'reaction limited'},
                        {'convection': 'none'}, {'calculate discharge energy': False}, {'__class__': 'x'}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate_request({'model_options': options})
        c = validate_request({'model_options': {'thermal': 'isothermal'}})
        self.assertEqual(model_options(c)['thermal'], 'isothermal')
        composite = dict(model='DFN', parameter_set='Chen2020_composite')
        options = json.loads(json.dumps(model_options(validate_request(composite))))
        self.assertEqual(validate_request(dict(composite, model_options=options))['model_options'], options)

    def test_runtime_failure_is_sanitized_and_blocks_execution(self):
        from pylibstudy.jobs import PhysicsJobs
        with tempfile.TemporaryDirectory() as directory:
            repo = RunRepository(Path(directory) / 'runs.sqlite3')
            with patch('pylibstudy.jobs.subprocess.run', side_effect=RuntimeError('secret raw third party error')):
                jobs = PhysicsJobs(repo, python_exe=Path(__import__('sys').executable), start=False)
            try:
                self.assertFalse(jobs.availability['available'])
                self.assertNotIn('secret', json.dumps(jobs.availability))
                with self.assertRaises(ValueError):
                    jobs.submit({})
            finally:
                jobs.close()


class CapabilityHttpTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_catalog_and_invalid_requests_leave_queue_empty(self):
        with self.request('/api/capabilities') as response:
            catalog_data = json.load(response)
        self.assertEqual(len(catalog_data['options']), 39)
        self.assertEqual(len(catalog_data['combinations']), len(COMBINATIONS))
        for bad in [{'model': 'SPM', 'parameter_set': 'Chen2020_composite'},
                    {'model': 'SPMe', 'parameter_set': 'Chen2020_composite'},
                    {'solver': 'CasadiSolver'}, {'config_schema_version': '9.0'},
                    {'model_options': {'thermal': 'x-full'}}]:
            for path, payload in [('/api/jobs', {'input': bad}), ('/api/physics/validate', bad)]:
                with self.subTest(path=path, bad=bad), self.assertRaises(HTTPError) as error:
                    self.request(path, payload)
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
        with self.request('/api/jobs') as response:
            self.assertEqual(json.load(response), [])

    def test_legacy_result_view_json_and_restore_after_restart(self):
        fixture = Path('docs/evidence/step03/spme_normal.json')
        record = json.loads(fixture.read_text(encoding='utf-8'))
        for key in ('config_schema_version', 'solver', 'model_options'):
            record['input'].pop(key, None)
        record['id'] = 'legacy-p0-regression'
        self.server.service.repository.save(record)
        # A fresh repository/service represents rereading persisted JSON, not in-memory migration.
        service = SimulationService(RunRepository(self.server.service.repository.path))
        self.assertEqual(service.get(record['id']), record)

        for suffix in ['', '.json']:
            with self.request('/api/results/' + record['id'] + suffix) as response:
                self.assertEqual(json.load(response), record)
        with self.request('/api/physics/validate', record['input']) as response:
            restored = json.load(response)['input']
        self.assertEqual(restored['config_schema_version'], CONFIG_SCHEMA_VERSION)
        self.assertEqual(restored['model'], record['input']['model'])
        self.assertEqual(service.get(record['id']), record)

    def test_large_valid_profile_can_be_restored(self):
        points = [[0, 1.2345678901234567]] + [[i + .1234567890123456, 1.2345678901234567] for i in range(1, 2000)]
        config = dict(protocol=[dict(kind='profile', points=points)])
        self.assertGreater(len(json.dumps(config).encode()), 65536)
        with self.request('/api/physics/validate', config) as response:
            self.assertEqual(json.load(response)['input']['protocol'], config['protocol'])

if __name__ == '__main__':
    unittest.main()
