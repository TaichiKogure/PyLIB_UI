"""Independent capacity, electrical and heat balances for analytical screening."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from pylibstudy.design import evaluate_design, templates
from pylibstudy.storage import RunRepository


def component(result, key):
    return next(x for x in result['analysis']['resistance']['components'] if x['id'] == key)


class DesignAnalysisTests(unittest.TestCase):
    def test_capacity_override_conserves_mass_and_component_charge(self):
        a = evaluate_design(dict(positive_capacity_mah_g=180, graphite_capacity_mah_g=300))
        b = evaluate_design(dict(positive_capacity_mah_g=200, graphite_capacity_mah_g=300))
        self.assertEqual(a['mass_g'], b['mass_g'])
        self.assertAlmostEqual(b['positive']['capacity_ah'] / a['positive']['capacity_ah'], 200 / 180)
        for side in ['positive', 'negative']:
            self.assertAlmostEqual(sum(x['mass_g'] for x in a[side]['components']), a[side]['dry_mass_g'])
            self.assertAlmostEqual(sum(x['capacity_ah'] for x in a[side]['components']), a[side]['capacity_ah'])
        self.assertEqual(a['materials']['NMC811_demo']['capacity_used_mah_g'], 180)
        self.assertEqual(a['materials']['NMC811_demo']['capacity_source'], 'user_input_unvalidated')

    def test_mass_and_volume_recipes_with_capacity_overrides_agree(self):
        c = dict(negative_graphite=.86, negative_si=.1, additive_capacity_mah_g=2500)
        a = evaluate_design(c)
        c.update(fraction_basis='volume')
        for side, keys in [('positive', ['positive_active', 'positive_binder', 'positive_carbon']),
                           ('negative', ['negative_graphite', 'negative_si', 'negative_binder', 'negative_carbon'])]:
            for key, part in zip(keys, a[side]['components']):
                c[key] = part['solid_volume_fraction']
        b = evaluate_design(c)
        self.assertAlmostEqual(a['capacity']['design_ah'], b['capacity']['design_ah'])
        self.assertAlmostEqual(a['analysis']['resistance']['total_mohm'], b['analysis']['resistance']['total_mohm'])

    def test_utilization_and_formation_loss_are_distinct(self):
        r = evaluate_design(dict(positive_utilization=.9, negative_utilization=.8, negative_first_cycle_efficiency=.8))
        a = r['analysis']['capacity']
        qp, qn = r['capacity']['positive_ah'] * .9, r['capacity']['negative_overlap_ah'] * .8
        self.assertAlmostEqual(r['capacity']['design_ah'], min(qp, qn))
        self.assertAlmostEqual(a['formation_loss_ah'], qn / 4)
        self.assertAlmostEqual(a['inventory_limited_ah'], max(0, min(qp - qn / 4, qn)))
        zero_li = evaluate_design(dict(lithium_fraction_positive=0, lithium_fraction_negative=0))
        self.assertEqual(zero_li['lithium_inventory']['total_mol_equivalent'], 0)
        self.assertGreater(zero_li['analysis']['capacity']['inventory_limited_ah'], 0)
        lost = evaluate_design(dict(negative_first_cycle_efficiency=.01))
        self.assertEqual(lost['analysis']['capacity']['inventory_limited_ah'], 0)
        self.assertIsNone(lost['analysis']['performance']['diffusion']['positive']['diffusion_to_discharge_time_ratio'])

    def test_known_stoichiometric_limits_and_undefined_siox(self):
        r = evaluate_design(dict(negative_graphite=.86, negative_si=.1))
        rows = {p['material_id']: p for p in r['analysis']['capacity']['materials']}
        self.assertAlmostEqual(rows['graphite_demo']['theoretical_capacity_mah_g'], 372, delta=.2)
        self.assertAlmostEqual(rows['Si_demo']['theoretical_capacity_mah_g'], 3579, delta=1)
        lf = evaluate_design(dict(positive_material='LFP_demo'))
        self.assertAlmostEqual(lf['analysis']['capacity']['materials'][0]['theoretical_capacity_mah_g'], 170, delta=.2)
        oxide = evaluate_design(dict(negative_graphite=.86, negative_si=.1, negative_additive='SiOx_demo'))
        self.assertIsNone(oxide['analysis']['capacity']['materials'][-1]['theoretical_capacity_mah_g'])
        too_high = evaluate_design(dict(graphite_capacity_mah_g=500))
        self.assertTrue(any('理論上限' in w for w in too_high['analysis']['warnings']))

    def test_rectangular_resistance_units_and_parallel_faces(self):
        r = evaluate_design(dict(length_mode='manual', length_mm=100, winding_width_mm=10,
                                 positive_width_mm=10, negative_width_mm=10,
                                 positive_thickness_um=100, negative_thickness_um=100,
                                 positive_foil_um=10, negative_foil_um=10, separator_um=20,
                                 positive_porosity=.25, negative_porosity=.25, separator_porosity=.25,
                                 positive_bruggeman=1, negative_bruggeman=1, separator_bruggeman=1,
                                 electrolyte_conductivity_s_m=2, positive_contact_asr_ohm_mm2=.01))
        # Two 10 x 100 mm reaction faces: .002 m². κeff=.5 S/m.
        # Lsep=20 µm gives .02 Ω; distributed 100 µm electrode gives 1/30 Ω.
        self.assertAlmostEqual(component(r, 'separator')['resistance_mohm'], 20)
        self.assertAlmostEqual(component(r, 'positive_electrolyte')['resistance_mohm'], 100 / 3)
        # The foil itself is shared by both reaction faces: one edge, 0.01 x 100 = 1 mm².
        self.assertAlmostEqual(r['analysis']['resistance']['collectors']['positive']['foil_edge_area_mm2'], 1)
        self.assertAlmostEqual(component(r, 'positive_contact')['resistance_mohm'], 10)

    def test_conductivity_and_contact_scaling_do_not_double_count(self):
        a = evaluate_design({})
        b = evaluate_design(dict(electrolyte_conductivity_s_m=2, positive_contact_fraction=.5))
        for key in ['positive_electrolyte', 'negative_electrolyte', 'separator']:
            self.assertAlmostEqual(component(a, key)['resistance_mohm'] / 2, component(b, key)['resistance_mohm'])
        self.assertAlmostEqual(component(a, 'positive_contact')['resistance_mohm'] * 2,
                               component(b, 'positive_contact')['resistance_mohm'])
        for key in ['positive_foil', 'negative_foil', 'negative_contact', 'positive_solid', 'terminal']:
            self.assertEqual(component(a, key), component(b, key))

    def test_foil_scaling_and_longitudinal_reference_are_separate(self):
        a = evaluate_design(dict(length_mode='manual', length_mm=300))
        b = evaluate_design(dict(length_mode='manual', length_mm=300, positive_foil_um=30))
        self.assertAlmostEqual(component(b, 'positive_foil')['resistance_mohm'],
                               component(a, 'positive_foil')['resistance_mohm'] / 2)
        self.assertEqual(a['capacity'], b['capacity'])
        self.assertGreater(b['total_mass_g'], a['total_mass_g'])
        cols = a['analysis']['resistance']['collectors']['positive']
        self.assertAlmostEqual(
            cols['ideal_longitudinal_reference_mohm'] / component(a, 'positive_foil')['resistance_mohm'],
            (300 / 60) ** 2)
        self.assertAlmostEqual(sum(x['resistance_mohm'] for x in a['analysis']['resistance']['components']),
                               a['analysis']['resistance']['total_mohm'])

    def test_power_and_irreversible_heat_conserve_electrical_energy(self):
        for current in [0, .1, 5, 25]:
            r = evaluate_design(dict(analysis_current_a=current))
            a = r['analysis'];
            p = a['performance']
            self.assertAlmostEqual(p['operating_power_w'] + p['irreversible_heat_w'], current * 3.7)
            self.assertAlmostEqual(p['irreversible_heat_w'], sum(x['heat_w'] for x in a['resistance']['components']))
            self.assertAlmostEqual(p['voltage_drop_v'], sum(x['voltage_drop_v'] for x in a['resistance']['components']))
        a = evaluate_design(dict(terminal_resistance_mohm=1))['analysis']['performance']
        b = evaluate_design(dict(terminal_resistance_mohm=11))['analysis']['performance']
        self.assertAlmostEqual(b['irreversible_heat_w'] - a['irreversible_heat_w'], 25 * .01)
        self.assertAlmostEqual(a['terminal_voltage_v'] - b['terminal_voltage_v'], 5 * .01)

    def test_kinetics_low_current_limit_and_high_current_nonlinearity(self):
        a = evaluate_design(dict(analysis_current_a=0))
        small = evaluate_design(dict(analysis_current_a=1e-8))
        high = evaluate_design(dict(analysis_current_a=50))
        for side in ['positive', 'negative']:
            self.assertAlmostEqual(component(a, side + '_kinetics')['resistance_mohm'],
                                   component(small, side + '_kinetics')['resistance_mohm'])
            self.assertLess(component(high, side + '_kinetics')['resistance_mohm'],
                            component(a, side + '_kinetics')['resistance_mohm'])
        self.assertEqual(a['analysis']['performance']['irreversible_heat_w'], 0)
        self.assertIsNone(a['analysis']['performance']['capacity_accounting_duration_s'])

    def test_adiabatic_and_convective_heat_limits(self):
        r = evaluate_design(dict(analysis_heat_transfer_w_m2_k=0))
        p = r['analysis']['performance']
        self.assertAlmostEqual(p['average_temperature_rise_k'], p['irreversible_heat_w'] * 60 / r['total_mass_g'])
        cooled = evaluate_design({})['analysis']['performance']
        self.assertLess(cooled['average_temperature_rise_k'], p['average_temperature_rise_k'])
        zero = evaluate_design(dict(analysis_pulse_s=0))
        self.assertEqual(zero['analysis']['performance']['average_temperature_rise_k'], 0)

    def test_diffusivity_does_not_invent_rate_capacity(self):
        a = evaluate_design({})
        b = evaluate_design(dict(positive_diffusivity_m2_s=4e-14))
        self.assertEqual(a['capacity'], b['capacity'])
        self.assertEqual(a['analysis']['resistance'], b['analysis']['resistance'])
        self.assertAlmostEqual(a['analysis']['performance']['diffusion']['positive']['particle_diffusion_time_s'] / 4,
                               b['analysis']['performance']['diffusion']['positive']['particle_diffusion_time_s'])

    def test_unwetted_and_zero_porosity_have_no_infinite_resistance(self):
        for changes in [dict(electrolyte_fill=.5), dict(positive_porosity=0), dict(separator_porosity=0)]:
            r = evaluate_design(changes)
            self.assertEqual(r['analysis']['status'], 'unavailable')
            self.assertIsNone(r['analysis']['resistance'])
            self.assertIsNone(r['analysis']['performance'])
            json.dumps(r, allow_nan=False)
            self.assertGreater(r['capacity']['design_ah'], 0)

    def test_sensitivity_recomputes_fit_and_exposes_comparison_basis(self):
        c = templates()['21700'];
        before = copy.deepcopy(c)
        a = evaluate_design(c)
        self.assertEqual(c, before)
        rows = a['analysis']['sensitivity']['rows']
        self.assertEqual(len(rows), 26)
        thick = next(x for x in rows if x['parameter'] == 'positive_thickness_um' and x['factor'] > 1)
        self.assertLess(thick['metrics']['winding_length_mm'], a['geometry']['length_mm'])
        self.assertEqual(thick['metrics']['current_a'], 5)
        invalid = next(x for x in rows if x['parameter'] == 'positive_contact_fraction' and x['factor'] > 1)
        self.assertEqual(invalid['status'], 'invalid')
        self.assertEqual(invalid['value'], 1.1)
        rated = evaluate_design(dict(analysis_current_mode='c_rate', analysis_c_rate=2))
        for row in rated['analysis']['sensitivity']['rows']:
            if row['status'] == 'available':
                self.assertAlmostEqual(row['metrics']['current_a'], 2 * row['metrics']['design_ah'])

    def test_invalid_inputs_and_immutable_persistence_with_sources(self):
        for change in [dict(negative_first_cycle_efficiency=0), dict(positive_utilization=0),
                       dict(positive_bruggeman=.5), dict(positive_diffusivity_m2_s=0),
                       dict(analysis_current_a=-1), dict(analysis_current_mode='unknown'),
                       dict(analysis_ocv_v=2), dict(graphite_capacity_mah_g=float('inf')),
                       dict(analysis_current_a=True), dict(analysis_temperature_c=-21)]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                evaluate_design(change)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.test_tmp') as directory:
            repo = RunRepository(Path(directory) / 'test.sqlite3')
            record = repo.save_design(dict(input=dict(graphite_capacity_mah_g=330)))
            saved = copy.deepcopy(record)
            record['analysis']['references'][0]['title'] = 'changed'
            self.assertEqual(repo.design(saved['id'], 'default'), saved)
            second = repo.save_design(dict(input=dict(graphite_capacity_mah_g=320)))
            self.assertNotEqual(saved['id'], second['id'])
            self.assertFalse(saved['analysis']['provenance']['applied_to_pybamm'])
            self.assertEqual(len(saved['analysis']['references']), 8)
            json.dumps(saved, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
