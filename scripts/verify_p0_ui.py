"""P0 browser contracts, isolated storage; uses installed Edge via Playwright."""
import json
import argparse
import unittest
from pathlib import Path

from playwright.sync_api import expect
from verify_model_tabs import ModelTabTests


class P0BrowserTests(unittest.TestCase):
    output_dir = Path('docs/evidence/p0')
    setUpClass = classmethod(ModelTabTests.setUpClass.__func__)
    tearDownClass = classmethod(ModelTabTests.tearDownClass.__func__)
    setUp = ModelTabTests.setUp
    tearDown = ModelTabTests.tearDown

    def test_catalog_options_filter_and_environment_refresh(self):
        self.page.locator('#physics-initial_soc').fill('0.63')
        original = self.page.evaluate('readPhysics()')
        self.page.locator('#capabilities-link').click()
        expect(self.page.locator('#capabilities-summary')).to_contain_text('39設定キー')
        expect(self.page.locator('#capabilities-combinations tbody tr')).to_have_count(16)
        expect(self.page.locator('#capabilities-checks tbody tr')).to_have_count(7)
        self.page.get_by_text('全39設定キーの接続状態', exact=True).click()
        expect(self.page.locator('#capabilities-options tbody tr')).to_have_count(39)
        self.page.get_by_text('機能一覧83項目と実装段階', exact=True).click()
        self.page.locator('#capabilities-search').fill('F11')
        expect(self.page.locator('#capabilities-features tbody tr')).to_have_count(1)
        expect(self.page.locator('#capabilities-features')).to_contain_text('IDAKLU')
        self.page.locator('#capabilities-search').fill('does-not-exist')
        expect(self.page.locator('#capabilities-feature-count')).to_have_text('0 / 83項目')
        self.page.locator('#capabilities-search').fill('')
        self.page.locator('#capabilities-filter').select_option('調査')
        expect(self.page.locator('#capabilities-feature-count')).not_to_have_text('0 / 83項目')
        self.page.locator('#capabilities-probe').click()
        expect(self.page.locator('#capabilities-probe')).to_be_enabled(timeout=30000)
        expect(self.page.locator('#physics-run')).to_be_enabled()
        self.assertEqual(self.page.evaluate('readPhysics()'), original)
        self.page.locator('#capabilities-panel').screenshot(path=str(self.output_dir / 'catalog-desktop.png'))

    def test_legacy_restore_and_rejection_preserve_editor(self):
        legacy = json.loads(Path('docs/evidence/step03/spme_normal.json').read_text(encoding='utf-8'))
        for key in ('config_schema_version', 'solver', 'model_options'):
            legacy['input'].pop(key, None)
        legacy['input']['initial_soc'] = .37
        self.page.evaluate('run => restorePhysics(run)', legacy)
        expect(self.page.locator('#physics-initial_soc')).to_have_value('0.37')
        current = self.page.evaluate('readPhysics()')
        legacy['input']['config_schema_version'] = '9.0'
        self.page.evaluate('run => restorePhysics(run)', legacy)
        expect(self.page.locator('#message')).to_contain_text('スキーマ版')
        self.assertEqual(self.page.evaluate('readPhysics()'), current)
        self.page.locator('#physics-parameter_set').select_option('Chen2020_composite')
        expect(self.page.locator('#physics-model')).to_have_value('DFN')
        expect(self.page.locator('#physics-model option[value="SPMe"]')).to_have_js_property('disabled', True)
        expect(self.page.locator('#physics-thermal option[value="lumped"]')).to_have_js_property('disabled', False)
        self.page.locator('#physics-thermal').select_option('lumped')
        expect(self.page.locator('#physics-compatibility')).to_contain_text('セル熱容量')
    def test_missing_environment_keeps_catalog_available(self):
        def missing_environment(route):
            response = route.fetch()
            config = response.json()
            config['environment'] = {'available': False, 'message': 'test: 固定計算環境がありません。'}
            config['capabilities']['environment'] = config['environment']
            route.fulfill(response=response, json=config)

        self.page.route('**/api/physics/config', missing_environment)
        self.page.reload()
        expect(self.page.locator('#run')).to_be_enabled(timeout=30000)
        expect(self.page.locator('#physics-run')).to_be_disabled()
        self.page.locator('#capabilities-link').click()
        expect(self.page.locator('#capabilities-environment')).to_contain_text('固定計算環境がありません')
        expect(self.page.locator('#capabilities-summary')).to_contain_text('83機能')

    def test_catalog_mobile_has_no_page_overflow(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('#capabilities-link').click()
        self.page.get_by_text('全39設定キーの接続状態', exact=True).click()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.page.locator('#capabilities-panel').screenshot(path=str(self.output_dir / 'catalog-mobile.png'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/p0'))
    args = parser.parse_args()
    P0BrowserTests.output_dir = args.output
    args.output.mkdir(parents=True, exist_ok=True)
    # Avoid importing ModelTabTests as a second test class into this module's runner.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(P0BrowserTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
