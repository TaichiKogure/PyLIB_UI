"""P4 browser integration with an isolated local database."""
import sys, unittest, json
from pathlib import Path
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_model_tabs import ModelTabTests


class MaterialUITests(ModelTabTests):
    def open_materials(self):
        self.page.locator('#material-settings').evaluate('(e)=>e.open=true')

    def test_lfp_and_half_cell_selection_boundaries(self):
        self.page.locator('#physics-parameter_set').select_option('Prada2013')
        expect(self.page.locator('#physics-min_voltage_v')).to_have_value('2')
        self.assertFalse(self.page.locator('#thermal-isothermal_heat_source').is_checked())
        self.page.locator('#physics-parameter_set').select_option('Xu2019')
        expect(self.page.locator('#physics-model')).to_have_value('DFN')
        expect(self.page.locator('#physics-reference_electrode_fraction')).to_have_value('')
        with self.page.expect_response('**/api/physics/preview') as response: self.page.locator(
            '#physics-preview-button').click()
        self.assertEqual(response.value.status, 200)
        expect(self.page.locator('#physics-preview-status')).to_contain_text('0.0024 Ah')

    def test_inventory_compare_filter_and_mobile(self):
        self.open_materials();
        self.page.locator('#material-browser').evaluate('(e)=>e.open=true')
        self.page.locator('#material-filter').fill('diffusivity')
        expect(self.page.locator('#material-inventory')).to_contain_text('Negative particle diffusivity')
        self.assertEqual(self.page.locator('#material-view option').count(), 19)
        self.page.locator('#material-compare').select_option('NCA_Kim2011')
        expect(self.page.locator('#material-inventory')).to_contain_text('異なる')
        out = Path('docs/evidence/p4');
        out.mkdir(parents=True, exist_ok=True)
        self.page.locator('#material-settings').screenshot(path=str(out / 'materials-desktop.png'))
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.screenshot(path=str(out / 'materials-mobile.png'), full_page=True)

    def test_custom_capacity_restore_and_preview(self):
        self.open_materials()
        self.page.evaluate('''() => {
            const c={...physical.config.defaults, material_settings:{...physical.config.defaults.material_settings,source:'synthetic browser check',overrides:{'Nominal cell capacity [A.h]':4}}};
            setPhysics(c);
        }''')
        config = self.page.evaluate('readPhysics()')
        self.assertEqual(config['material_settings']['overrides']['Nominal cell capacity [A.h]'], 4)
        response = self.page.request.post(self.url + '/api/physics/validate', data=config)
        self.assertEqual(response.status, 200)
        self.page.evaluate('(c)=>setPhysics(c)', response.json()['input'])
        self.assertEqual(self.page.evaluate('readPhysics()'), response.json()['input'])
        with self.page.expect_response('**/api/physics/preview') as result: self.page.locator(
            '#physics-preview-button').click()
        self.assertEqual(result.value.status, 200)
        expect(self.page.locator('#physics-preview-status')).to_contain_text('4.0000 Ah')

    def test_bpx_file_input_original_restore_and_missing_properties(self):
        self.open_materials();
        self.page.locator('#material-bpx-file').evaluate('(e)=>e.closest("details").open=true')
        fixture = Path('pylibstudy/data/bpx_reference.json')
        self.page.locator('#material-bpx-file').set_input_files(str(fixture.resolve()))
        expect(self.page.locator('#physics-parameter_set')).to_have_value('BPX')
        expect(self.page.locator('#material-bpx-status')).to_contain_text('12.5 Ah')
        config = self.page.evaluate('readPhysics()')
        self.assertEqual(config['material_settings']['bpx_original_text'], fixture.read_text(encoding='utf-8'))
        response = self.page.request.post(self.url + '/api/physics/validate', data=config)
        self.assertEqual(response.status, 200)
        self.page.evaluate('(c)=>setPhysics(c)', response.json()['input'])
        self.assertEqual(self.page.evaluate('readPhysics()'), response.json()['input'])
        self.page.locator('#physics-parameter_set').select_option('Chen2020')
        self.assertIsNone(self.page.evaluate('readPhysics().material_settings.bpx'))
        self.page.locator('#physics-parameter_set').select_option('BPX')
        self.assertEqual(self.page.evaluate('readPhysics().material_settings.bpx.Header.Title'),
                         config['material_settings']['bpx']['Header']['Title'])
        config['parameter_set'] = 'Chen2020';
        config['material_settings'].update(bpx=None, bpx_original_text=None, transport='tortuosity factor')
        response = self.page.request.post(self.url + '/api/physics/validate', data=config)
        self.assertEqual(response.status, 400)
        self.assertIn('tortuosity', response.json()['error'])

    def test_material_result_provenance_and_restore(self):
        result = json.loads(Path('docs/evidence/p4/custom_capacity.json').read_text(encoding='utf-8'))
        self.page.evaluate('(r)=>{showResult(r);setPhysics(r.input)}', result)
        expect(self.page.locator('#result-material-source')).to_contain_text('synthetic explicit capacity')
        expect(self.page.locator('#result-material-differences')).to_contain_text('Nominal cell capacity')
        self.assertEqual(self.page.evaluate('readPhysics().material_settings.overrides["Nominal cell capacity [A.h]"]'),
                         4)


if __name__ == '__main__':
    # Inherit existing navigation assertions; do not rediscover the imported base class.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MaterialUITests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
