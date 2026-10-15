"""Independent balances, invalid designs, immutable persistence and run lineage."""
import json
import tempfile
import unittest
from pathlib import Path

from pylib_ui.design import evaluate_design, templates
from pylib_ui.schema import SimulationInput
from pylib_ui.service import SimulationService, design_simulation_fields
from pylib_ui.storage import RunRepository
import test_simulation
from urllib.error import HTTPError


class DesignTests(unittest.TestCase):
    def test_templates_and_area_adapter(self):
        for template in templates().values():
            r = evaluate_design(template)
            self.assertGreater(r['capacity']['design_ah'], 0)
            self.assertAlmostEqual(r['geometry']['outer_radius_mm'],
                                   template['diameter_mm'] / 2 - template['wall_mm'] - template['radial_gap_mm'])
            a = r['adapter_input']
            self.assertAlmostEqual(a['electrode_height_m'] * a['electrode_width_m'] * a['parallel_electrodes'],
                                   r['positive']['area_cm2'] / 10000)
            self.assertEqual(a['negative_particle_phases'], '1')
            self.assertFalse(a['solver_ready'])

    def test_independent_rectangular_volume_and_mass_balance(self):
        r = evaluate_design(dict(length_mode='manual', length_mm=100, winding_width_mm=10,
                                 positive_width_mm=10, negative_width_mm=10,
                                 positive_thickness_um=200, negative_thickness_um=200,
                                 positive_foil_um=50, negative_foil_um=50, separator_um=50,
                                 positive_porosity=0, negative_porosity=0, separator_porosity=0,
                                 positive_active=1, positive_binder=0, positive_carbon=0,
                                 negative_graphite=1, negative_binder=0, negative_carbon=0))
        # 100 x 10 mm strip: two 0.2mm coatings per electrode, two .05mm foils and two .05mm separators.
        self.assertAlmostEqual(r['geometry']['envelope_cm3'], 1)
        self.assertAlmostEqual(r['geometry']['layer_volume_cm3'], 1)
        self.assertAlmostEqual(r['geometry']['uncoated_void_cm3'], 0)
        self.assertAlmostEqual(r['positive']['area_cm2'], 20)
        self.assertAlmostEqual(r['positive']['dry_mass_g'], 1.92)
        self.assertAlmostEqual(r['positive']['capacity_ah'], .384)
        self.assertAlmostEqual(r['negative']['dry_mass_g'], .904)
        self.assertAlmostEqual(r['negative']['capacity_ah'], .3164)
        self.assertAlmostEqual(r['mass_g']['al_foil'], .135)
        self.assertAlmostEqual(r['mass_g']['cu_foil'], .448)
        self.assertEqual(r['mass_g']['electrolyte'], 0)
        self.assertAlmostEqual(r['capacity']['design_ah'], .3164)
        self.assertAlmostEqual(r['total_mass_g'], sum(r['mass_g'].values()))

    def test_manual_length_scaling_and_fit_changes(self):
        a = evaluate_design(dict(length_mode='manual', length_mm=300))
        b = evaluate_design(dict(length_mode='manual', length_mm=600))
        for key in ['area_cm2', 'dry_mass_g', 'capacity_ah']:
            self.assertAlmostEqual(b['positive'][key], 2 * a['positive'][key])
        thick = evaluate_design(dict(positive_thickness_um=100))
        self.assertLess(thick['geometry']['length_mm'], evaluate_design({})['geometry']['length_mm'])
        wider = evaluate_design(dict(diameter_mm=22))
        self.assertGreater(wider['capacity']['design_ah'], evaluate_design({})['capacity']['design_ah'])

    def test_overlap_np_excludes_negative_overhang(self):
        a = evaluate_design({})
        b = evaluate_design(dict(negative_width_mm=64))
        self.assertGreater(b['capacity']['negative_total_ah'], a['capacity']['negative_total_ah'])
        self.assertAlmostEqual(b['capacity']['np_ratio'], a['capacity']['np_ratio'])
        self.assertAlmostEqual(b['capacity']['design_ah'], a['capacity']['design_ah'])

    def test_mass_volume_recipe_roundtrip_and_zero_si(self):
        a = evaluate_design(dict(negative_graphite=.86, negative_si=.1))
        fractions = a['negative']['components']
        b = evaluate_design(dict(fraction_basis='volume', positive_active=1, positive_binder=0, positive_carbon=0,
                                 **dict(zip(['negative_graphite', 'negative_si', 'negative_binder', 'negative_carbon'],
                                            [v['solid_volume_fraction'] for v in fractions]))))
        for x, y in zip(a['negative']['components'], b['negative']['components']):
            self.assertAlmostEqual(x['mass_fraction'], y['mass_fraction'])
        self.assertEqual(a['negative_phase_count'], 2)
        zero = evaluate_design({})
        self.assertEqual(zero['negative_phase_count'], 1)
        self.assertEqual([p['id'] for p in zero['adapter_input']['negative_active_components']], ['graphite_demo'])
        oxide = evaluate_design(dict(negative_graphite=.86, negative_si=.1, negative_additive='SiOx_demo'))
        self.assertNotEqual(a['negative']['capacity_ah'], oxide['negative']['capacity_ah'])

    def test_lithium_and_c_rate_are_distinct(self):
        a = evaluate_design(dict(c_rate_capacity_mode='rated', rated_capacity_ah=7,
                                 lithium_fraction_positive=0, lithium_fraction_negative=0))
        self.assertEqual(a['capacity']['c_rate_reference_ah'], 7)
        self.assertNotEqual(a['capacity']['design_ah'], 7)
        self.assertEqual(a['lithium_inventory']['total_mol_equivalent'], 0)
        b = evaluate_design(dict(lithium_fraction_negative=1, lithium_fraction_positive=0))
        self.assertAlmostEqual(b['lithium_inventory']['total_mol_equivalent'],
                               b['negative']['capacity_ah'] * 3600 / 96485.33212)

    def test_invalid_geometry_recipe_and_types(self):
        for data in [[], {'unexpected': 1}, {'wall_mm': 11}, {'axial_reserve_mm': 70},
                     {'lid_total_mm': 5}, {'lid_total_mm': 0},
                     {'negative_width_mm': 50}, {'positive_porosity': 1}, {'separator_um': 0},
                     {'positive_active': .5}, {'negative_si': .1}, {'diameter_mm': True},
                     {'diameter_mm': float('nan')}, {'length_mm': float('inf')}, {'length_mm': '10'},
                     {'length_mode': 'manual', 'length_mm': 100000}, {'positive_terminal': 'bottom'},
                     {'positive_contact_fraction': 0}, {'positive_material': 'NCX'}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                evaluate_design(data)

    def test_immutable_project_storage_and_run_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = RunRepository(Path(tmp) / 'runs.sqlite3')
            r = repo.save_design({'input': {}})
            second = repo.save_design({'input': {'name': '新しい版', 'diameter_mm': 22}})
            self.assertNotEqual(r['id'], second['id'])
            other = repo.create_project('別プロジェクト')['id']
            self.assertEqual(repo.designs(other), [])
            with self.assertRaises(ValueError):
                repo.design(r['id'], other)
            config = SimulationInput().snapshot()
            config.update(design_simulation_fields(r), duration_min=1)
            service = SimulationService(repo)
            run = service.run(config, design_id=r['id'])
            service.save(run['id'])
            fresh = RunRepository(Path(tmp) / 'runs.sqlite3')
            self.assertEqual(fresh.get(run['id'])['design_snapshot'], r)
            self.assertEqual(len(fresh.designs('default')), 2)
            r['input']['diameter_mm'] = 99
            self.assertEqual(fresh.design(r['id'], 'default')['input']['diameter_mm'], 21)
            config['capacity_ah'] = 9
            with self.assertRaises(ValueError):
                service.run(config, design_id=r['id'])
            with self.assertRaises(ValueError):
                service.run(config, project_id=other, design_id=r['id'])


class DesignHttpTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_design_api_roundtrip_and_invalid_inputs(self):
        for path in ['/design.js', '/api/design/config']:
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
        with self.request('/api/design/evaluate', {}) as response:
            preview = json.load(response)
        with self.request('/api/designs') as response:
            self.assertEqual(json.load(response), [])
        with self.request('/api/designs', {'input': preview['input']}) as response:
            design = json.load(response)
        with self.request('/api/designs') as response:
            self.assertEqual(json.load(response), [design])
        config = SimulationInput().snapshot()
        config.update(design_simulation_fields(design), design_id=design['id'], duration_min=1)
        with self.request('/api/simulate', config) as response:
            run = json.load(response)
            self.assertEqual(run['design_snapshot'], design)
        with self.request('/api/save', {'id': run['id']}):
            pass
        with self.request('/api/results/' + run['id'] + '.json') as response:
            self.assertEqual(json.load(response)['design_snapshot'], design)
        for path, data in [('/api/design/evaluate', {'wall_mm': 20}),
                           ('/api/designs', {'input': {}, 'project_id': 'missing'}),
                           ('/api/simulate', dict(config, capacity_ah=9))]:
            with self.assertRaises(HTTPError) as error:
                self.request(path, data)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()


if __name__ == '__main__':
    unittest.main()
