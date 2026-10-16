"""Browser checks for design screening; temporary DB, existing installed Edge."""
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pylibstudy.server import create_server


class DesignAnalysisBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='design-screening-', dir=ROOT / '.test_tmp')
        cls.server = create_server(0, cls.directory.name)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.evidence = ROOT / 'docs' / 'evidence' / 'design-analysis'
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
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        expect(self.page.locator('#run')).to_be_enabled(timeout=30000)
        self.page.locator('#tab-design').click()
        self.wait_result()

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def wait_result(self):
        self.page.wait_for_function('() => designing.result !== null')
        expect(self.page.locator('#design-insights')).to_contain_text('活物質容量と設計変更の影響')

    def fill(self, name, value):
        control = self.page.locator(f'#design-form [name="{name}"]')
        control.evaluate("el => { el.closest('details').open = true; }")
        control.fill(str(value))
        self.wait_result()

    def test_initial_results_formulas_sources_and_graph(self):
        expect(self.page.locator('#design-insights')).to_contain_text('10.740 mΩ')
        self.page.get_by_text('計算式・単位・近似の前提', exact=True).click()
        expect(self.page.locator('#design-insights')).to_contain_text('n F/(3.6 M)')
        self.page.get_by_text('論文・公式資料と、この計算での使い方（8件）', exact=True).click()
        links = self.page.locator('.insight-sources a')
        expect(links).to_have_count(8)
        for link in links.all():
            self.assertTrue(link.get_attribute('href').startswith('https://'))
            self.assertEqual(link.get_attribute('rel'), 'noopener noreferrer')
        select = self.page.locator('#design-sensitivity-metric')
        for key, text in [('design_ah', '設計容量'), ('terminal_voltage_v', '端子電圧'), ('heat_w', '不可逆発熱')]:
            select.select_option(key)
            expect(self.page.locator('.insight-sensitivity-chart svg')).to_have_attribute('aria-label',
                                                                                          __import__('re').compile(
                                                                                              text))

    def test_edits_invalidate_results_and_use_latest_revision(self):
        original = self.page.evaluate('designing.result.capacity.positive_ah')
        self.fill('positive_capacity_mah_g', 180)
        self.assertAlmostEqual(self.page.evaluate('designing.result.capacity.positive_ah'), original * .9)
        field = self.page.locator('#design-form [name="positive_capacity_mah_g"]')
        field.fill('175')
        field.fill('185')
        self.wait_result()
        self.page.wait_for_function(
            '() => designing.result !== null && designing.result.input.positive_capacity_mah_g === 185')
        self.assertAlmostEqual(self.page.evaluate('designing.result.capacity.positive_ah'), original * .925)
        self.page.locator('#design-form [name="diameter_mm"]').fill('1')
        expect(self.page.locator('#design-status')).to_contain_text('入力を修正')
        expect(self.page.locator('#design-insights')).to_be_empty()
        expect(self.page.locator('#design-save')).to_be_disabled()
        expect(self.page.locator('#design-export')).to_be_disabled()

    def test_save_restore_export_and_analysis_isolation(self):
        self.fill('graphite_capacity_mah_g', 330)
        self.fill('analysis_temperature_c', -10)
        self.page.locator('#design-save').click()
        expect(self.page.locator('#design-status')).to_contain_text('保存しました')
        saved = self.page.evaluate('designing.saved')
        self.fill('graphite_capacity_mah_g', 310)
        self.page.locator('#design-saved').select_option(saved['id'])
        expect(self.page.locator('#design-form [name="graphite_capacity_mah_g"]')).to_have_value('330')
        expect(self.page.locator('#design-form [name="analysis_temperature_c"]')).to_have_value('-10')
        self.assertEqual(self.page.evaluate('designing.result.analysis'), saved['analysis'])
        with self.page.expect_download() as download:
            self.page.locator('#design-export').click()
        import json
        result = json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        self.assertEqual(result['analysis'], saved['analysis'])
        physics = self.page.evaluate('readPhysics()')
        self.page.locator('#tab-SPMe').click()
        self.assertEqual(self.page.evaluate('readPhysics()'), physics)

    def test_legacy_saved_design_does_not_inherit_new_input_values(self):
        self.fill('graphite_capacity_mah_g', 300)
        self.page.evaluate('''() => {
            const legacy = JSON.parse(JSON.stringify(designing.result));
            delete legacy.analysis;
            delete legacy.input.graphite_capacity_mah_g;
            legacy.id = 'legacy-screening-test';
            legacy.created_at = '2026-10-15T00:00:00Z';
            legacy.project_id = library.projectId;
            designing.records.push(legacy);
            const option = document.createElement('option');
            option.value = legacy.id;
            option.textContent = '旧版の保存設計';
            document.getElementById('design-saved').append(option);
        }''')
        self.page.locator('#design-saved').select_option('legacy-screening-test')
        expect(self.page.locator('#design-form [name="graphite_capacity_mah_g"]')).to_have_value('0')
        expect(self.page.locator('#design-insights')).to_contain_text('追加前です')
        self.page.get_by_text('この設計を新しい式で再評価', exact=True).click()
        self.wait_result()
        self.assertEqual(self.page.evaluate('designing.result.analysis.provenance.specific_capacities_mah_g.graphite'),
                         350)
        self.assertIsNone(self.page.evaluate('designing.saved'))

    def test_invalid_transport_is_visible_without_stale_numbers(self):
        self.fill('electrolyte_fill', .5)
        expect(self.page.locator('#design-insights .insight-warning')).to_contain_text('注液充填率=1')
        self.assertIsNone(self.page.evaluate('designing.result.analysis.resistance'))
        expect(self.page.locator('.insight-metrics')).to_contain_text('算出対象外')
        self.fill('electrolyte_fill', 1)
        expect(self.page.locator('.insight-metrics')).to_contain_text('10.740 mΩ')

    def test_fixed_c_rate_and_contact_change(self):
        self.fill('positive_contact_fraction', .5)
        details = self.page.evaluate('designing.result.analysis.resistance')
        contact = next(x for x in details['components'] if x['id'] == 'positive_contact')
        self.assertGreater(contact['resistance_mohm'], 0)
        mode = self.page.locator('#design-form [name="analysis_current_mode"]')
        mode.evaluate("el => { el.closest('details').open = true; }")
        mode.select_option('c_rate')
        self.wait_result()
        expect(self.page.locator('#design-form [name="analysis_current_a"]')).to_be_disabled()
        expect(self.page.locator('#design-form [name="analysis_c_rate"]')).to_be_enabled()
        expect(self.page.locator('.insight-evaluation-point')).to_contain_text('固定Cレートで比較')

    def test_desktop_and_mobile_have_no_page_overflow(self):
        for width in [1440, 820, 390]:
            self.page.set_viewport_size(dict(width=width, height=1000))
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
        self.page.screenshot(path=str(self.evidence / 'mobile-390.png'), full_page=True)
        self.page.set_viewport_size(dict(width=1440, height=1000))
        self.page.locator('#design-insights').screenshot(path=str(self.evidence / 'desktop-insights.png'))

    def test_live_solver_diagnostics_can_be_displayed(self):
        import json
        run = json.loads((self.evidence / 'literature-composite-dfn.json').read_text(encoding='utf-8'))
        self.page.evaluate('(run) => showResult(run)', run)
        expect(self.page.locator('#snapshot')).to_contain_text('SPMe/DFNが計算した損失・発熱の内訳')
        expect(self.page.locator('#snapshot')).to_contain_text('ヒステリシス発熱')
        expect(self.page.locator('#snapshot')).to_contain_text('混合熱（現設定は無効）')
        self.assertEqual(len(run['diagnostic_summary']), 11)


if __name__ == '__main__':
    unittest.main(verbosity=2)
