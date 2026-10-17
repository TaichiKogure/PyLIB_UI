"""P3 browser regression with native thermal results and isolated storage."""
import copy
import json
import time
import unittest
from pathlib import Path

from playwright.sync_api import expect
from verify_model_tabs import ModelTabTests
from pylibstudy.jobs import TERMINAL


class P3BrowserTests(unittest.TestCase):
    output = Path('docs/evidence/p3')
    tearDownClass = classmethod(ModelTabTests.tearDownClass.__func__)
    setUp = ModelTabTests.setUp
    tearDown = ModelTabTests.tearDown

    @classmethod
    def setUpClass(cls):
        ModelTabTests.setUpClass.__func__(cls)
        cls.output.mkdir(parents=True, exist_ok=True)
        cls.runs = []
        for resistance in (0, .01):
            job = cls.server.jobs.submit(dict(name=f'P3 native contact {resistance}', thermal='lumped',
                                              thermal_settings=dict(capacity_mode='user', cell_heat_capacity_j_k=50,
                                                                    surface_temperature='lumped',
                                                                    casing_heat_capacity_j_k=5,
                                                                    environment_thermal_resistance_k_w=2,
                                                                    contact_resistance_ohm=resistance,
                                                                    source='synthetic browser fixture; not measured'),
                                              protocol=[dict(kind='cc', current_a=3, duration_s=60)]))
            end = time.monotonic() + 150
            while time.monotonic() < end:
                current = cls.server.jobs.get(job['id'], 'default')
                if current['status'] in TERMINAL: break
                time.sleep(.05)
            assert current['status'] == 'completed', current
            cls.runs.append(cls.server.service.repository.get(job['result_id']))
        cls.other = cls.server.service.repository.create_project('P3 isolation')['id']

    def open_run(self):
        self.page.evaluate('async id => showResult(await api(`/api/results/${id}`))', self.runs[1]['id'])
        self.page.locator('#result-explorer').evaluate('(e)=>e.open=true')
        self.page.locator('#result-thermal-details').evaluate('(e)=>e.open=true')

    def test_thermal_settings_restore_units_and_state_preservation(self):
        self.page.evaluate('run=>restorePhysics(run)', self.runs[1])
        self.page.locator('#physics-thermal-settings').evaluate('(e)=>e.open=true')
        expect(self.page.locator('#thermal-cell_heat_capacity_j_k')).to_have_value('50')
        expect(self.page.locator('#thermal-casing_heat_capacity_j_k')).to_be_enabled()
        c = self.page.evaluate('readPhysics()')
        self.assertEqual(c['thermal_settings'], self.runs[1]['input']['thermal_settings'])
        self.page.locator('#physics-thermal').select_option('isothermal')
        expect(self.page.locator('#thermal-cell_heat_capacity_j_k')).to_be_disabled()
        self.assertIsNone(self.page.evaluate('readPhysics().thermal_settings.cell_heat_capacity_j_k'))
        self.page.locator('#physics-thermal').select_option('lumped')
        expect(self.page.locator('#thermal-cell_heat_capacity_j_k')).to_have_value('50')
        self.page.locator('#thermal-source').fill('')
        self.assertFalse(self.page.locator('#thermal-source').evaluate('(e)=>e.checkValidity()'))
        self.page.locator('#physics-parameter_set').select_option('Chen2020_composite')
        expect(self.page.locator('#thermal-heat_of_mixing')).to_be_disabled()
        expect(self.page.locator('#physics-compatibility')).to_contain_text('セル熱容量')
        legacy = copy.deepcopy(self.runs[0]);
        legacy['input'].pop('thermal_settings');
        legacy['input']['config_schema_version'] = '1.2'
        self.page.evaluate('run=>restorePhysics(run)', legacy)
        expect(self.page.locator('#thermal-capacity_mode')).to_have_value('literature')
        expect(self.page.locator('#thermal-contact_resistance_ohm')).to_have_value('0')

    def test_native_energy_units_csv_and_comparison_save_restore(self):
        self.open_run()
        expect(self.page.locator('#result-thermal-energy')).to_contain_text('許容差内')
        expect(self.page.locator('#result-thermal-summary')).to_contain_text('synthetic browser fixture')
        self.page.locator('#result-variable').select_option('total_heat_with_contact_w')
        self.page.locator(f'input[aria-label="{self.runs[0]["name"]}を比較"]').check()
        expect(self.page.locator('#result-thermal-comparison tbody tr')).to_have_count(2)
        expect(self.page.locator('#legend')).to_contain_text(self.runs[0]['name'])
        expect(self.page.locator('#chart svg')).to_have_attribute('aria-label',
                                                                  '接触を含む合計発熱 (W)の比較グラフ。2本。')
        self.page.locator('#comparison-name').evaluate('(e)=>e.closest("details").open=true')
        self.page.locator('#comparison-name').fill('P3 thermal comparison')
        self.page.locator('#save-comparison').click()
        expect(self.page.locator('#message')).to_contain_text('保存しました')
        records = self.page.request.get(self.url + '/api/comparisons?project_id=default').json()
        self.assertEqual(records[0]['variable'], 'total_heat_with_contact_w')
        self.page.reload();
        expect(self.page.locator('#run')).to_be_enabled()
        self.page.locator('#comparison-name').evaluate('(e)=>e.closest("details").open=true')
        self.page.locator('#comparison-list button').first.click()
        expect(self.page.locator('#result-variable')).to_have_value('total_heat_with_contact_w')
        self.page.locator('#result-explorer').evaluate('(e)=>e.open=true')
        self.page.locator('#result-thermal-details').evaluate('(e)=>e.open=true')
        expect(self.page.locator('#result-thermal-comparison tbody tr')).to_have_count(2)
        csv = self.page.request.get(self.url + f'/api/results/{self.runs[1]["id"]}.csv').text()
        self.assertIn('contact_heating_w', csv)
        self.page.locator('#result-thermal-details').screenshot(path=str(self.output / 'thermal-result-desktop.png'))

    def test_mobile_and_old_result_without_thermal_metadata(self):
        self.open_run()
        self.page.set_viewport_size(dict(width=390, height=844))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.locator('#result-thermal-details').screenshot(path=str(self.output / 'thermal-result-mobile.png'))
        self.page.evaluate('run=>restorePhysics(run)', self.runs[1])
        self.page.locator('#physics-thermal-settings').evaluate('(e)=>e.open=true')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.locator('#physics-thermal-settings').screenshot(path=str(self.output / 'thermal-settings-mobile.png'))
        old = copy.deepcopy(self.runs[0]);
        old.pop('thermal_provenance');
        old.pop('thermal_balance')
        self.page.evaluate('run=>showResult(run)', old)
        expect(self.page.locator('#result-thermal-summary')).to_contain_text('旧結果')

    def test_project_switch_ignores_delayed_comparison_response(self):
        self.open_run()
        self.page.evaluate('''run => {
            window.realP3Api = api;
            api = (path, ...args) => path === `/api/results/${run.id}` ? new Promise(resolve => window.releaseP3Comparison = () => resolve(run)) : realP3Api(path,...args);
        }''', self.runs[0])
        self.page.locator(f'input[aria-label="{self.runs[0]["name"]}を比較"]').check()
        self.page.evaluate('id=>{library.projectId=id;state.comparisons.clear();}', self.other)
        self.page.evaluate('releaseP3Comparison()')
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('state.comparisons.size'), 0)
        self.page.evaluate('()=>{api=window.realP3Api;}')


if __name__ == '__main__': unittest.main(verbosity=2)
