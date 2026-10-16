"""Local Edge browser and HTTP regression for public cathode curves (isolated DB)."""
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pylibstudy.server import create_server


class CathodeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='cathode-ui-', dir=ROOT / '.test_tmp')
        cls.server = create_server(0, cls.directory.name)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.evidence = ROOT / 'docs/evidence/cathode-curves'
        cls.evidence.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.directory.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport=dict(width=1440, height=1000))
        self.errors = []
        self.network = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('requestfailed', lambda request: self.network.append([request.url, request.failure]))
        self.page.on('response', lambda response: self.network.append([response.url, response.status]))
        self.page.on('requestfinished', lambda request: self.network.append(['finished', request.url]))
        self.page.goto(self.url)
        expect(self.page.locator('#run')).to_be_enabled(timeout=30000)
        self.page.locator('#tab-cathodes').click()
        self.page.evaluate('''() => {
            window.testEvents = [];
            for (const kind of ['pointerdown', 'pointerup', 'click', 'submit', 'invalid', 'change']) {
                document.addEventListener(kind, e => window.testEvents.push([kind, e.target.id, e.target.value]), true);
            }
        }''')

    def tearDown(self):
        outcome = self._outcome.result
        if any(test is self for test, trace in outcome.failures + outcome.errors):
            print('NETWORK', [x for x in self.network if '/api/cathodes' in str(x) or '/api/results' in str(x)])
        self.page.close()
        self.assertEqual(self.errors, [])

    def calculate(self):
        old = self.page.evaluate('state.current?.id || null')
        invalid = self.page.locator('#cathode-form :invalid').evaluate_all(
            'els => els.map(e => [e.id, e.value, e.validationMessage])')
        self.assertEqual(invalid, [])
        self.page.locator('#cathode-run').click()
        try:
            self.page.wait_for_function(
                '(old) => state.current?.record_type === "reference_curve" && state.current.id !== old', arg=old,
                timeout=15000)
        except Exception as error:
            self.fail(str(error) + ' status=' + self.page.locator(
                '#cathode-status').inner_text() + ' message=' + self.page.locator('#message').inner_text()
                      + ' debug=' + str(self.page.evaluate(
                '({events:window.testEvents,busy:state.busy,submitting:cathodes.submitting,input:readCathode()})'))
                      + ' network=' + str(self.network))
        return self.page.evaluate('state.current')

    def fill(self, name, value):
        self.page.locator('#cathode-' + name).fill(str(value))

    def test_catalog_sources_conditions_and_plot(self):
        expect(self.page.locator('#cathode-curve option')).to_have_count(8)
        curves = self.page.evaluate('cathodes.config.catalog.curves')
        for c in curves:
            self.page.locator('#cathode-curve').select_option(c['id'])
            expect(self.page.locator('#cathode-chart svg')).to_have_count(1)
            expect(self.page.locator('#cathode-source')).to_contain_text(c['composition'])
            link = self.page.locator('#cathode-source a').first
            self.assertTrue(link.get_attribute('href').startswith('https://'))
            self.assertEqual(link.get_attribute('rel'), 'noopener noreferrer')
        self.page.locator('#cathode-curve').select_option('lmfp_2022_fmc_cycle3')
        expect(self.page.locator('#cathode-source')).to_contain_text('70°C')
        expect(self.page.locator('#cathode-source')).to_contain_text('ベクトル抽出')
        self.page.locator('#cathode-reference-current').click()
        expect(self.page.locator('#cathode-current_a')).to_have_value('0.7')
        self.page.locator('#cathodes-panel').screenshot(path=str(self.evidence / 'lmfp-panel.png'))
        for fmt in ['csv', 'json']:
            with self.page.expect_download() as download:
                self.page.locator('#cathode-source-' + fmt).click()
            path = self.evidence / ('lmfp-reference.' + fmt)
            download.value.save_as(path)
            text = path.read_text(encoding='utf-8-sig')
            self.assertIn('CC BY 4.0', text)
            self.assertIn('vector_figure_digitized', text)
            self.assertIn('LiMn0.6Fe0.4PO4', text)

    def test_lco_upper_cutoff_and_restore(self):
        self.page.locator('#cathode-curve').select_option('lco2018_bare_cycle3')
        self.page.locator('#cathode-mode').select_option('charge')
        r = self.calculate()
        self.assertEqual(r['termination'], 'positive_upper_voltage')
        self.assertAlmostEqual(r['summary']['final_positive_v'], 4.55)
        expect(self.page.locator('#result-meta')).to_contain_text('対Li基準の上限')
        self.fill('positive_mass_g', 6)
        self.page.locator('#restore').click()
        expect(self.page.locator('#tab-cathodes')).to_have_attribute('aria-selected', 'true')
        expect(self.page.locator('#cathode-positive_mass_g')).to_have_value('10')

    def test_separate_voltage_basis_and_electrode_charts(self):
        expect(self.page.locator('#cathode-cell_max_v')).to_be_disabled()
        self.page.locator('#cathode-voltage_basis').select_option('full_cell')
        expect(self.page.locator('#cathode-cell_max_v')).to_be_enabled()
        self.page.locator('#cathode-mode').select_option('charge')
        self.fill('positive_max_v', 4.55)
        self.fill('cell_max_v', 4.2)
        r = self.calculate()
        self.assertEqual(r['termination'], 'cell_upper_voltage')
        self.assertAlmostEqual(r['summary']['final_terminal_v'], 4.2)
        self.assertGreater(r['summary']['final_positive_v'], 4.2)
        for key in ['positive_reference_v', 'negative_reference_v', 'voltage_v']:
            self.page.locator(f'[data-chart="{key}"]').click()
            expect(self.page.locator('#chart svg')).to_have_count(1)
        expect(self.page.locator('#legend')).to_contain_text('セル端子電圧')
        self.page.locator('#cathodes-panel').screenshot(path=str(self.evidence / 'full-cell-panel.png'))

    def test_unrecorded_lower_range_and_source_temperature(self):
        self.fill('positive_min_v', 1.5)
        expect(self.page.locator('#cathode-status')).to_contain_text('未収録')
        r = self.calculate()
        self.assertEqual(r['termination'], 'positive_source_end')
        self.assertAlmostEqual(r['summary']['final_positive_v'], 3)
        self.assertGreater(r['summary']['capacity_ah'], 1)
        self.page.locator('#cathode-curve').select_option('lfp_2022_fmc_cycle3')
        self.calculate()
        expect(self.page.locator('#metric-temp-title')).to_have_text('参照測定温度')
        expect(self.page.locator('#metric-temp')).to_have_text('70.0')
        expect(self.page.locator('#metric-temp-kind')).to_contain_text('温度計算なし')

    def test_ocp_assumption_and_data_license(self):
        self.page.locator('#cathode-curve').select_option('nmc622_wan2026')
        expect(self.page.locator('#cathode-ocp_capacity_mah_g')).to_be_enabled()
        self.fill('ocp_capacity_mah_g', 180)
        r = self.calculate()
        self.assertFalse(r['mapping']['independent_charge_discharge'])
        self.assertEqual(r['mapping']['capacity_basis'], 'user_assumed_ocp_scale')
        self.page.locator('#cathode-curve').select_option('nmc111_pybep')
        expect(self.page.locator('#cathode-source')).to_contain_text('CC BY-NC-SA 4.0')

    def test_save_export_reload_and_project_isolation(self):
        self.fill('name', 'cathode browser saved')
        r = self.calculate()
        self.page.locator('#save').click()
        expect(self.page.locator('#result-state')).to_contain_text('保存済み')
        row = self.page.locator('#history .history-row').filter(has_text='cathode browser saved')
        expect(row).to_have_count(1)
        row.locator('input[type="checkbox"]').check()
        self.page.locator('#cathode-curve').select_option('lmfp_2022_fmc_cycle3')
        self.calculate()
        expect(self.page.locator('#legend')).to_contain_text('cathode browser saved')
        row.get_by_role('button', name='表示', exact=True).click()
        self.page.wait_for_function('(id) => state.current?.id === id', arg=r['id'])
        with self.page.expect_download() as download:
            self.page.locator('#csv').click()
        path = self.evidence / 'reference-result.csv'
        download.value.save_as(path)
        text = path.read_text(encoding='utf-8-sig')
        self.assertIn('source_snapshot', text)
        self.assertIn('positive_reference_v', text)
        self.page.reload()
        expect(self.page.locator('#run')).to_be_enabled(timeout=30000)
        self.page.locator('#history .history-row').filter(has_text='cathode browser saved').get_by_role('button',
                                                                                                        name='表示',
                                                                                                        exact=True).click()
        self.page.wait_for_function('(id) => state.current?.id === id', arg=r['id'])
        expect(self.page.locator('#legend')).to_contain_text('対Li基準')
        self.page.locator('#project-name').fill('cathode isolated project')
        self.page.locator('#create-project').click()
        expect(self.page.locator('#history')).to_contain_text('まだ保存した結果はありません')

    def test_navigation_and_mobile_layout(self):
        self.fill('positive_mass_g', 7)
        self.page.locator('#tab-synthetic').click()
        expect(self.page.locator('#cathodes-panel')).to_be_hidden()
        self.page.locator('#tab-cathodes').click()
        expect(self.page.locator('#cathode-positive_mass_g')).to_have_value('7')
        self.page.set_viewport_size(dict(width=390, height=844))
        self.page.locator('#cathode-curve').select_option('lmfp_2022_fmc_cycle3')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 392)
        self.page.locator('#cathodes-panel').screenshot(path=str(self.evidence / 'mobile-panel.png'))

    def test_http_contract_rejects_unknown_and_nonfinite(self):
        response = self.page.request.post(self.url + '/api/cathodes/simulate', data={'curve_id': '../../bad'})
        self.assertEqual(response.status, 400)
        response = self.page.request.post(self.url + '/api/cathodes/simulate', data={'current_a': True})
        self.assertEqual(response.status, 400)
        response = self.page.request.get(self.url + '/api/cathodes')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()['catalog']['voltage_reference'], 'Li/Li+')


if __name__ == '__main__':
    unittest.main(verbosity=2)
